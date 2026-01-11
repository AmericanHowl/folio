#!/usr/bin/env python3
"""
Folio Server - Serves static files and manages Calibre library via direct DB access
No Calibre Content Server needed - reads directly from metadata.db
"""
import http.server
import http.cookiejar
import socketserver
from socketserver import ThreadingMixIn
import urllib.request
from urllib.parse import urlparse, parse_qs
import json
import subprocess
import os
import base64
import tempfile
import re
import sqlite3
from pathlib import Path
import time
import random
import shutil
import threading
import glob as glob_module
from functools import wraps

PORT = 9099

# ============================================
# API Response Cache
# ============================================

class APICache:
    """Simple in-memory cache with TTL for API responses"""
    
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()
    
    def get(self, key):
        """Get cached value if not expired"""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                else:
                    # Expired, remove it
                    del self._cache[key]
            return None
    
    def set(self, key, value, ttl_seconds):
        """Cache a value with TTL"""
        with self._lock:
            expiry = time.time() + ttl_seconds
            self._cache[key] = (value, expiry)
    
    def clear(self, pattern=None):
        """Clear cache entries, optionally matching a pattern"""
        with self._lock:
            if pattern is None:
                self._cache.clear()
            else:
                keys_to_delete = [k for k in self._cache if pattern in k]
                for key in keys_to_delete:
                    del self._cache[key]
    
    def stats(self):
        """Get cache statistics"""
        with self._lock:
            now = time.time()
            valid_count = sum(1 for _, (_, expiry) in self._cache.items() if now < expiry)
            return {
                'total_entries': len(self._cache),
                'valid_entries': valid_count,
                'keys': list(self._cache.keys())
            }

# Global cache instance
# TTL values (in seconds):
# - Hardcover trending/recent: 5 minutes (data changes infrequently)
# - Hardcover lists: 10 minutes (lists are fairly static)
# - iTunes search: 30 minutes (metadata is stable)
api_cache = APICache()

# ============================================
# Cover Metadata Cache (for concurrent cover requests)
# ============================================

class CoverCache:
    """Cache book cover metadata to avoid DB hits on every cover request.
    
    This solves the issue where many concurrent cover requests cause SQLite
    contention, leading to random timeouts and inconsistent cover loading.
    """
    
    def __init__(self, ttl_seconds=300):  # 5 minute TTL
        self._cache = {}  # book_id -> {'path': str, 'has_cover': bool}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._expiry = 0
        self._loading = False
    
    def get(self, book_id):
        """Get cached cover info for a book"""
        with self._lock:
            if time.time() > self._expiry:
                return None
            return self._cache.get(book_id)
    
    def get_all(self):
        """Get all cached cover info (for bulk lookups)"""
        with self._lock:
            if time.time() > self._expiry:
                return None
            return self._cache.copy()
    
    def load_all(self, force=False):
        """Load all book cover metadata from DB into cache.
        
        This is called once on startup and periodically refreshed.
        Uses a loading flag to prevent concurrent loads.
        """
        with self._lock:
            # Check if already loading or cache is still valid
            if self._loading:
                return False
            if not force and time.time() < self._expiry:
                return True
            self._loading = True
        
        try:
            library_path = get_calibre_library()
            db_path = os.path.join(library_path, 'metadata.db')
            
            if not os.path.exists(db_path):
                return False
            
            # Use WAL mode and read-only for better concurrency
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30.0)
            conn.row_factory = sqlite3.Row
            
            cursor = conn.cursor()
            cursor.execute("SELECT id, path, has_cover FROM books")
            rows = cursor.fetchall()
            conn.close()
            
            new_cache = {}
            for row in rows:
                new_cache[row['id']] = {
                    'path': row['path'],
                    'has_cover': bool(row['has_cover'])
                }
            
            with self._lock:
                self._cache = new_cache
                self._expiry = time.time() + self._ttl
                self._loading = False
            
            print(f"📦 Cover cache loaded: {len(new_cache)} books")
            return True
            
        except Exception as e:
            print(f"❌ Cover cache load error: {e}")
            with self._lock:
                self._loading = False
            return False
    
    def invalidate(self, book_id=None):
        """Invalidate cache for a specific book or all books"""
        with self._lock:
            if book_id is not None:
                self._cache.pop(book_id, None)
            else:
                self._expiry = 0  # Force full reload on next access

# Global cover cache instance
cover_cache = CoverCache(ttl_seconds=300)  # 5 minute TTL

CACHE_TTL_HARDCOVER_TRENDING = 300  # 5 minutes
CACHE_TTL_HARDCOVER_RECENT = 300    # 5 minutes  
CACHE_TTL_HARDCOVER_LISTS = 600     # 10 minutes
CACHE_TTL_HARDCOVER_LIST = 600      # 10 minutes
CACHE_TTL_HARDCOVER_AUTHOR = 600    # 10 minutes
CACHE_TTL_ITUNES_SEARCH = 1800      # 30 minutes
CONFIG_FILE = "config.json"
IMPORTED_FILES_FILE = "imported_files.json"  # Persists list of already-imported files
HARDCOVER_API_URL = "https://api.hardcover.app/v1/graphql"

# Global config
config = {
    'calibre_library': os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library')),
    'calibredb_path': os.getenv('CALIBREDB_PATH', ''),  # Auto-detected if empty
    'hardcover_token': os.getenv('HARDCOVER_TOKEN', ''),
    'prowlarr_url': os.getenv('PROWLARR_URL', ''),
    'prowlarr_api_key': os.getenv('PROWLARR_API_KEY', ''),
    'requested_books': [],  # Store requested book IDs with timestamps
    # Import folder settings
    'import_folder': os.getenv('IMPORT_FOLDER', ''),  # Empty = disabled
    'import_interval': int(os.getenv('IMPORT_INTERVAL', '60')),  # Seconds between scans
    'import_recursive': os.getenv('IMPORT_RECURSIVE', 'true').lower() == 'true',  # Scan subdirs
    'import_delete': os.getenv('IMPORT_DELETE', 'true').lower() == 'true',  # Delete from import folder after successful import (default: true)
}

# Import watcher state
import_state = {
    'running': False,
    'last_scan': None,
    'last_import': None,
    'imported_files': [],  # Track already imported files to avoid duplicates
    'last_imported_count': 0,
    'total_imported': 0,
    'errors': [],
    # KEPUB conversion tracking
    'kepub_converting': None,  # Currently converting file (None if idle)
    'kepub_convert_start': None,  # When current conversion started
    'kepub_last_file': None,  # Last file that was converted
    'kepub_last_success': None,  # True/False for last conversion result
    'kepub_last_log': None,  # Full log output from last kepubify run
}

# Threading lock to protect import_state from concurrent access
import_state_lock = threading.Lock()

# Track watcher thread to prevent duplicates
_import_watcher_thread = None


def sanitize_token(token):
    """Sanitize API token by removing whitespace, newlines, and 'Bearer ' prefix."""
    if not token:
        return ''
    # Strip whitespace and newlines
    token = token.strip()
    # Remove 'Bearer ' prefix if present (users sometimes paste the full header)
    if token.startswith('Bearer '):
        token = token[7:]
    return token.strip()


def load_config():
    """Load configuration from file, merging with environment variables.

    Environment variables take precedence over file values when set.
    This allows Docker deployments to override config via env vars.
    """
    global config

    # Start with environment variable defaults (sanitize tokens)
    env_config = {
        'calibre_library': os.getenv('CALIBRE_LIBRARY', ''),
        'calibredb_path': os.getenv('CALIBREDB_PATH', ''),
        'hardcover_token': sanitize_token(os.getenv('HARDCOVER_TOKEN', '')),
        'prowlarr_url': os.getenv('PROWLARR_URL', '').strip(),
        'prowlarr_api_key': sanitize_token(os.getenv('PROWLARR_API_KEY', '')),
    }

    # Load file config if it exists
    file_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_config = json.load(f)
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}")

    # Merge: start with file config, then overlay non-empty env vars
    config.update(file_config)

    # Environment variables override file config when set (non-empty)
    for key, value in env_config.items():
        if value:  # Only override if env var is actually set
            config[key] = value

    # Ensure required keys exist with defaults
    config.setdefault('calibre_library', os.path.expanduser('~/Calibre Library'))
    config.setdefault('calibredb_path', '')
    config.setdefault('hardcover_token', '')
    config.setdefault('prowlarr_url', '')
    config.setdefault('prowlarr_api_key', '')
    config.setdefault('requested_books', [])

    return config


def save_config():
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"⚠️  Failed to save config: {e}")
        return False


def load_imported_files():
    """Load list of already-imported files from disk (survives restarts).

    Thread-safe via import_state_lock.
    """
    global import_state
    if os.path.exists(IMPORTED_FILES_FILE):
        try:
            with open(IMPORTED_FILES_FILE, 'r') as f:
                data = json.load(f)
                with import_state_lock:
                    import_state['imported_files'] = data.get('files', [])
                print(f"📂 Loaded {len(import_state['imported_files'])} previously imported files")
        except Exception as e:
            print(f"⚠️  Failed to load imported files list: {e}")
            with import_state_lock:
                import_state['imported_files'] = []
    else:
        with import_state_lock:
            import_state['imported_files'] = []


def save_imported_files():
    """Save list of imported files to disk for persistence across restarts.

    Uses atomic write (temp file + rename) to prevent corruption.
    Thread-safe via import_state_lock.
    """
    try:
        with import_state_lock:
            files_to_save = list(import_state.get('imported_files', []))

        # Write to temp file first, then atomically rename
        temp_file = IMPORTED_FILES_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump({'files': files_to_save}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is written to disk

        # Atomic rename (on POSIX systems)
        os.replace(temp_file, IMPORTED_FILES_FILE)
        return True
    except Exception as e:
        print(f"⚠️  Failed to save imported files list: {e}")
        # Clean up temp file if it exists
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass
        return False


def get_calibre_library():
    """Get the current Calibre library path"""
    return config.get('calibre_library', os.path.expanduser('~/Calibre Library'))


def get_db_connection(readonly=False):
    """Get a connection to the Calibre metadata database
    
    Args:
        readonly: If True, open in read-only mode for better concurrency
    """
    library_path = get_calibre_library()
    db_path = os.path.join(library_path, 'metadata.db')

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Calibre database not found at {db_path}")

    # Add timeout for concurrent access (threaded server)
    # Use URI mode to support read-only connections
    if readonly:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30.0)
    else:
        conn = sqlite3.connect(db_path, timeout=30.0)
        # Enable WAL mode for better concurrent read/write performance
        # This only needs to be set once per database, but is safe to call repeatedly
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass  # May fail on read-only filesystems, which is fine
    
    conn.row_factory = sqlite3.Row

    # Some Calibre databases use custom SQLite functions (e.g. title_sort)
    # in indexes or queries. When those functions are missing, *any* query
    # that touches the affected index can raise "no such function: title_sort".
    # We register lightweight fallbacks so the queries (and index usage) work.
    try:
        conn.create_function("title_sort", 1, lambda s: s or "")
    except Exception:
        # Best-effort only – don't break connection creation if this fails
        pass

    return conn


def get_books(limit=50, offset=0, search=None, sort='recent'):
    """Get books from the Calibre database
    
    Args:
        limit: Max books to return
        offset: Pagination offset
        search: Optional search term
        sort: Sort order - 'recent' (default), 'title', 'author'
    """
    try:
        conn = get_db_connection(readonly=True)
        cursor = conn.cursor()

        # Determine sort order - default to recently added
        if sort == 'title':
            order_clause = "ORDER BY b.sort"
        elif sort == 'author':
            order_clause = "ORDER BY authors, b.sort"
        else:  # 'recent' is default
            order_clause = "ORDER BY b.timestamp DESC"

        # Base query
        query = """
            SELECT
                b.id,
                b.title,
                b.sort,
                b.timestamp,
                b.pubdate,
                b.series_index,
                b.path,
                b.has_cover,
                GROUP_CONCAT(a.name, ' & ') as authors,
                GROUP_CONCAT(t.name, ', ') as tags,
                c.text as comments,
                p.name as publisher,
                s.name as series
            FROM books b
            LEFT JOIN books_authors_link bal ON b.id = bal.book
            LEFT JOIN authors a ON bal.author = a.id
            LEFT JOIN books_tags_link btl ON b.id = btl.book
            LEFT JOIN tags t ON btl.tag = t.id
            LEFT JOIN comments c ON b.id = c.book
            LEFT JOIN books_publishers_link bpl ON b.id = bpl.book
            LEFT JOIN publishers p ON bpl.publisher = p.id
            LEFT JOIN books_series_link bsl ON b.id = bsl.book
            LEFT JOIN series s ON bsl.series = s.id
        """

        # Add search if provided
        if search:
            query += " WHERE b.title LIKE ? OR a.name LIKE ?"
            params = (f'%{search}%', f'%{search}%', limit, offset)
        else:
            params = (limit, offset)

        query += f" GROUP BY b.id {order_clause} LIMIT ? OFFSET ?"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Get all book IDs for batch format query
        book_ids = [row['id'] for row in rows]
        
        # Batch query for formats (avoids N+1 queries)
        formats_map = {}
        if book_ids:
            placeholders = ','.join('?' * len(book_ids))
            cursor.execute(f"SELECT book, format FROM data WHERE book IN ({placeholders})", book_ids)
            for fmt_row in cursor.fetchall():
                book_id = fmt_row['book']
                if book_id not in formats_map:
                    formats_map[book_id] = []
                formats_map[book_id].append(fmt_row['format'].upper())

        books = []
        for row in rows:
            formats = formats_map.get(row['id'], [])

            # Parse authors - handle various separators and formats, and deduplicate
            # Calibre stores authors as "LastName, FirstName" or "LastName| FirstName" - convert to "FirstName LastName"
            authors_list = []
            seen_authors = set()  # Use set for O(1) lookup
            
            def normalize_author_name(author_str):
                """Convert 'LastName, FirstName' or 'LastName| FirstName' to 'FirstName LastName'"""
                author_str = author_str.strip()
                if not author_str:
                    return None
                
                # Handle pipe format: "LastName| FirstName" or "LastName|FirstName"
                if '|' in author_str:
                    parts = author_str.split('|', 1)
                    if len(parts) == 2:
                        last_name = parts[0].strip()
                        first_name = parts[1].strip()
                        if first_name and last_name:
                            return f"{first_name} {last_name}"
                
                # Handle comma format: "LastName, FirstName" or "LastName,FirstName"
                if ', ' in author_str:
                    parts = author_str.split(', ', 1)
                    if len(parts) == 2:
                        last_name = parts[0].strip()
                        first_name = parts[1].strip()
                        if first_name and last_name:
                            return f"{first_name} {last_name}"
                elif author_str.count(',') == 1 and not author_str.startswith(','):
                    # Handle "LastName,FirstName" (no space)
                    parts = author_str.split(',', 1)
                    if len(parts) == 2:
                        last_name = parts[0].strip()
                        first_name = parts[1].strip()
                        if first_name and last_name:
                            return f"{first_name} {last_name}"
                
                # If no conversion needed, return as-is
                return author_str
            
            if row['authors']:
                authors_str = str(row['authors']).strip()
                if authors_str:
                    # First, handle pipe separators between authors (rare, but possible)
                    # Replace '|' used as author separator with ' & ', but preserve '|' within names
                    # We'll split by ' & ' first, then normalize each author
                    authors_str = authors_str.replace(', and ', ' & ').replace(' and ', ' & ')
                    
                    # Split by ' & ' for multiple authors
                    # Note: '|' within an author name (like "Smith| John") will be handled by normalize_author_name
                    for author in authors_str.split(' & '):
                        author = author.strip()
                        if not author:
                            continue
                        
                        # Normalize the author name format
                        normalized_author = normalize_author_name(author)
                        if normalized_author:
                            # Deduplicate
                            key = normalized_author.lower()
                            if key not in seen_authors:
                                seen_authors.add(key)
                                authors_list.append(normalized_author)
            
            # Deduplicate tags while preserving order
            tags_list = []
            if row['tags']:
                seen_tags = set()
                for tag in row['tags'].split(','):
                    tag = tag.strip()
                    if tag and tag.lower() not in seen_tags:
                        seen_tags.add(tag.lower())
                        tags_list.append(tag)

            book = {
                'id': row['id'],
                'title': row['title'],
                'authors': authors_list,
                'tags': tags_list,
                'comments': row['comments'],
                'publisher': row['publisher'],
                'series': row['series'],
                'series_index': row['series_index'],
                'timestamp': row['timestamp'],
                'pubdate': row['pubdate'],
                'has_cover': bool(row['has_cover']),
                'formats': formats,
                'path': row['path']
            }
            books.append(book)

        conn.close()
        return books
    except Exception as e:
        print(f"❌ Error loading books: {e}")
        return []


def get_book_cover(book_id):
    """Get the cover image for a book.
    
    Uses the cover cache to avoid database hits on every request.
    This prevents SQLite contention when many covers load simultaneously.
    """
    try:
        # Try to get from cache first (avoids DB contention)
        cached = cover_cache.get(book_id)
        
        if cached is None:
            # Cache miss or expired - try to refresh cache
            cover_cache.load_all()
            cached = cover_cache.get(book_id)
        
        if cached is None:
            # Still no cache - fall back to direct DB query
            conn = get_db_connection(readonly=True)
            cursor = conn.cursor()
            cursor.execute("SELECT path, has_cover FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None
            
            cached = {
                'path': row['path'],
                'has_cover': bool(row['has_cover'])
            }
        
        if not cached.get('has_cover'):
            return None

        library_path = get_calibre_library()
        cover_path = os.path.join(library_path, cached['path'], 'cover.jpg')

        if os.path.exists(cover_path):
            with open(cover_path, 'rb') as f:
                return f.read()

        return None
    except Exception as e:
        print(f"❌ Error loading cover for book {book_id}: {e}")
        return None


def get_reading_list_books(sort='added'):
    """Get books that are on the reading list.
    
    Args:
        sort: Sort order - 'added' (default, by timestamp), 'title', 'author'
    
    Returns:
        List of book dicts with id, title, authors, timestamp, formats, has_cover, etc.
    """
    reading_list_ids = get_reading_list_ids()
    if not reading_list_ids:
        return []
    
    conn = None
    try:
        conn = get_db_connection(readonly=True)
        cursor = conn.cursor()
        
        # Build query to get books by IDs
        placeholders = ','.join('?' * len(reading_list_ids))
        
        # Determine sort order
        if sort == 'title':
            order_clause = "ORDER BY b.sort"
        elif sort == 'author':
            order_clause = "ORDER BY authors, b.sort"
        else:  # 'added' is default - sort by when added to library
            order_clause = "ORDER BY b.timestamp DESC"
        
        query = f"""
            SELECT
                b.id,
                b.title,
                b.sort,
                b.timestamp,
                b.pubdate,
                b.path,
                b.has_cover,
                GROUP_CONCAT(a.name, ' & ') as authors
            FROM books b
            LEFT JOIN books_authors_link bal ON b.id = bal.book
            LEFT JOIN authors a ON bal.author = a.id
            WHERE b.id IN ({placeholders})
            GROUP BY b.id {order_clause}
        """
        
        cursor.execute(query, reading_list_ids)
        rows = cursor.fetchall()
        
        # Batch query for formats
        book_ids = [row['id'] for row in rows]
        formats_map = {}
        if book_ids:
            fmt_placeholders = ','.join('?' * len(book_ids))
            cursor.execute(f"SELECT book, format, uncompressed_size FROM data WHERE book IN ({fmt_placeholders})", book_ids)
            for fmt_row in cursor.fetchall():
                book_id = fmt_row['book']
                if book_id not in formats_map:
                    formats_map[book_id] = []
                formats_map[book_id].append({
                    'format': fmt_row['format'].upper(),
                    'size': fmt_row['uncompressed_size'] or 0
                })
        
        books = []
        for row in rows:
            formats = formats_map.get(row['id'], [])
            
            # Parse authors - handle "LastName, FirstName" format
            authors_list = []
            seen_authors = set()
            
            def normalize_author(author_str):
                author_str = author_str.strip()
                if ', ' in author_str:
                    parts = author_str.split(', ', 1)
                    if len(parts) == 2:
                        return f"{parts[1]} {parts[0]}"
                elif '|' in author_str:
                    parts = author_str.split('|', 1)
                    if len(parts) == 2:
                        return f"{parts[1].strip()} {parts[0].strip()}"
                return author_str
            
            if row['authors']:
                for author in row['authors'].split(' & '):
                    normalized = normalize_author(author)
                    key = normalized.lower()
                    if key not in seen_authors:
                        seen_authors.add(key)
                        authors_list.append(normalized)
            
            book = {
                'id': row['id'],
                'title': row['title'],
                'authors': authors_list if authors_list else ['Unknown Author'],
                'timestamp': row['timestamp'],
                'pubdate': row['pubdate'],
                'has_cover': bool(row['has_cover']),
                'formats': formats,
                'path': row['path']
            }
            books.append(book)
        
        return books
    except Exception as e:
        print(f"❌ Error loading reading list books: {e}")
        return []
    finally:
        if conn:
            conn.close()


def render_kobo_page(books, page=1, sort='added', books_per_page=5):
    """Render the Kobo e-ink HTML page server-side.
    
    This page works without JavaScript for the Kobo browser.
    """
    total_books = len(books)
    total_pages = max(1, (total_books + books_per_page - 1) // books_per_page)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * books_per_page
    end_idx = start_idx + books_per_page
    page_books = books[start_idx:end_idx]
    
    def escape_html(text):
        if not text:
            return ''
        return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))
    
    def format_size(size_bytes):
        if not size_bytes:
            return ''
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"
    
    def format_authors(authors_list):
        if not authors_list:
            return 'Unknown Author'
        return ', '.join(authors_list)
    
    # Build book list HTML
    book_items_html = ''
    for book in page_books:
        authors_str = escape_html(format_authors(book.get('authors', [])))
        title_str = escape_html(book.get('title', 'Unknown Title'))
        
        # Find EPUB format preferentially, otherwise first format
        formats = book.get('formats', [])
        preferred_format = None
        format_info = ''
        
        for fmt in formats:
            if fmt['format'] == 'EPUB':
                preferred_format = fmt
                break
        if not preferred_format and formats:
            preferred_format = formats[0]
        
        if preferred_format:
            size_str = format_size(preferred_format['size'])
            format_info = f"KOBO {preferred_format['format']}"
            if size_str:
                format_info += f" · {size_str}"
        
        download_url = f"/api/download/{book['id']}/{preferred_format['format']}" if preferred_format else '#'
        
        book_items_html += f'''
    <li class="book-item">
      <img src="/api/cover/{book['id']}" alt="" class="book-cover">
      <div class="book-info">
        <h2 class="book-title">{title_str}</h2>
        <p class="book-author">{authors_str}</p>
      </div>
      <div class="book-meta">
        <div class="file-info">{escape_html(format_info)}</div>
        <a href="{download_url}" class="download-btn">Download</a>
      </div>
    </li>'''
    
    # Empty state if no books
    if not page_books:
        book_items_html = '''
    <li class="empty-state">
      <p>No books in your reading list yet.</p>
      <p>Add books from the main app to see them here.</p>
    </li>'''
    
    # Sort dropdown options
    sort_options = [
        ('added', 'Date Added'),
        ('title', 'Title'),
        ('author', 'Author'),
    ]
    sort_options_html = ''
    for value, label in sort_options:
        selected = ' selected' if sort == value else ''
        sort_options_html += f'<option value="{value}"{selected}>{label}</option>'
    
    # Previous/Next buttons
    prev_disabled = ' disabled' if page <= 1 else ''
    next_disabled = ' disabled' if page >= total_pages else ''
    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Folio - Reading List</title>
  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      background: #fff;
      color: #000;
    }}
    
    .header {{
      background: #f0f0f0;
      border-bottom: 2px solid #000;
      padding: 12px 16px;
      display: table;
      width: 100%;
    }}
    
    .header-logo {{
      display: table-cell;
      vertical-align: middle;
      width: 40px;
    }}
    
    .header-logo svg {{
      width: 32px;
      height: 32px;
    }}
    
    .header-title {{
      display: table-cell;
      vertical-align: middle;
      padding-left: 10px;
    }}
    
    .header h1 {{
      font-size: 26px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.5px;
    }}
    
    .header-sort {{
      display: table-cell;
      vertical-align: middle;
      text-align: right;
    }}
    
    .sort-form {{
      display: inline;
    }}
    
    .sort-select {{
      background: #fff;
      border: 2px solid #000;
      padding: 12px 16px;
      font-size: 18px;
      font-weight: 500;
      min-width: 140px;
    }}
    
    .content {{
      position: absolute;
      top: 70px;
      bottom: 80px;
      left: 0;
      right: 0;
      overflow: hidden;
    }}
    
    .book-list {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    
    .book-item {{
      display: table;
      width: 100%;
      padding: 14px 16px;
      border-bottom: 1px solid #ccc;
    }}

    .book-cover {{
      display: table-cell;
      vertical-align: top;
      width: 70px;
      height: 100px;
      background: #ddd;
      border: 1px solid #999;
    }}

    .book-cover img {{
      width: 70px;
      height: 100px;
      object-fit: cover;
    }}

    .book-info {{
      display: table-cell;
      vertical-align: top;
      padding: 0 16px;
    }}

    .book-title {{
      font-size: 22px;
      font-weight: 600;
      margin: 0 0 6px 0;
      line-height: 1.25;
    }}

    .book-author {{
      font-size: 18px;
      color: #333;
      margin: 0;
    }}

    .book-meta {{
      display: table-cell;
      vertical-align: middle;
      text-align: right;
      white-space: nowrap;
      width: 130px;
    }}

    .file-info {{
      font-size: 14px;
      color: #555;
      margin-bottom: 10px;
    }}
    
    .download-btn {{
      display: inline-block;
      background: #000;
      color: #fff;
      border: none;
      padding: 14px 20px;
      font-size: 18px;
      font-weight: 600;
      text-decoration: none;
      text-align: center;
    }}
    
    .empty-state {{
      padding: 50px 24px;
      text-align: center;
      color: #555;
    }}

    .empty-state p {{
      margin: 12px 0;
      font-size: 20px;
    }}
    
    .pagination {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: #f0f0f0;
      border-top: 2px solid #000;
      padding: 12px 16px;
      display: table;
      width: 100%;
    }}
    
    .pagination-left {{
      display: table-cell;
      text-align: left;
      width: 33%;
    }}
    
    .pagination-center {{
      display: table-cell;
      text-align: center;
      width: 34%;
      font-size: 18px;
      color: #333;
      vertical-align: middle;
    }}
    
    .pagination-right {{
      display: table-cell;
      text-align: right;
      width: 33%;
    }}
    
    .nav-btn {{
      display: inline-block;
      background: #000;
      color: #fff;
      border: 2px solid #000;
      padding: 16px 28px;
      font-size: 20px;
      font-weight: 600;
      text-decoration: none;
      text-align: center;
      min-width: 120px;
    }}
    
    .nav-btn[disabled],
    .nav-btn.disabled {{
      background: #ccc;
      color: #888;
      border-color: #999;
      pointer-events: none;
    }}
    
    .page-info {{
      font-weight: 500;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-logo">
      <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" rx="20" fill="#000"/>
        <path d="M25 20h50v60H25z" fill="#fff"/>
        <path d="M30 25h40v50H30z" fill="#000"/>
        <path d="M35 35h25v3H35zM35 42h30v2H35zM35 48h28v2H35zM35 54h30v2H35zM35 60h20v2H35z" fill="#fff"/>
      </svg>
    </div>
    <div class="header-title">
      <h1>Reading List</h1>
    </div>
    <div class="header-sort">
      <form method="GET" action="/kobo" class="sort-form">
        <input type="hidden" name="page" value="1">
        <select name="sort" class="sort-select" onchange="this.form.submit()">
          {sort_options_html}
        </select>
        <noscript><button type="submit" class="nav-btn" style="margin-left:8px;padding:10px 16px;">Go</button></noscript>
      </form>
    </div>
  </div>
  
  <div class="content">
    <ul class="book-list">
{book_items_html}
    </ul>
  </div>
  
  <div class="pagination">
    <div class="pagination-left">
      <a href="/kobo?page={prev_page}&amp;sort={sort}" class="nav-btn{prev_disabled}">← Prev</a>
    </div>
    <div class="pagination-center">
      <span class="page-info">{page} / {total_pages}</span>
    </div>
    <div class="pagination-right">
      <a href="/kobo?page={next_page}&amp;sort={sort}" class="nav-btn{next_disabled}">Next →</a>
    </div>
  </div>
</body>
</html>'''
    
    return html


def find_calibredb():
    """Find calibredb executable across platforms"""
    # Check if path is configured
    configured_path = config.get('calibredb_path', '').strip()
    if configured_path and os.path.exists(configured_path) and os.access(configured_path, os.X_OK):
        return configured_path
    
    # Try finding in PATH first (most reliable cross-platform method)
    calibredb_in_path = shutil.which('calibredb')
    if calibredb_in_path:
        return calibredb_in_path
    
    # Try common locations by platform
    import platform
    system = platform.system()
    
    common_paths = []
    
    if system == 'Darwin':  # macOS
        common_paths = [
            '/Applications/calibre.app/Contents/MacOS/calibredb',
            '/Applications/calibre.app/Contents/console.app/Contents/MacOS/calibredb',
            os.path.expanduser('~/Applications/calibre.app/Contents/MacOS/calibredb'),
        ]
    elif system == 'Linux':
        common_paths = [
            '/usr/bin/calibredb',
            '/usr/local/bin/calibredb',
            '/opt/calibre/bin/calibredb',
            os.path.expanduser('~/.local/bin/calibredb'),
        ]
    elif system == 'Windows':
        common_paths = [
            'C:\\Program Files\\Calibre2\\calibredb.exe',
            'C:\\Program Files (x86)\\Calibre2\\calibredb.exe',
            os.path.expanduser('~\\AppData\\Local\\Programs\\Calibre\\calibredb.exe'),
        ]
        # Also try without .exe extension (for WSL/cygwin)
        common_paths.extend([
            'C:\\Program Files\\Calibre2\\calibredb',
            'C:\\Program Files (x86)\\Calibre2\\calibredb',
        ])
    
    # Try all common paths
    for path in common_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    
    return None


def find_kepubify():
    """Find kepubify executable across platforms"""
    # Try finding in PATH first
    kepubify_in_path = shutil.which('kepubify')
    if kepubify_in_path:
        return kepubify_in_path

    # Try common locations by platform
    import platform
    system = platform.system()

    common_paths = []

    if system == 'Darwin':  # macOS
        common_paths = [
            '/usr/local/bin/kepubify',
            os.path.expanduser('~/bin/kepubify'),
            os.path.expanduser('~/.local/bin/kepubify'),
        ]
    elif system == 'Linux':
        common_paths = [
            '/usr/bin/kepubify',
            '/usr/local/bin/kepubify',
            os.path.expanduser('~/.local/bin/kepubify'),
            os.path.expanduser('~/bin/kepubify'),
        ]
    elif system == 'Windows':
        common_paths = [
            os.path.expanduser('~\\kepubify.exe'),
            'C:\\Program Files\\kepubify\\kepubify.exe',
        ]

    for path in common_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path

    return None


def convert_book_to_kepub(book_id):
    """
    Convert an EPUB book to KEPUB format using kepubify and add it to the library.
    Returns True on success, False on failure.
    """
    kepubify_path = find_kepubify()
    if not kepubify_path:
        print("⚠️ kepubify not found - skipping KEPUB conversion")
        return False

    try:
        # Get book info from database
        conn = get_db_connection(readonly=True)
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(f"❌ Book {book_id} not found for KEPUB conversion")
            return False

        book_path = row['path']
        library_path = get_calibre_library()
        book_dir = os.path.join(library_path, book_path)

        # Find the EPUB file in the book directory
        epub_file = None
        for filename in os.listdir(book_dir):
            if filename.lower().endswith('.epub') and not filename.lower().endswith('.kepub.epub'):
                epub_file = os.path.join(book_dir, filename)
                break

        if not epub_file:
            print(f"⚠️ No EPUB found for book {book_id} - skipping KEPUB conversion")
            return False

        # Create output filename
        kepub_file = epub_file.replace('.epub', '.kepub.epub')

        # Run kepubify
        result = subprocess.run(
            [kepubify_path, '-o', kepub_file, epub_file],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and os.path.exists(kepub_file):
            # Add the KEPUB format to the book in Calibre
            add_result = run_calibredb(['add_format', str(book_id), kepub_file], suppress_errors=True)
            if add_result['success']:
                print(f"✅ Converted and added KEPUB for book {book_id}")
                # Remove the temporary kepub file since it's now in the library
                try:
                    os.remove(kepub_file)
                except:
                    pass
                return True
            else:
                print(f"❌ Failed to add KEPUB format: {add_result.get('error', 'Unknown error')}")
                return False
        else:
            print(f"❌ kepubify failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ KEPUB conversion error: {e}")
        return False


def convert_file_to_kepub(filepath):
    """
    Convert an EPUB file from the import folder to KEPUB format using kepubify.
    Returns the path to the KEPUB file on success, None on failure.
    The KEPUB file is created in a temp directory to avoid polluting the import folder.
    """
    kepubify_path = find_kepubify()
    if not kepubify_path:
        print("⚠️ kepubify not found - cannot convert to KEPUB")
        return None

    if not filepath.lower().endswith('.epub'):
        print(f"⚠️ File is not an EPUB, cannot convert to KEPUB: {os.path.basename(filepath)}")
        return None

    if filepath.lower().endswith('.kepub.epub'):
        # Already a KEPUB
        return filepath

    try:
        # Create output filename in a temp directory
        temp_dir = tempfile.mkdtemp(prefix='kepub_')
        base_name = os.path.basename(filepath)
        kepub_name = base_name.replace('.epub', '.kepub.epub').replace('.EPUB', '.kepub.epub')
        kepub_file = os.path.join(temp_dir, kepub_name)

        # Run kepubify
        result = subprocess.run(
            [kepubify_path, '-o', kepub_file, filepath],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and os.path.exists(kepub_file):
            print(f"✅ Converted to KEPUB: {os.path.basename(filepath)}")
            return kepub_file
        else:
            print(f"❌ kepubify failed for {os.path.basename(filepath)}: {result.stderr}")
            # Clean up temp dir on failure
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
            return None

    except Exception as e:
        print(f"❌ KEPUB conversion error for {os.path.basename(filepath)}: {e}")
        return None


def group_import_files_by_book(files):
    """
    Group import files by their base name (without extension) to detect duplicates.
    This handles cases where both .mobi and .epub exist for the same book.
    Returns a dict: {base_name: [list of filepaths]}
    """
    groups = {}
    for filepath in files:
        filename = os.path.basename(filepath)
        # Get base name without extension
        base_name, ext = os.path.splitext(filename)
        # Handle double extensions like .kepub.epub
        if base_name.lower().endswith('.kepub'):
            base_name = base_name[:-6]

        # Normalize the base name for grouping (lowercase, strip whitespace)
        group_key = base_name.lower().strip()

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(filepath)

    return groups


def select_best_format_for_import(filepaths):
    """
    Given a list of file paths for the same book (different formats),
    select the best one for import. Prefers EPUB (can be converted to KEPUB),
    then other formats in order of preference.
    Returns (best_file, other_files) tuple.
    """
    # Priority order: EPUB (for KEPUB conversion) > MOBI > AZW3 > others
    priority = {
        '.epub': 1,
        '.kepub.epub': 0,  # Already KEPUB is best
        '.mobi': 2,
        '.azw3': 3,
        '.azw': 4,
        '.pdf': 5,
    }

    def get_priority(filepath):
        lower = filepath.lower()
        if lower.endswith('.kepub.epub'):
            return priority.get('.kepub.epub', 99)
        for ext, prio in priority.items():
            if lower.endswith(ext):
                return prio
        return 99

    sorted_files = sorted(filepaths, key=get_priority)
    return sorted_files[0], sorted_files[1:] if len(sorted_files) > 1 else []


def fetch_and_apply_itunes_metadata(book_id):
    """
    Fetch metadata from iTunes based on the book's title/author and apply it.
    Returns True on success, False on failure.
    """
    try:
        # Get book info from database
        conn = get_db_connection(readonly=True)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.title, GROUP_CONCAT(a.name, ' & ') as authors
            FROM books b
            LEFT JOIN books_authors_link bal ON b.id = bal.book
            LEFT JOIN authors a ON bal.author = a.id
            WHERE b.id = ?
            GROUP BY b.id
        """, (book_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(f"❌ Book {book_id} not found for metadata fetch")
            return False

        title = row['title'] or ''
        authors = row['authors'] or ''

        # Build search query
        search_query = title
        if authors:
            # Take just the first author for more accurate results
            first_author = authors.split(' & ')[0].strip()
            search_query = f"{title} {first_author}"

        print(f"🔍 Searching iTunes for: {search_query}")

        # Search iTunes
        result = search_itunes(search_query, limit=5)
        if 'error' in result or not result.get('books'):
            print(f"⚠️ No iTunes results for book {book_id}")
            return False

        # Find best match (simple title matching)
        best_match = None
        title_lower = title.lower()
        for book in result['books']:
            if book.get('title', '').lower() == title_lower:
                best_match = book
                break

        # If no exact match, use first result
        if not best_match:
            best_match = result['books'][0]

        # Build metadata update args
        metadata_args = ['set_metadata', str(book_id)]

        # Apply description/comments if available
        if best_match.get('description'):
            # Strip HTML tags for Calibre comments
            description = re.sub(r'<[^>]+>', '', best_match['description'])
            metadata_args.extend(['--field', f'comments:{description}'])

        # Apply cover if available
        if best_match.get('image'):
            try:
                # Download cover image
                cover_url = best_match['image']
                req = urllib.request.Request(cover_url)
                with urllib.request.urlopen(req, timeout=10) as response:
                    cover_data = response.read()

                # Save to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp.write(cover_data)
                    cover_path = tmp.name

                # Apply cover using calibredb
                cover_result = run_calibredb(['set_metadata', str(book_id), '--field', f'cover:{cover_path}'], suppress_errors=True)

                # Clean up temp file
                try:
                    os.remove(cover_path)
                except:
                    pass

                if cover_result['success']:
                    print(f"✅ Applied cover from iTunes for book {book_id}")
            except Exception as e:
                print(f"⚠️ Failed to apply cover: {e}")

        # Apply other metadata if we have any fields
        if len(metadata_args) > 2:
            result = run_calibredb(metadata_args, suppress_errors=True)
            if result['success']:
                print(f"✅ Applied iTunes metadata for book {book_id}")
                return True
            else:
                print(f"⚠️ Failed to apply metadata: {result.get('error', 'Unknown')}")
                return False

        return True

    except Exception as e:
        print(f"❌ iTunes metadata error: {e}")
        return False


def get_book_id_from_calibredb_output(output):
    """
    Extract the book ID from calibredb add output.
    Output format typically: "Added book ids: 123" or similar
    """
    if not output:
        return None

    # Look for patterns like "Added book ids: 123" or "id: 123"
    match = re.search(r'(?:Added book ids?:|id:)\s*(\d+)', output, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Also try to find just a number on a line by itself
    for line in output.strip().split('\n'):
        line = line.strip()
        if line.isdigit():
            return int(line)

    return None


def run_calibredb(args, suppress_errors=False):
    """Execute calibredb command with the library path

    Args:
        args: Command arguments for calibredb
        suppress_errors: If True, don't print error messages (for non-critical operations)
    """
    library_path = get_calibre_library()
    calibredb_path = find_calibredb()
    
    if not calibredb_path:
        error_msg = 'calibredb not found. Please install Calibre or set CALIBREDB_PATH environment variable.'
        if not suppress_errors:
            print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    
    cmd = [calibredb_path] + args + ['--library-path', library_path]
    if not suppress_errors:
        print(f"🔧 Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30  # Add timeout to prevent hanging
        )
        return {'success': True, 'output': result.stdout}
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        if not suppress_errors:
            print(f"❌ calibredb error: {error_msg}")
        return {'success': False, 'error': error_msg}
    except subprocess.TimeoutExpired:
        error_msg = 'calibredb command timed out'
        if not suppress_errors:
            print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    except FileNotFoundError:
        error_msg = f'calibredb not found at {calibredb_path}. Please install Calibre.'
        if not suppress_errors:
            print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = str(e)
        if not suppress_errors:
            print(f"❌ calibredb unexpected error: {error_msg}")
        return {'success': False, 'error': error_msg}


# Supported ebook formats for import
EBOOK_EXTENSIONS = {'.epub', '.pdf', '.mobi', '.azw', '.azw3', '.fb2', '.lit', '.prc', '.txt', '.rtf', '.djvu', '.cbz', '.cbr'}

# Minimum file age in seconds before processing (to avoid partially downloaded files)
FILE_MATURITY_SECONDS = 5


def is_file_mature(filepath):
    """Check if file has not been modified recently (not still downloading)."""
    try:
        mtime = os.path.getmtime(filepath)
        age = time.time() - mtime
        return age >= FILE_MATURITY_SECONDS
    except OSError:
        return False  # File doesn't exist or can't be accessed


def scan_import_folder():
    """Scan the import folder for ebook files.

    Skips files that are still being written (modified within last 5 seconds).
    """
    import_folder = config.get('import_folder', '')
    if not import_folder or not os.path.isdir(import_folder):
        return []

    recursive = config.get('import_recursive', True)
    files = []
    skipped_immature = 0

    print(f"🔍 Scanning import folder: {import_folder} (recursive: {recursive})")

    if recursive:
        # Walk through all subdirectories
        for root, dirs, filenames in os.walk(import_folder):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in EBOOK_EXTENSIONS:
                    filepath = os.path.join(root, filename)
                    # Skip files still being written
                    if not is_file_mature(filepath):
                        skipped_immature += 1
                        rel_path = os.path.relpath(filepath, import_folder)
                        print(f"   ⏳ Skipping (still downloading): {rel_path}")
                        continue
                    files.append(filepath)
                    # Show relative path for better readability
                    rel_path = os.path.relpath(filepath, import_folder)
                    print(f"   📖 Found: {rel_path}")
    else:
        # Only scan top-level directory
        for filename in os.listdir(import_folder):
            filepath = os.path.join(import_folder, filename)
            if os.path.isfile(filepath):
                ext = os.path.splitext(filename)[1].lower()
                if ext in EBOOK_EXTENSIONS:
                    # Skip files still being written
                    if not is_file_mature(filepath):
                        skipped_immature += 1
                        print(f"   ⏳ Skipping (still downloading): {filename}")
                        continue
                    files.append(filepath)
                    print(f"   📖 Found: {filename}")

    if skipped_immature > 0:
        print(f"   ℹ️  Skipped {skipped_immature} file(s) still being written")
    print(f"🔍 Scan complete: found {len(files)} ebook file(s)")
    return files


def import_books_from_folder():
    """
    Import books from the import folder into Calibre.

    Flow:
    1. Scan import folder for ebook files
    2. Group files by base name to detect duplicates (e.g., same book as .mobi and .epub)
    3. For each book group, select the best format (prefer EPUB for KEPUB conversion)
    4. Convert EPUB to KEPUB using kepubify
    5. Import the KEPUB (or original format if not EPUB) to Calibre
    6. Delete the original file(s) from the import folder
    """
    global import_state

    import_folder = config.get('import_folder', '')
    if not import_folder:
        return {'success': False, 'error': 'Import folder not configured'}

    if not os.path.isdir(import_folder):
        return {'success': False, 'error': f'Import folder does not exist: {import_folder}'}

    # Find all ebook files
    files = scan_import_folder()

    # Filter out already imported files (thread-safe)
    with import_state_lock:
        already_imported = set(import_state.get('imported_files', []))
    new_files = [f for f in files if f not in already_imported]

    if not new_files:
        with import_state_lock:
            import_state['last_scan'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if len(already_imported) > 0:
            print(f"   ℹ️  All {len(files)} file(s) already imported previously")
        return {'success': True, 'imported': 0, 'message': 'No new files to import'}

    print(f"\n📥 Found {len(new_files)} new file(s) to process:")
    for f in new_files:
        print(f"   📄 {os.path.basename(f)}")

    # Group files by book name to detect duplicates
    book_groups = group_import_files_by_book(new_files)
    print(f"\n📊 Grouped into {len(book_groups)} unique book(s) (handling duplicate formats)")

    imported_count = 0
    errors = []
    skipped_duplicates = 0

    for base_name, filepaths in book_groups.items():
        # Select the best format for import (prefer EPUB for KEPUB conversion)
        best_file, other_files = select_best_format_for_import(filepaths)

        if other_files:
            skipped_duplicates += len(other_files)
            print(f"📚 Found {len(filepaths)} formats for '{base_name}', using: {os.path.basename(best_file)}")
            for other in other_files:
                print(f"   ⏭️  Skipping duplicate format: {os.path.basename(other)}")

        kepub_file = None
        temp_dir_to_cleanup = None

        try:
            # Convert EPUB to KEPUB before importing
            if best_file.lower().endswith('.epub') and not best_file.lower().endswith('.kepub.epub'):
                print(f"\n🔄 Converting to KEPUB: {os.path.basename(best_file)}")
                kepub_file = convert_file_to_kepub(best_file)
                if kepub_file:
                    # Remember the temp dir for cleanup
                    temp_dir_to_cleanup = os.path.dirname(kepub_file)
                    file_to_import = kepub_file
                    print(f"   ✅ KEPUB conversion successful")
                else:
                    # Conversion failed, fall back to importing original EPUB
                    print(f"   ⚠️ KEPUB conversion failed, importing original EPUB: {os.path.basename(best_file)}")
                    file_to_import = best_file
            else:
                file_to_import = best_file

            # Build calibredb add command
            # --duplicates flag allows adding even if similar book exists
            print(f"\n📚 Importing to Calibre library: {os.path.basename(file_to_import)}")
            args = ['add', file_to_import, '--duplicates']

            result = run_calibredb(args)

            if result['success']:
                imported_count += 1
                # Mark all files in this group as imported (thread-safe)
                with import_state_lock:
                    for filepath in filepaths:
                        import_state['imported_files'].append(filepath)
                save_imported_files()  # Persist to disk immediately

                print(f"   ✅ Successfully imported to Calibre: {os.path.basename(file_to_import)}")

                # Get the book ID from the calibredb output for post-processing
                book_id = get_book_id_from_calibredb_output(result.get('output', ''))

                if book_id:
                    print(f"   📋 Book ID: {book_id}")
                    # Fetch and apply iTunes metadata
                    try:
                        print(f"   🔍 Fetching iTunes metadata for book {book_id}...")
                        fetch_and_apply_itunes_metadata(book_id)
                    except Exception as e:
                        print(f"   ⚠️ iTunes metadata fetch failed: {e}")

                # Handle file cleanup
                # IMPORTANT: Keep EPUB files for seeding (torrents), only delete non-EPUB formats
                delete_after = config.get('import_delete', False)
                for filepath in filepaths:
                    is_epub = filepath.lower().endswith('.epub')
                    if is_epub:
                        # Always keep EPUBs for seeding
                        print(f"📁 Kept for seeding: {os.path.basename(filepath)}")
                    elif delete_after:
                        # Delete non-EPUB formats if configured
                        try:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                                print(f"🗑️  Deleted from import folder: {os.path.basename(filepath)}")
                        except Exception as e:
                            errors.append(f"Failed to delete {filepath}: {e}")
                            print(f"⚠️ Failed to delete {os.path.basename(filepath)}: {e}")

            else:
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"{os.path.basename(best_file)}: {error_msg}")
                print(f"❌ Failed to import {os.path.basename(best_file)}: {error_msg}")

        except Exception as e:
            errors.append(f"{os.path.basename(best_file)}: {str(e)}")
            print(f"❌ Error importing {os.path.basename(best_file)}: {e}")

        finally:
            # Clean up temp KEPUB file and directory
            if temp_dir_to_cleanup and os.path.exists(temp_dir_to_cleanup):
                try:
                    shutil.rmtree(temp_dir_to_cleanup)
                except Exception as e:
                    print(f"⚠️ Failed to cleanup temp dir: {e}")

    # Update state (thread-safe)
    with import_state_lock:
        import_state['last_scan'] = time.strftime('%Y-%m-%d %H:%M:%S')
        import_state['last_imported_count'] = imported_count
        import_state['total_imported'] += imported_count
        if imported_count > 0:
            import_state['last_import'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if errors:
            import_state['errors'] = errors[-10:]  # Keep last 10 errors
    if imported_count > 0:
        # Invalidate cover cache so new books are picked up
        cover_cache.invalidate()

    message = f'Imported {imported_count} book(s)'
    if skipped_duplicates > 0:
        message += f' (skipped {skipped_duplicates} duplicate format(s))'

    return {
        'success': True,
        'imported': imported_count,
        'skipped_duplicates': skipped_duplicates,
        'errors': errors if errors else None,
        'message': message
    }


def import_watcher_thread():
    """Background thread that periodically scans the import folder.

    Thread-safe via import_state_lock for state access.
    """
    global import_state

    with import_state_lock:
        import_state['running'] = True
    interval = config.get('import_interval', 60)

    print(f"📂 Import watcher started (interval: {interval}s, recursive: {config.get('import_recursive', True)}, delete: {config.get('import_delete', False)})")

    while True:
        # Check running state with lock
        with import_state_lock:
            if not import_state['running']:
                break

        try:
            print(f"\n⏰ Starting scheduled import scan at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            result = import_books_from_folder()
            if result.get('imported', 0) > 0:
                print(f"📚 Import scan complete: {result.get('message', '')}")
            else:
                print(f"📚 Import scan complete: {result.get('message', 'No new books found')}")
        except Exception as e:
            print(f"❌ Import watcher error: {e}")
            import traceback
            traceback.print_exc()
            with import_state_lock:
                import_state['errors'].append(str(e))
                # Limit error list to 10 entries
                if len(import_state['errors']) > 10:
                    import_state['errors'] = import_state['errors'][-10:]

        # Sleep in small increments so we can stop quickly
        for _ in range(interval):
            with import_state_lock:
                if not import_state['running']:
                    break
            time.sleep(1)

    print("📂 Import watcher stopped")


def start_import_watcher():
    """Start the import watcher background thread if configured.

    Prevents duplicate watchers from starting.
    """
    global _import_watcher_thread

    import_folder = config.get('import_folder', '')

    if not import_folder:
        print("📂 Import folder not configured - watcher disabled")
        return False

    if not os.path.isdir(import_folder):
        print(f"⚠️  Import folder does not exist: {import_folder}")
        return False

    # Prevent duplicate watcher threads
    if _import_watcher_thread is not None and _import_watcher_thread.is_alive():
        print("📂 Import watcher already running - skipping duplicate start")
        return True

    # Start background thread
    _import_watcher_thread = threading.Thread(target=import_watcher_thread, daemon=True)
    _import_watcher_thread.start()
    return True


def stop_import_watcher():
    """Stop the import watcher background thread."""
    global import_state
    with import_state_lock:
        import_state['running'] = False


def get_reading_list_column_id():
    """
    Get the ID of the reading_list custom column from the database.
    Returns the column ID if it exists, None otherwise.
    """
    try:
        library_path = get_calibre_library()
        db_path = os.path.join(library_path, 'metadata.db')

        if not os.path.exists(db_path):
            return None

        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM custom_columns WHERE label = 'reading_list'")
        row = cursor.fetchone()
        conn.close()

        return row[0] if row else None
    except Exception:
        return None


def ensure_reading_list_column():
    """
    Ensure the reading_list custom column exists in Calibre.
    Creates it if it doesn't exist.
    Returns the column ID if column exists or was created successfully, None otherwise.

    This is a non-critical feature - failures are handled gracefully.
    """
    # First, check if column already exists
    column_id = get_reading_list_column_id()
    if column_id is not None:
        return column_id

    # Column doesn't exist, try to create it using calibredb
    library_path = get_calibre_library()
    calibredb_path = find_calibredb()

    if not calibredb_path:
        # No calibredb available - reading list feature won't work
        return None

    # Try positional arguments (most compatible with different calibre versions)
    cmd = [calibredb_path, 'add_custom_column', 'reading_list', 'Reading List', 'bool', '--library-path', library_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        # Check if successful or if column already exists
        if result.returncode == 0:
            # Get the new column ID
            return get_reading_list_column_id()

        # Check stderr for "already exists" type errors - these are fine
        error_output = (result.stderr + result.stdout).lower()
        if ('already exists' in error_output or
            'duplicate' in error_output or
            'unique constraint' in error_output or
            'constrainterror' in error_output):
            return get_reading_list_column_id()

        # Some other error - reading list won't work but app continues
        return None

    except Exception as e:
        error_str = str(e).lower()
        # If error indicates column already exists, that's fine
        if 'unique constraint' in error_str or 'already exists' in error_str:
            return get_reading_list_column_id()
        return None


def get_reading_list_ids():
    """
    Get IDs of books on the reading list using direct database query.

    This is a non-critical feature - returns empty list on any error.
    """
    try:
        column_id = ensure_reading_list_column()
        if column_id is None:
            return []

        library_path = get_calibre_library()
        db_path = os.path.join(library_path, 'metadata.db')

        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10.0)
        cursor = conn.cursor()

        # Query the custom column table for books with value = 1 (true)
        table_name = f'custom_column_{column_id}'
        cursor.execute(f"SELECT book FROM {table_name} WHERE value = 1")
        rows = cursor.fetchall()
        conn.close()

        return [row[0] for row in rows]
    except Exception as e:
        print(f"⚠️ Reading list unavailable: {e}", flush=True)
        return []


def add_to_reading_list(book_id):
    """
    Add a book to the reading list using direct database access.
    Returns True on success, False on failure.
    """
    try:
        column_id = ensure_reading_list_column()
        if column_id is None:
            print("❌ Could not create reading list column")
            return False

        library_path = get_calibre_library()
        db_path = os.path.join(library_path, 'metadata.db')

        if not os.path.exists(db_path):
            return False

        conn = sqlite3.connect(db_path, timeout=10.0)
        cursor = conn.cursor()

        table_name = f'custom_column_{column_id}'

        # Check if entry already exists
        cursor.execute(f"SELECT id FROM {table_name} WHERE book = ?", (book_id,))
        existing = cursor.fetchone()

        if existing:
            # Update existing entry
            cursor.execute(f"UPDATE {table_name} SET value = 1 WHERE book = ?", (book_id,))
        else:
            # Insert new entry
            cursor.execute(f"INSERT INTO {table_name} (book, value) VALUES (?, 1)", (book_id,))

        conn.commit()
        conn.close()

        print(f"✅ Added book {book_id} to reading list")
        return True
    except Exception as e:
        print(f"❌ Failed to add book {book_id} to reading list: {e}")
        return False


def remove_from_reading_list(book_id):
    """
    Remove a book from the reading list using direct database access.
    Returns True on success, False on failure.
    """
    try:
        column_id = get_reading_list_column_id()
        if column_id is None:
            # Column doesn't exist, nothing to remove
            return True

        library_path = get_calibre_library()
        db_path = os.path.join(library_path, 'metadata.db')

        if not os.path.exists(db_path):
            return False

        conn = sqlite3.connect(db_path, timeout=10.0)
        cursor = conn.cursor()

        table_name = f'custom_column_{column_id}'

        # Delete the entry (or set value to 0)
        cursor.execute(f"DELETE FROM {table_name} WHERE book = ?", (book_id,))

        conn.commit()
        conn.close()

        print(f"✅ Removed book {book_id} from reading list")
        return True
    except Exception as e:
        print(f"❌ Failed to remove book {book_id} from reading list: {e}")
        return False


def mark_request_actioned(book_title):
    """
    Mark a book request as actioned (sent to qBittorrent).
    Sets the actioned_at timestamp for the matching request.
    Returns True if a request was marked, False otherwise.
    """
    try:
        requested_books = config.get('requested_books', [])
        title_lower = book_title.lower().strip()

        for book in requested_books:
            book_title_lower = book.get('title', '').lower().strip()
            if book_title_lower == title_lower or title_lower in book_title_lower or book_title_lower in title_lower:
                book['actioned_at'] = int(time.time())
                config['requested_books'] = requested_books
                save_config()
                print(f"✅ Marked request as actioned: {book.get('title', 'Unknown')}")
                return True

        return False
    except Exception as e:
        print(f"⚠️ Failed to mark request as actioned: {e}")
        return False


def check_book_in_library(title, author=None):
    """
    Check if a book with the given title (and optionally author) exists in the Calibre library.
    Returns the book ID if found, None otherwise.
    """
    try:
        conn = get_db_connection(readonly=True)
        cursor = conn.cursor()

        # Search by title (case-insensitive)
        title_pattern = f'%{title}%'

        if author:
            # Search with both title and author
            author_pattern = f'%{author}%'
            cursor.execute("""
                SELECT DISTINCT b.id, b.title
                FROM books b
                LEFT JOIN books_authors_link bal ON b.id = bal.book
                LEFT JOIN authors a ON bal.author = a.id
                WHERE b.title LIKE ? AND a.name LIKE ?
                LIMIT 1
            """, (title_pattern, author_pattern))
        else:
            # Search by title only
            cursor.execute("""
                SELECT id, title FROM books
                WHERE title LIKE ?
                LIMIT 1
            """, (title_pattern,))

        row = cursor.fetchone()
        conn.close()

        return row['id'] if row else None
    except Exception as e:
        print(f"⚠️ Error checking library for book: {e}")
        return None


def cleanup_fulfilled_requests():
    """
    Remove requests for books that are now in the Calibre library.
    Returns list of removed book titles.
    """
    try:
        requested_books = config.get('requested_books', [])
        if not requested_books:
            return []

        removed = []
        remaining = []

        for book in requested_books:
            title = book.get('title', '')
            author = book.get('author', '')

            # Check if book is now in library
            book_id = check_book_in_library(title, author)
            if book_id:
                removed.append(title)
                print(f"📚 Request fulfilled - found in library: {title}")
            else:
                remaining.append(book)

        if removed:
            config['requested_books'] = remaining
            save_config()
            print(f"🧹 Cleaned up {len(removed)} fulfilled request(s)")

        return removed
    except Exception as e:
        print(f"⚠️ Error cleaning up requests: {e}")
        return []


def transform_hardcover_books(results):
    """Transform Hardcover API book results to our format (for discovery features)"""
    books = []
    for book in results:
        if not book:
            continue
            
        # Extract author from cached_contributors
        author = ''
        contributors = book.get('cached_contributors', [])
        if contributors and isinstance(contributors, list):
            author_entry = next((c for c in contributors if c.get('contribution') == 'Author'), None)
            if author_entry:
                author = author_entry.get('author', {}).get('name', '')
            elif contributors:
                author = contributors[0].get('author', {}).get('name', '')

        # Extract image URL from cached_image object
        image = ''
        cached_image = book.get('cached_image')
        if cached_image:
            if isinstance(cached_image, dict):
                image = cached_image.get('url', '')
            elif isinstance(cached_image, str):
                image = cached_image

        # Extract genres/tags from cached_genres or genres field
        genres = []
        if 'cached_genres' in book and book.get('cached_genres'):
            if isinstance(book['cached_genres'], list):
                genres = [g.get('name', '') if isinstance(g, dict) else str(g) for g in book['cached_genres'] if g]
            elif isinstance(book['cached_genres'], str):
                genres = [book['cached_genres']]
        elif 'genres' in book and book.get('genres'):
            if isinstance(book['genres'], list):
                genres = [g.get('name', '') if isinstance(g, dict) else str(g) for g in book['genres'] if g]
            elif isinstance(book['genres'], str):
                genres = [book['genres']]

        books.append({
            'id': book.get('id'),
            'title': book.get('title', ''),
            'author': author,
            'year': book.get('release_year'),
            'pages': book.get('pages'),
            'description': book.get('description', ''),
            'image': image,
            'rating': book.get('rating'),
            'ratings_count': book.get('ratings_count', 0),
            'slug': book.get('slug', ''),
            'genres': genres
        })
    
    return books


def transform_itunes_books(results):
    """Transform iTunes API book results to our format (for metadata search)"""
    books = []
    if not results or 'results' not in results:
        return books
    
    for book in results.get('results', []):
        if not book:
            continue
        
        # Extract year from releaseDate
        year = None
        release_date = book.get('releaseDate')
        if release_date:
            try:
                # releaseDate format: "2010-01-01T00:00:00Z" or "2010-01-01"
                year = int(release_date.split('-')[0])
            except (ValueError, IndexError):
                pass
        
        # Extract genres array and remove "Books" genre
        genres = book.get('genres', [])
        if not isinstance(genres, list):
            genres = [genres] if genres else []
        # Remove "Books" genre from every result
        genres = [g for g in genres if g and g != 'Books']
        
        # Extract rating (averageUserRating from iTunes API)
        rating = book.get('averageUserRating')
        # iTunes ratings are 0-5, convert to 0-5 scale (already correct)
        
        # Extract image URL - prioritize artworkUrl512, fallback to artworkUrl100, then artworkUrl60
        # Always upgrade to 512x512 by replacing dimensions in the URL
        image = book.get('artworkUrl512')
        if not image:
            # Try to get any available artwork URL and upgrade it to 512x512
            base_url = book.get('artworkUrl100') or book.get('artworkUrl60') or book.get('artworkUrl30') or ''
            if base_url:
                # Replace any dimension pattern (60x60, 100x100, 30x30, etc.) with 512x512
                # This works because iTunes URLs have the pattern: .../artworkUrl60/60x60bb.jpg -> .../artworkUrl60/512x512bb.jpg
                image = re.sub(r'\d+x\d+', '512x512', base_url)
        # Clean description - remove bold tags but preserve paragraph layout and rich formatting
        description = book.get('description', '')
        if description:
            # Remove bold/strong tags but keep the text content and all other formatting
            # This preserves italics, links, paragraph structure, and other rich formatting
            description = re.sub(r'</?(?:b|strong)[^>]*>', '', description, flags=re.IGNORECASE)
            
            # Clean up any double spaces that might result from tag removal
            # But preserve the HTML structure and paragraph layout
            description = re.sub(r'  +', ' ', description)  # Multiple spaces to single space
            description = description.strip()
        
        books.append({
            'id': book.get('trackId'),  # Use trackId as unique identifier
            'title': book.get('trackName', ''),
            'author': book.get('artistName', ''),
            'year': year,
            'description': description,
            'image': image,
            'genres': genres,
            'rating': rating  # Star rating from iTunes (0-5)
        })
    
    return books


def search_itunes(query, limit=20, offset=0):
    """Search iTunes API for books (with caching)"""
    # Create cache key from query parameters
    cache_key = f"itunes_search:{query}:{limit}:{offset}"
    
    # Check cache first
    cached = api_cache.get(cache_key)
    if cached is not None:
        print(f"📦 Cache hit: iTunes search '{query}'")
        return cached
    
    # iTunes Search API endpoint
    # media=ebook for books, limit results
    # Note: iTunes API doesn't support offset directly, but we can request more and slice
    # For pagination, we'll request limit + offset and then slice
    requested_limit = limit + offset
    search_url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&media=ebook&limit={requested_limit}&country=us"
    try:
        req = urllib.request.Request(search_url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'errorMessage' in data:
                return {'error': data['errorMessage']}
            
            transformed = transform_itunes_books(data)
            
            # Apply offset by slicing results (iTunes API doesn't support offset directly)
            if offset > 0 and isinstance(transformed, list):
                transformed = transformed[offset:]
            
            # Limit results to requested limit
            if isinstance(transformed, list) and len(transformed) > limit:
                transformed = transformed[:limit]
            
            result = {'books': transformed}
            
            # Cache successful results
            api_cache.set(cache_key, result, CACHE_TTL_ITUNES_SEARCH)
            print(f"📦 Cached: iTunes search '{query}'")
            
            return result

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        print(f"❌ iTunes API error: {e.code} - {error_body}")
        return {'error': f'API error: {e.code}'}
    except urllib.error.URLError as e:
        print(f"❌ iTunes connection error: {e.reason}")
        return {'error': f'Connection error: {e.reason}'}
    except Exception as e:
        print(f"❌ iTunes search error: {e}")
        return {'error': str(e)}


def identify_book_from_image(base64_image):
    """Use Claude API with vision to identify a book from a cover image.

    Args:
        base64_image: Base64-encoded JPEG image data (without data URI prefix)

    Returns:
        dict with 'title' and 'author' if identified, or 'error' if failed
    """
    anthropic_api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()

    if not anthropic_api_key:
        return {'error': 'ANTHROPIC_API_KEY environment variable not configured'}

    try:
        # Claude API endpoint for messages
        api_url = "https://api.anthropic.com/v1/messages"

        # Prepare the request payload with vision
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64_image
                            }
                        },
                        {
                            "type": "text",
                            "text": "What book is this? Reply with just the title and author in format: Title: <title>\nAuthor: <author>"
                        }
                    ]
                }
            ]
        }

        # Make the API request
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(api_url, data=req_data, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('x-api-key', anthropic_api_key)
        req.add_header('anthropic-version', '2023-06-01')

        print(f"📷 Sending image to Claude API for book identification...")

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))

            # Extract the text response
            if 'content' in result and len(result['content']) > 0:
                text_response = result['content'][0].get('text', '')
                print(f"📷 Claude response: {text_response}")

                # Parse title and author from response
                title = None
                author = None

                for line in text_response.strip().split('\n'):
                    line = line.strip()
                    if line.lower().startswith('title:'):
                        title = line[6:].strip()
                    elif line.lower().startswith('author:'):
                        author = line[7:].strip()

                if title:
                    return {
                        'title': title,
                        'author': author or '',
                        'raw_response': text_response
                    }
                else:
                    # Couldn't parse, return the raw response for debugging
                    return {
                        'error': "Couldn't identify book from image",
                        'raw_response': text_response
                    }
            else:
                return {'error': 'Empty response from Claude API'}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        print(f"❌ Claude API HTTP error: {e.code} - {error_body}")
        return {'error': f'Claude API error: {e.code}'}
    except urllib.error.URLError as e:
        print(f"❌ Claude API connection error: {e.reason}")
        return {'error': f'Connection error: {e.reason}'}
    except Exception as e:
        print(f"❌ Claude API error: {e}")
        return {'error': str(e)}


def get_trending_hardcover(token, limit=20):
    """Get most popular books from 2025 on Hardcover (with caching)"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

    # Check cache first
    cache_key = f"hardcover_trending:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        print(f"📦 Cache hit: Hardcover trending")
        return cached

    # GraphQL query for trending books from 2025
    # Books filtered by release_year 2025, sorted by users_read_count (most popular)
    graphql_query = """
    query TrendingBooks2025($limit: Int!) {
        books(
            limit: $limit, 
            where: {release_year: {_eq: 2025}},
            order_by: {users_read_count: desc}
        ) {
            id
            title
            slug
            release_year
            pages
            description
            cached_image
            cached_contributors
            rating
            ratings_count
            users_read_count
        }
    }
    """

    payload = json.dumps({
        'query': graphql_query,
        'variables': {
            'limit': limit
        }
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(
            HARDCOVER_API_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if 'errors' in data:
                return {'error': data['errors'][0].get('message', 'GraphQL error')}

            # Get books directly from query result
            results = data.get('data', {}).get('books', [])

            # Transform results
            books = transform_hardcover_books(results)
            result = {'books': books}
            
            # Cache successful results
            api_cache.set(cache_key, result, CACHE_TTL_HARDCOVER_TRENDING)
            print(f"📦 Cached: Hardcover trending")
            
            return result

    except Exception as e:
        print(f"❌ Hardcover trending error: {e}")
        return {'error': str(e)}


def get_recent_releases_hardcover(token, limit=20):
    """Get recent book releases from Hardcover - matches /upcoming/recent page (with caching)"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

    # Check cache first
    cache_key = f"hardcover_recent:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        print(f"📦 Cache hit: Hardcover recent releases")
        return cached

    # Calculate recent timeframe - last 14 days (matches Hardcover's recent page)
    from datetime import datetime, timedelta
    today = datetime.now()
    fourteen_days_ago = (today - timedelta(days=14)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    # GraphQL query for recent releases - books released in last 2 weeks
    # Sorted by users_count (popularity) like Hardcover does
    graphql_query = """
    query RecentReleases($startDate: date!, $endDate: date!, $limit: Int) {
        books(
            where: { 
                release_date: { _gte: $startDate, _lte: $endDate }
            }
            order_by: { users_count: desc }
            limit: $limit
        ) {
            id
            title
            slug
            release_year
            release_date
            pages
            description
            cached_image
            cached_contributors
            rating
            ratings_count
            users_count
        }
    }
    """

    payload = json.dumps({
        'query': graphql_query,
        'variables': {
            'startDate': fourteen_days_ago,
            'endDate': today_str,
            'limit': limit
        }
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(
            HARDCOVER_API_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if 'errors' in data:
                return {'error': data['errors'][0].get('message', 'GraphQL error')}

            results = data.get('data', {}).get('books', [])
            books = transform_hardcover_books(results)
            result = {'books': books}
            
            # Cache successful results
            api_cache.set(cache_key, result, CACHE_TTL_HARDCOVER_RECENT)
            print(f"📦 Cached: Hardcover recent releases")
            
            return result

    except Exception as e:
        print(f"❌ Hardcover recent releases error: {e}")
        return {'error': str(e)}


def get_hardcover_popular_lists(token):
    """Get popular lists from Hardcover - first 30, then pick 3 random (with caching)"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

    # Check cache first
    # Note: We cache the full list of 25 lists, not the random selection
    # This allows the random selection to change on each page load
    cache_key = "hardcover_popular_lists_all"
    cached = api_cache.get(cache_key)
    
    if cached is not None:
        print(f"📦 Cache hit: Hardcover popular lists")
        # Pick 3 random lists from cached results
        lists = cached.get('all_lists', [])
        if len(lists) > 3:
            selected_lists = random.sample(lists, 3)
        else:
            selected_lists = lists
        return {'lists': selected_lists}

    # GraphQL query to get popular lists - matches /lists/popular
    # Get top 25 lists ordered by popularity
    graphql_query = """
    query PopularLists {
        lists(
            limit: 25,
            order_by: {followers_count: desc}
        ) {
            id
            name
            description
            slug
        }
    }
    """

    payload = json.dumps({
        'query': graphql_query,
        'variables': {}
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(
            HARDCOVER_API_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if 'errors' in data:
                return {'error': data['errors'][0].get('message', 'GraphQL error')}

            lists = data.get('data', {}).get('lists', [])
            
            # Cache all lists for future random selections
            api_cache.set(cache_key, {'all_lists': lists}, CACHE_TTL_HARDCOVER_LISTS)
            print(f"📦 Cached: Hardcover popular lists")
            
            # Pick 3 random lists from the top 25
            if len(lists) > 3:
                selected_lists = random.sample(lists, 3)
            else:
                selected_lists = lists
            return {'lists': selected_lists}

    except Exception as e:
        print(f"❌ Hardcover popular lists error: {e}")
        return {'error': str(e)}


def get_list_hardcover(token, list_id, limit=20):
    """Get books from a specific Hardcover list by ID (with caching)"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

    # Check cache first
    cache_key = f"hardcover_list:{list_id}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        print(f"📦 Cache hit: Hardcover list {list_id}")
        return cached

    # GraphQL query for list books
    graphql_query = """
    query ListBooks($listId: Int!, $limit: Int) {
        lists(where: {id: {_eq: $listId}}) {
            id
            name
            description
            list_books(limit: $limit, order_by: {position: asc}) {
                book {
                    id
                    title
                    slug
                    release_year
                    pages
                    description
                    cached_image
                    cached_contributors
                    rating
                    ratings_count
                }
            }
        }
    }
    """

    payload = json.dumps({
        'query': graphql_query,
        'variables': {
            'listId': int(list_id),
            'limit': limit
        }
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(
            HARDCOVER_API_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if 'errors' in data:
                return {'error': data['errors'][0].get('message', 'GraphQL error')}

            lists = data.get('data', {}).get('lists', [])
            if not lists:
                return {'error': 'List not found'}

            list_data = lists[0]
            list_books = list_data.get('list_books', [])

            # Extract books from list_books structure
            raw_books = [item.get('book') for item in list_books if item.get('book')]
            books = transform_hardcover_books(raw_books)
            result = {
                'books': books,
                'list_name': list_data.get('name', ''),
                'list_description': list_data.get('description', '')
            }
            
            # Cache successful results
            api_cache.set(cache_key, result, CACHE_TTL_HARDCOVER_LIST)
            print(f"📦 Cached: Hardcover list {list_id}")
            
            return result

    except Exception as e:
        print(f"❌ Hardcover list error: {e}")
        return {'error': str(e)}


def get_books_by_author_hardcover(token, author_name, limit=20):
    """Get books by a specific author from Hardcover (with caching)"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

    # Check cache first
    cache_key = f"hardcover_author:{author_name.lower()}:{limit}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        print(f"📦 Cache hit: Hardcover author '{author_name}'")
        return cached

    # GraphQL query to search for books by author (API returns results as JSON blob)
    graphql_query = """
    query BooksByAuthor($authorName: String!) {
        search(query: $authorName, query_type: "Book") {
            results
        }
    }
    """

    payload = json.dumps({
        'query': graphql_query,
        'variables': {
            'authorName': author_name
        }
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(
            HARDCOVER_API_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

            if 'errors' in data:
                return {'error': data['errors'][0].get('message', 'GraphQL error')}

            # New API returns results as JSON with hits array
            results_json = data.get('data', {}).get('search', {}).get('results', {})
            hits = results_json.get('hits', [])
            
            books = []
            for hit in hits:
                doc = hit.get('document', {})
                # Extract author from author_names
                author = ''
                author_names = doc.get('author_names', [])
                if author_names:
                    author = author_names[0]
                
                # Only include if author matches (case-insensitive)
                if author.lower() != author_name.lower():
                    continue
                
                # Get image URL
                image = ''
                if doc.get('image') and isinstance(doc['image'], dict):
                    image = doc['image'].get('url', '')
                
                books.append({
                    'id': doc.get('id'),
                    'title': doc.get('title', ''),
                    'author': author,
                    'year': doc.get('release_year'),
                    'pages': doc.get('pages'),
                    'description': doc.get('description', ''),
                    'image': image,
                    'rating': doc.get('rating'),
                    'ratings_count': doc.get('ratings_count', 0),
                    'slug': doc.get('slug', '')
                })
                
                if len(books) >= limit:
                    break

            result = {
                'books': books,
                'author_name': author_name
            }
            
            # Cache successful results
            api_cache.set(cache_key, result, CACHE_TTL_HARDCOVER_AUTHOR)
            print(f"📦 Cached: Hardcover author '{author_name}'")
            
            return result

    except Exception as e:
        print(f"❌ Hardcover author books error: {e}")
        return {'error': str(e)}


def list_directories(path):
    """List directories at the given path"""
    try:
        # Expand ~ to home directory
        path = os.path.expanduser(path)

        # Security: convert to absolute path and resolve symlinks
        path = os.path.abspath(path)

        if not os.path.exists(path):
            return {'error': 'Path does not exist', 'path': path}

        if not os.path.isdir(path):
            return {'error': 'Path is not a directory', 'path': path}

        # Get parent directory
        parent = str(Path(path).parent)

        # List directories
        entries = []
        try:
            for entry in sorted(os.listdir(path)):
                entry_path = os.path.join(path, entry)
                if os.path.isdir(entry_path):
                    # Check if it's a Calibre library by looking for metadata.db
                    is_calibre_library = os.path.exists(os.path.join(entry_path, 'metadata.db'))
                    entries.append({
                        'name': entry,
                        'path': entry_path,
                        'is_calibre_library': is_calibre_library
                    })
        except PermissionError:
            return {'error': 'Permission denied', 'path': path}

        return {
            'path': path,
            'parent': parent if parent != path else None,
            'entries': entries
        }
    except Exception as e:
        return {'error': str(e), 'path': path}


class FolioHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="public", **kwargs)

    def guess_type(self, path):
        """Override to provide correct MIME types for PWA files"""
        if path.endswith('.manifest') or path.endswith('manifest.json'):
            return 'application/manifest+json'
        if path.endswith('.webmanifest'):
            return 'application/manifest+json'
        if path.endswith('service-worker.js') or path.endswith('.js'):
            return 'application/javascript'
        if path.endswith('.json'):
            return 'application/json'
        if path.endswith('.png'):
            return 'image/png'
        if path.endswith('.ico'):
            return 'image/x-icon'
        if path.endswith('.svg'):
            return 'image/svg+xml'
        return super().guess_type(path)

    def do_GET(self):
        # Parse URL
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        # Store parsed_url for use in handlers
        self.parsed_url = parsed_url
        
        # Kobo e-ink interface (server-rendered, no JavaScript)
        if path == '/kobo':
            try:
                page = int(query_params.get('page', [1])[0])
                sort = query_params.get('sort', ['added'])[0]
                if sort not in ('added', 'title', 'author'):
                    sort = 'added'
                
                books = get_reading_list_books(sort=sort)
                html = render_kobo_page(books, page=page, sort=sort, books_per_page=5)
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
                return
            except Exception as e:
                print(f"❌ Kobo page error: {e}")
                self.send_error(500, f"Error rendering Kobo page: {str(e)}")
                return
        
        # API: Get import status
        if path == '/api/import/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Get import state snapshot with lock for thread safety
            with import_state_lock:
                state_snapshot = {
                    'running': import_state.get('running', False),
                    'last_scan': import_state.get('last_scan'),
                    'last_import': import_state.get('last_import'),
                    'last_imported_count': import_state.get('last_imported_count', 0),
                    'total_imported': import_state.get('total_imported', 0),
                    'imported_files_count': len(import_state.get('imported_files', [])),
                    'errors': list(import_state.get('errors', [])),
                    'kepub_converting': import_state.get('kepub_converting'),
                    'kepub_convert_start': import_state.get('kepub_convert_start'),
                    'kepub_last_file': import_state.get('kepub_last_file'),
                    'kepub_last_success': import_state.get('kepub_last_success'),
                    'kepub_last_log': import_state.get('kepub_last_log'),
                }
            status = {
                'enabled': bool(config.get('import_folder')),
                'running': state_snapshot['running'],
                'folder': config.get('import_folder', ''),
                'interval': config.get('import_interval', 60),
                'recursive': config.get('import_recursive', True),
                'delete_after_import': config.get('import_delete', False),
                'last_scan': state_snapshot['last_scan'],
                'last_import': state_snapshot['last_import'],
                'last_imported_count': state_snapshot['last_imported_count'],
                'total_imported': state_snapshot['total_imported'],
                'pending_files': len(scan_import_folder()) - state_snapshot['imported_files_count'],
                'errors': state_snapshot['errors'],
                # KEPUB conversion status (for debugging - can be removed later)
                'kepub': {
                    'converting': state_snapshot['kepub_converting'],
                    'convert_start': state_snapshot['kepub_convert_start'],
                    'last_file': state_snapshot['kepub_last_file'],
                    'last_success': state_snapshot['kepub_last_success'],
                    'last_log': state_snapshot['kepub_last_log'],
                }
            }
            response = json.dumps(status)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get config
        if path == '/api/config':
            # Re-check env vars on each request to ensure they're fresh (fixes Docker env var persistence)
            env_hardcover = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            env_prowlarr_url = os.getenv('PROWLARR_URL', '').strip().strip()
            env_prowlarr_key = sanitize_token(os.getenv('PROWLARR_API_KEY', ''))
            if env_hardcover:
                config['hardcover_token'] = env_hardcover
            if env_prowlarr_url:
                config['prowlarr_url'] = env_prowlarr_url
            if env_prowlarr_key:
                config['prowlarr_api_key'] = env_prowlarr_key
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Don't expose the full tokens, just whether they're set
            # BUT: For Hardcover token, expose the actual value if it exists (user needs to see it)
            # For Prowlarr API key, only expose boolean for security
            safe_config = {
                **config,
                'calibredb_path': config.get('calibredb_path', ''),
                'hardcover_token': config.get('hardcover_token', '') or bool(config.get('hardcover_token')),  # Return actual value if set
                'prowlarr_url': config.get('prowlarr_url', ''),
                'prowlarr_api_key': bool(config.get('prowlarr_api_key'))  # Only boolean for security
            }
            response = json.dumps(safe_config)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Search iTunes (for metadata matching)
        if path == '/api/itunes/search':
            query = query_params.get('q', [''])[0]
            limit = int(query_params.get('limit', [20])[0])
            offset = int(query_params.get('offset', [0])[0])

            if not query:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': 'Query parameter q is required'})
                self.wfile.write(response.encode('utf-8'))
                return
            result = search_itunes(query, limit, offset)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get trending from Hardcover
        if path == '/api/hardcover/trending':
            # Re-check env var on each request to ensure it's fresh (fixes Docker env var persistence)
            env_hardcover_token = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            if env_hardcover_token:
                config['hardcover_token'] = env_hardcover_token

            limit = int(query_params.get('limit', [20])[0])
            token = config.get('hardcover_token', '')
            result = get_trending_hardcover(token, limit)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get recent releases from Hardcover
        if path == '/api/hardcover/recent':
            # Re-check env var on each request to ensure it's fresh (fixes Docker env var persistence)
            env_hardcover_token = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            if env_hardcover_token:
                config['hardcover_token'] = env_hardcover_token

            limit = int(query_params.get('limit', [20])[0])
            token = config.get('hardcover_token', '')
            result = get_recent_releases_hardcover(token, limit)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get popular lists
        if path == '/api/hardcover/lists':
            # Re-check env var on each request to ensure it's fresh (fixes Docker env var persistence)
            env_hardcover_token = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            if env_hardcover_token:
                config['hardcover_token'] = env_hardcover_token

            token = config.get('hardcover_token', '')
            result = get_hardcover_popular_lists(token)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get books from a Hardcover list
        if path == '/api/hardcover/list':
            list_id = query_params.get('id', [''])[0]
            if not list_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': 'List ID parameter is required'})
                self.wfile.write(response.encode('utf-8'))
                return

            # Re-check env var on each request to ensure it's fresh (fixes Docker env var persistence)
            env_hardcover_token = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            if env_hardcover_token:
                config['hardcover_token'] = env_hardcover_token

            limit = int(query_params.get('limit', [20])[0])
            token = config.get('hardcover_token', '')
            result = get_list_hardcover(token, list_id, limit)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get books by author from Hardcover
        if path == '/api/hardcover/author':
            author = query_params.get('author', [''])[0]
            if not author:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': 'Author parameter is required'})
                self.wfile.write(response.encode('utf-8'))
                return

            # Re-check env var on each request to ensure it's fresh (fixes Docker env var persistence)
            env_hardcover_token = sanitize_token(os.getenv('HARDCOVER_TOKEN', ''))
            if env_hardcover_token:
                config['hardcover_token'] = env_hardcover_token

            limit = int(query_params.get('limit', [20])[0])
            token = config.get('hardcover_token', '')
            result = get_books_by_author_hardcover(token, author, limit)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Search Prowlarr for a book
        if path == '/api/prowlarr/search':
            query = query_params.get('q', [''])[0]
            author = query_params.get('author', [''])[0]
            
            if not query:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': 'Query parameter q is required'})
                self.wfile.write(response.encode('utf-8'))
                return

            # Re-check env vars on each request to ensure they're fresh (fixes Docker env var persistence)
            env_prowlarr_url = os.getenv('PROWLARR_URL', '').strip()
            env_prowlarr_key = sanitize_token(os.getenv('PROWLARR_API_KEY', ''))
            if env_prowlarr_url:
                config['prowlarr_url'] = env_prowlarr_url
            if env_prowlarr_key:
                config['prowlarr_api_key'] = env_prowlarr_key

            prowlarr_url = config.get('prowlarr_url', '').rstrip('/')
            prowlarr_api_key = config.get('prowlarr_api_key', '')
            
            if not prowlarr_url or not prowlarr_api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': 'Prowlarr not configured'})
                self.wfile.write(response.encode('utf-8'))
                return

            try:
                # Build search query - combine title and author
                search_query = query
                if author:
                    search_query = f"{author} {query}"
                
                # Prowlarr uses /api/v1/search endpoint
                # Restrict to a single indexer (MyAnonamouse = ID 3)
                search_url = f"{prowlarr_url}/api/v1/search?query={urllib.parse.quote(search_query)}&indexerIds=3"
                req = urllib.request.Request(search_url)
                req.add_header('X-Api-Key', prowlarr_api_key)
                
                with urllib.request.urlopen(req) as response:
                    results = json.loads(response.read().decode('utf-8'))
                    
                    # Transform results to a simpler format
                    formatted_results = []
                    missing_indexer_count = 0
                    for idx, item in enumerate(results):
                        indexer_id = item.get('indexerId')
                        if indexer_id is None:
                            missing_indexer_count += 1
                        
                        # Log first few results to stdout (visible in Docker logs)
                        if idx < 3:
                            print(f"🔍 Search result {idx}: title={item.get('title', 'Unknown')[:50]}, indexerId={indexer_id}, indexer={item.get('indexer', 'Unknown')}, guid={item.get('guid', '')[:50]}")
                        
                        # Get download URL - prefer magnetUrl, then downloadUrl, then infoUrl
                        download_url = item.get('downloadUrl', '')
                        magnet_url = item.get('magnetUrl', '')
                        info_url = item.get('infoUrl', '')
                        
                        formatted_results.append({
                            'title': item.get('title', 'Unknown'),
                            'author': item.get('author', 'Unknown'),
                            'indexer': item.get('indexer', 'Unknown'),
                            'indexerId': indexer_id,
                            'size': item.get('size', 0),
                            'seeders': item.get('seeders', 0),
                            'leechers': item.get('leechers', 0),
                            'downloadUrl': download_url,
                            'magnetUrl': magnet_url,
                            'infoUrl': info_url,
                            'guid': item.get('guid', ''),
                            'publishDate': item.get('publishDate', ''),
                            'categories': item.get('categories', [])
                        })
                    
                    print(f"🔍 Prowlarr search: {len(formatted_results)} results, {missing_indexer_count} missing indexerId")
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'results': formatted_results})
                    self.wfile.write(response.encode('utf-8'))
            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
                print(f"❌ Prowlarr HTTP error {e.code}: {error_body}")
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': f'Prowlarr API error: {error_body}'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                print(f"❌ Prowlarr search error: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': f'Failed to search Prowlarr: {str(e)}'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Get requested books
        if path == '/api/requests':
            # First, clean up any requests for books now in the library
            fulfilled = cleanup_fulfilled_requests()

            requested_books = config.get('requested_books', [])
            # Ensure all books have a requested_at timestamp (set to today if missing)
            current_timestamp = int(time.time())
            needs_save = False
            for book in requested_books:
                if 'requested_at' not in book or not book.get('requested_at'):
                    book['requested_at'] = current_timestamp
                    needs_save = True

            # Save updated books back to config if needed
            if needs_save:
                config['requested_books'] = requested_books
                save_config()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({
                'books': requested_books,
                'fulfilled': fulfilled if fulfilled else None
            })
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get reading list (IDs of library books)
        if path == '/api/reading-list':
            try:
                # Ensure the column exists before trying to get reading list
                ensure_reading_list_column()
                ids = get_reading_list_ids()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'ids': ids})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Failed to load reading list: {e}")
            return
        
        # API: Get all unique authors from library (for autocomplete)
        if path == '/api/authors':
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT name FROM authors ORDER BY name")
                raw_authors = [row['name'] for row in cursor.fetchall()]
                conn.close()
                
                # Normalize author names: convert "LastName, FirstName" or "LastName| FirstName" to "FirstName LastName"
                def normalize_author_name(author_str):
                    """Convert 'LastName, FirstName' or 'LastName| FirstName' to 'FirstName LastName'"""
                    author_str = author_str.strip()
                    if not author_str:
                        return None
                    
                    # Handle pipe format: "LastName| FirstName" or "LastName|FirstName"
                    if '|' in author_str:
                        parts = author_str.split('|', 1)
                        if len(parts) == 2:
                            last_name = parts[0].strip()
                            first_name = parts[1].strip()
                            if first_name and last_name:
                                return f"{first_name} {last_name}"
                    
                    # Handle comma format: "LastName, FirstName" or "LastName,FirstName"
                    if ', ' in author_str:
                        parts = author_str.split(', ', 1)
                        if len(parts) == 2:
                            last_name = parts[0].strip()
                            first_name = parts[1].strip()
                            if first_name and last_name:
                                return f"{first_name} {last_name}"
                    elif author_str.count(',') == 1 and not author_str.startswith(','):
                        parts = author_str.split(',', 1)
                        if len(parts) == 2:
                            last_name = parts[0].strip()
                            first_name = parts[1].strip()
                            if first_name and last_name:
                                return f"{first_name} {last_name}"
                    
                    # If no conversion needed, return as-is
                    return author_str
                
                # Normalize all authors and deduplicate
                normalized_authors = []
                seen = set()
                for author in raw_authors:
                    normalized = normalize_author_name(author)
                    if normalized:
                        key = normalized.lower()
                        if key not in seen:
                            seen.add(key)
                            normalized_authors.append(normalized)
                
                # Sort by last name for autocomplete
                def get_last_name_for_sort(author):
                    """Extract last name for sorting"""
                    parts = author.split()
                    if len(parts) >= 2:
                        return parts[-1]  # Last word is last name
                    return author
                
                normalized_authors.sort(key=get_last_name_for_sort)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps(normalized_authors)
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Database error: {e}")
            return
        
        # API: Get all unique tags/genres from library (for autocomplete)
        if path == '/api/tags':
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT name FROM tags ORDER BY name")
                tags = [row['name'] for row in cursor.fetchall()]
                conn.close()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps(tags)
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Database error: {e}")
            return

        # API: Browse directories
        if path == '/api/browse':
            browse_path = query_params.get('path', [os.path.expanduser('~')])[0]
            result = list_directories(browse_path)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get books
        if path == '/api/books':
            limit = int(query_params.get('limit', [50])[0])
            offset = int(query_params.get('offset', [0])[0])
            search = query_params.get('search', [None])[0]
            sort = query_params.get('sort', ['recent'])[0]  # 'recent', 'title', 'author'

            books = get_books(limit=limit, offset=offset, search=search, sort=sort)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(books)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get book cover
        cover_match = re.match(r'/api/cover/(\d+)', path)
        if cover_match:
            book_id = int(cover_match.group(1))
            cover_data = get_book_cover(book_id)

            if cover_data:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                # Use aggressive caching since URL is versioned with ?v= parameter
                # immutable tells browser this URL's content will never change
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.end_headers()
                self.wfile.write(cover_data)
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')  # Prevent 404 caching
                self.end_headers()
                self.wfile.write(b"Cover not found")
            return

        # API: Download book file
        download_match = re.match(r'/api/download/(\d+)/(\w+)', path)
        if download_match:
            book_id = int(download_match.group(1))
            format = download_match.group(2).upper()

            try:
                conn = get_db_connection()
                cursor = conn.cursor()

                # Get book path and format file
                cursor.execute(
                    "SELECT b.path, b.title, d.name, d.format FROM books b JOIN data d ON b.id = d.book WHERE b.id = ? AND d.format = ?",
                    (book_id, format)
                )
                row = cursor.fetchone()
                conn.close()

                if not row:
                    self.send_error(404, f"Book format {format} not found")
                    return

                library_path = get_calibre_library()
                book_file_path = os.path.join(library_path, row['path'], f"{row['name']}.{format.lower()}")

                # Handle KEPUB files which may have .kepub.epub extension
                if not os.path.exists(book_file_path) and format == 'KEPUB':
                    book_file_path = os.path.join(library_path, row['path'], f"{row['name']}.kepub.epub")

                if not os.path.exists(book_file_path):
                    self.send_error(404, f"Book file not found at {book_file_path}")
                    return

                # Determine MIME type based on format
                mime_types = {
                    'EPUB': 'application/epub+zip',
                    'KEPUB': 'application/epub+zip',  # KEPUB is Kobo's extended EPUB
                    'PDF': 'application/pdf',
                    'MOBI': 'application/x-mobipocket-ebook',
                    'AZW3': 'application/vnd.amazon.ebook',
                    'TXT': 'text/plain',
                }
                mime_type = mime_types.get(format, 'application/octet-stream')

                # Clean filename for Content-Disposition header
                safe_title = row["title"].replace('"', "'").replace('\n', ' ').replace('\r', '')
                # Use .epub extension for KEPUB files so devices recognize them
                file_ext = 'epub' if format == 'KEPUB' else format.lower()

                # Send the file
                with open(book_file_path, 'rb') as f:
                    book_data = f.read()

                self.send_response(200)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Disposition', f'attachment; filename="{safe_title}.{file_ext}"')
                self.send_header('Content-Length', len(book_data))
                self.end_headers()
                self.wfile.write(book_data)
                print(f"📥 Downloaded: {row['title']} ({format})")
                return

            except Exception as e:
                print(f"❌ Download error: {e}")
                self.send_error(500, f"Download failed: {str(e)}")
                return
        # Serve static files from public/ (directory set in __init__)
        super().do_GET()

    def do_POST(self):
        """Handle POST requests"""
        # API: Trigger manual import scan
        if self.path == '/api/import/scan':
            if not config.get('import_folder'):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Import folder not configured'})
                self.wfile.write(response.encode('utf-8'))
                return

            result = import_books_from_folder()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps(result)
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Convert book to KEPUB
        if self.path.startswith('/api/convert-to-kepub/'):
            book_id = self.path.split('/')[-1]
            try:
                book_id = int(book_id)
            except ValueError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Invalid book ID'})
                self.wfile.write(response.encode('utf-8'))
                return

            # Check if kepubify is available
            kepubify_path = find_kepubify()
            if not kepubify_path:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'kepubify not installed on server'})
                self.wfile.write(response.encode('utf-8'))
                return

            # Attempt conversion
            success = convert_book_to_kepub(book_id)
            if success:
                # Invalidate cover cache to refresh book data
                cover_cache.invalidate()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': True, 'message': 'Book converted to KEPUB'})
                self.wfile.write(response.encode('utf-8'))
            else:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'KEPUB conversion failed - check server logs'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Identify book from camera image
        if self.path == '/api/camera/identify':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'error': 'No image data provided'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))

                # Get base64 image data (strip data URI prefix if present)
                image_data = data.get('image', '')
                if image_data.startswith('data:'):
                    # Remove data URI prefix (e.g., "data:image/jpeg;base64,")
                    image_data = image_data.split(',', 1)[1] if ',' in image_data else ''

                if not image_data:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'error': 'No image data provided'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                print(f"📷 Received camera image for identification ({len(image_data)} bytes base64)")

                # Identify book using Claude API
                identify_result = identify_book_from_image(image_data)

                if 'error' in identify_result:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': identify_result['error'],
                        'raw_response': identify_result.get('raw_response', '')
                    })
                    self.wfile.write(response.encode('utf-8'))
                    return

                # Search iTunes with the identified title and author
                title = identify_result.get('title', '')
                author = identify_result.get('author', '')
                search_query = f"{title} {author}".strip()

                print(f"📷 Searching iTunes for: {search_query}")

                search_result = search_itunes(search_query, limit=20, offset=0)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({
                    'success': True,
                    'identified': {
                        'title': title,
                        'author': author
                    },
                    'search_query': search_query,
                    'books': search_result.get('books', [])
                })
                self.wfile.write(response.encode('utf-8'))

            except json.JSONDecodeError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': f'Invalid JSON: {e}'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                print(f"❌ Camera identify error: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': str(e)})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Update config
        if self.path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))

                # Update config (sanitize tokens to remove whitespace, newlines, Bearer prefix)
                if 'calibre_library' in data:
                    config['calibre_library'] = os.path.expanduser(data['calibre_library'])
                if 'calibredb_path' in data:
                    config['calibredb_path'] = data['calibredb_path'].strip()
                if 'hardcover_token' in data:
                    config['hardcover_token'] = sanitize_token(data['hardcover_token'])
                if 'prowlarr_url' in data:
                    config['prowlarr_url'] = data['prowlarr_url'].strip() if data['prowlarr_url'] else ''
                if 'prowlarr_api_key' in data:
                    config['prowlarr_api_key'] = sanitize_token(data['prowlarr_api_key'])

                # Save to file
                if save_config():
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    # Return safe config (without full tokens)
                    safe_config = {
                        **config,
                        'calibredb_path': config.get('calibredb_path', ''),
                        'hardcover_token': bool(config.get('hardcover_token')),
                        'prowlarr_url': config.get('prowlarr_url', ''),
                        'prowlarr_api_key': bool(config.get('prowlarr_api_key'))
                    }
                    response = json.dumps({'success': True, 'config': safe_config})
                    self.wfile.write(response.encode('utf-8'))
                else:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'Failed to save config'})
                    self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(400, f"Bad Request: {e}")
            return

        # API: Validate Prowlarr connection
        if self.path == '/api/prowlarr/validate':
            # Re-check env vars on each request to ensure they're fresh
            env_prowlarr_url = os.getenv('PROWLARR_URL', '').strip()
            env_prowlarr_key = sanitize_token(os.getenv('PROWLARR_API_KEY', ''))
            if env_prowlarr_url:
                config['prowlarr_url'] = env_prowlarr_url
            if env_prowlarr_key:
                config['prowlarr_api_key'] = env_prowlarr_key

            # Get Prowlarr config from request body or use config
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    post_data = self.rfile.read(content_length)
                    request_data = json.loads(post_data.decode('utf-8'))
                    prowlarr_url = request_data.get('prowlarr_url', '').rstrip('/') or config.get('prowlarr_url', '').rstrip('/')
                    prowlarr_api_key = request_data.get('prowlarr_api_key', '') or config.get('prowlarr_api_key', '')
                else:
                    prowlarr_url = config.get('prowlarr_url', '').rstrip('/')
                    prowlarr_api_key = config.get('prowlarr_api_key', '')
            except:
                prowlarr_url = config.get('prowlarr_url', '').rstrip('/')
                prowlarr_api_key = config.get('prowlarr_api_key', '')

            if not prowlarr_url or not prowlarr_api_key:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Prowlarr URL and API key are required'})
                self.wfile.write(response.encode('utf-8'))
                return

            try:
                # Test connection by checking Prowlarr system status
                test_url = f"{prowlarr_url}/api/v1/system/status"
                req = urllib.request.Request(test_url)
                req.add_header('X-Api-Key', prowlarr_api_key)

                with urllib.request.urlopen(req, timeout=10) as resp:
                    status_data = json.loads(resp.read().decode('utf-8'))

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'version': status_data.get('version', '')})
                    self.wfile.write(response.encode('utf-8'))

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
                print(f"❌ Prowlarr validation HTTP error {e.code}: {error_body}")
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if e.code == 401:
                    error_msg = 'Invalid API key. Please check your Prowlarr API key.'
                else:
                    error_msg = f'Failed to connect to Prowlarr (HTTP {e.code}). Please check your URL.'
                response = json.dumps({'success': False, 'error': error_msg})
                self.wfile.write(response.encode('utf-8'))

            except Exception as e:
                print(f"❌ Prowlarr validation error: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': f'Failed to connect to Prowlarr: {str(e)}'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Add book request
        if self.path == '/api/requests':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))
                book = data.get('book')

                if not book:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'error': 'Book data is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                # Add to requested books if not already there, or update timestamp if already exists
                requested_books = config.get('requested_books', [])
                existing_index = None
                for i, b in enumerate(requested_books):
                    if b.get('id') == book.get('id'):
                        existing_index = i
                        break
                
                # Add timestamp when requested
                book['requested_at'] = int(time.time())
                
                if existing_index is not None:
                    # Update existing request with new timestamp
                    requested_books[existing_index] = book
                else:
                    # Add new request
                    requested_books.append(book)
                
                config['requested_books'] = requested_books
                save_config()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': True, 'books': requested_books})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(400, f"Bad Request: {e}")
            return

        # API: Send torrent/magnet to qBittorrent
        if self.path == '/api/qbittorrent/add':
            print(f"📥 qBittorrent add endpoint hit", flush=True)
            
            try:
                content_length = int(self.headers['Content-Length'])
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
                
                # Get the URL to add (magnet or torrent URL)
                url = data.get('url', '')
                title = data.get('title', 'Unknown')
                
                print(f"📥 qBittorrent add request: title={title}, url={url[:100]}...", flush=True)
                
                if not url:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'URL is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return
                
                # Get qBittorrent config from environment
                qbt_url = os.getenv('QBITTORRENT_URL', '').strip().rstrip('/')
                qbt_username = os.getenv('QBITTORRENT_USERNAME', '').strip()
                qbt_password = os.getenv('QBITTORRENT_PASSWORD', '').strip()
                
                if not qbt_url:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False, 
                        'error': 'qBittorrent not configured. Set QBITTORRENT_URL environment variable.'
                    })
                    self.wfile.write(response.encode('utf-8'))
                    return
                
                print(f"🔗 Connecting to qBittorrent at {qbt_url}", flush=True)
                
                # Cookie jar for session management
                cookie_jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
                
                # Login to qBittorrent if credentials provided
                if qbt_username and qbt_password:
                    login_url = f"{qbt_url}/api/v2/auth/login"
                    login_data = urllib.parse.urlencode({
                        'username': qbt_username,
                        'password': qbt_password
                    }).encode('utf-8')
                    
                    try:
                        login_req = urllib.request.Request(login_url, data=login_data, method='POST')
                        login_req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                        login_resp = opener.open(login_req, timeout=10)
                        login_result = login_resp.read().decode('utf-8')
                        
                        if login_result.strip().lower() != 'ok.':
                            print(f"⚠️ qBittorrent login response: {login_result}", flush=True)
                        else:
                            print(f"✅ qBittorrent login successful", flush=True)
                    except urllib.error.HTTPError as e:
                        if e.code == 404:
                            print(f"❌ qBittorrent login 404 - Web UI may not be enabled or URL is wrong", flush=True)
                            self.send_response(500)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            response = json.dumps({
                                'success': False,
                                'error': f'qBittorrent Web UI not found at {qbt_url}. Please check: 1) Web UI is enabled in qBittorrent settings, 2) The URL is correct (e.g., http://localhost:8080)'
                            })
                            self.wfile.write(response.encode('utf-8'))
                            return
                        elif e.code == 403:
                            print(f"❌ qBittorrent login 403 - Invalid credentials", flush=True)
                            self.send_response(500)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            response = json.dumps({
                                'success': False,
                                'error': 'qBittorrent login failed: Invalid username or password'
                            })
                            self.wfile.write(response.encode('utf-8'))
                            return
                        else:
                            print(f"⚠️ qBittorrent login failed with HTTP {e.code}: {e}", flush=True)
                            # Continue anyway - might work without auth
                    except urllib.error.URLError as e:
                        print(f"❌ Cannot connect to qBittorrent at {qbt_url}: {e.reason}", flush=True)
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        response = json.dumps({
                            'success': False,
                            'error': f'Cannot connect to qBittorrent at {qbt_url}. Is it running? Error: {e.reason}'
                        })
                        self.wfile.write(response.encode('utf-8'))
                        return
                    except Exception as e:
                        print(f"⚠️ qBittorrent login failed: {e}", flush=True)
                        # Continue anyway - maybe auth is disabled
                
                # Add torrent to qBittorrent
                add_url = f"{qbt_url}/api/v2/torrents/add"

                # Check if this is a magnet link or a torrent URL
                is_magnet = url.startswith('magnet:')
                
                if is_magnet:
                    # For magnet links, just send the URL with ebook category
                    print(f"🔗 Sending magnet to qBittorrent: {url[:80]}...", flush=True)
                    add_data = urllib.parse.urlencode({'urls': url, 'category': 'ebooks'}).encode('utf-8')
                    add_req = urllib.request.Request(add_url, data=add_data, method='POST')
                    add_req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                else:
                    # For torrent URLs (like Prowlarr download links), download the .torrent file first
                    # then send it to qBittorrent. Prowlarr download links expire/timeout so qBittorrent
                    # can't fetch them directly - we need to proxy the download (like Radarr/Sonarr do)
                    print(f"🔗 Downloading torrent file from: {url[:80]}...", flush=True)
                    
                    try:
                        torrent_req = urllib.request.Request(url)
                        torrent_req.add_header('User-Agent', 'Folio/1.0')
                        torrent_resp = urllib.request.urlopen(torrent_req, timeout=30)
                        torrent_data = torrent_resp.read()
                        
                        if not torrent_data:
                            raise Exception("Empty response from Prowlarr")
                        
                        print(f"✅ Downloaded torrent file: {len(torrent_data)} bytes", flush=True)
                        
                        # Build multipart/form-data body with unique boundary
                        import uuid
                        boundary = f'----FormBoundary{uuid.uuid4().hex[:16]}'
                        
                        body = (
                            # Torrent file part
                            f'--{boundary}\r\n'.encode() +
                            b'Content-Disposition: form-data; name="torrents"; filename="download.torrent"\r\n' +
                            b'Content-Type: application/x-bittorrent\r\n' +
                            b'\r\n' +
                            torrent_data +
                            # Category part
                            f'\r\n--{boundary}\r\n'.encode() +
                            b'Content-Disposition: form-data; name="category"\r\n' +
                            b'\r\n' +
                            b'ebooks' +
                            # Closing boundary
                            f'\r\n--{boundary}--\r\n'.encode()
                        )
                        
                        add_data = body
                        add_req = urllib.request.Request(add_url, data=add_data, method='POST')
                        add_req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
                        add_req.add_header('Referer', qbt_url)
                        add_req.add_header('Origin', qbt_url)
                        
                    except Exception as e:
                        print(f"❌ Failed to download torrent file: {e}", flush=True)
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        response = json.dumps({
                            'success': False,
                            'error': f'Failed to download torrent from Prowlarr: {str(e)}'
                        })
                        self.wfile.write(response.encode('utf-8'))
                        return

                try:
                    add_resp = opener.open(add_req, timeout=30)
                    add_result = add_resp.read().decode('utf-8').strip()

                    print(f"📥 qBittorrent API response: '{add_result}'", flush=True)

                    # qBittorrent returns "Ok." on success, "Fails." on failure
                    if add_result.lower() == 'ok.':
                        print(f"✅ Successfully added to qBittorrent: {title}", flush=True)

                        # Mark the corresponding book request as actioned
                        mark_request_actioned(title)

                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        response = json.dumps({
                            'success': True,
                            'message': f'Torrent added to qBittorrent: {title}'
                        })
                        self.wfile.write(response.encode('utf-8'))
                    else:
                        # qBittorrent returned an error - "Fails." is generic and could mean:
                        # - Torrent already exists (duplicate)
                        # - Invalid torrent file
                        # - Category doesn't exist
                        # - Disk full or other issues
                        print(f"❌ qBittorrent rejected the torrent: {add_result}", flush=True)
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        
                        if add_result.lower() == 'fails.':
                            error_msg = 'qBittorrent rejected the torrent. This usually means the torrent already exists in qBittorrent, or the torrent file is invalid.'
                        else:
                            error_msg = f'qBittorrent error: {add_result}'
                        
                        response = json.dumps({
                            'success': False,
                            'error': error_msg
                        })
                        self.wfile.write(response.encode('utf-8'))
                    
                except urllib.error.HTTPError as e:
                    error_body = ''
                    try:
                        error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
                    except:
                        error_body = str(e)
                    print(f"❌ qBittorrent add error {e.code}: {error_body}", flush=True)
                    
                    # Provide helpful error messages based on HTTP status code
                    if e.code == 404:
                        error_msg = f'qBittorrent API not found (404). Please check: 1) Web UI is enabled in qBittorrent Preferences > Web UI, 2) QBITTORRENT_URL is correct (currently: {qbt_url})'
                    elif e.code == 403:
                        error_msg = 'qBittorrent rejected the request (403 Forbidden). Check your username/password or authentication settings.'
                    elif e.code == 401:
                        error_msg = 'qBittorrent authentication required (401). Please set QBITTORRENT_USERNAME and QBITTORRENT_PASSWORD.'
                    else:
                        error_msg = f'qBittorrent error ({e.code}): {error_body}'
                    
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': error_msg
                    })
                    self.wfile.write(response.encode('utf-8'))
                    
                except urllib.error.URLError as e:
                    print(f"❌ Cannot connect to qBittorrent: {e.reason}", flush=True)
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': f'Cannot connect to qBittorrent at {qbt_url}. Is it running? Error: {e.reason}'
                    })
                    self.wfile.write(response.encode('utf-8'))
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON decode error: {e}", flush=True)
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Invalid JSON'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                import traceback
                print(f"❌ qBittorrent add error: {e}", flush=True)
                print(f"❌ Traceback: {traceback.format_exc()}", flush=True)
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': str(e)})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Validate qBittorrent connection
        if self.path == '/api/qbittorrent/validate':
            print(f"🔍 qBittorrent validate endpoint hit", flush=True)

            try:
                # Get qBittorrent config from environment
                qbt_url = os.getenv('QBITTORRENT_URL', '').strip().rstrip('/')
                qbt_username = os.getenv('QBITTORRENT_USERNAME', '').strip()
                qbt_password = os.getenv('QBITTORRENT_PASSWORD', '').strip()

                print(f"🔍 qBittorrent config - URL: {qbt_url}, Username: {'***' if qbt_username else '(none)'}, Password: {'***' if qbt_password else '(none)'}", flush=True)

                if not qbt_url:
                    print(f"❌ qBittorrent validation failed: URL not configured", flush=True)
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': 'qBittorrent not configured. Set QBITTORRENT_URL environment variable.',
                        'configured': False
                    })
                    self.wfile.write(response.encode('utf-8'))
                    return

                # Cookie jar for session management
                cookie_jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

                # Try to login (if credentials provided)
                if qbt_username and qbt_password:
                    login_url = f"{qbt_url}/api/v2/auth/login"
                    login_data = urllib.parse.urlencode({
                        'username': qbt_username,
                        'password': qbt_password
                    }).encode('utf-8')

                    try:
                        login_req = urllib.request.Request(login_url, data=login_data, method='POST')
                        login_req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                        login_resp = opener.open(login_req, timeout=10)
                        login_result = login_resp.read().decode('utf-8')

                        if login_result.strip().lower() != 'ok.':
                            print(f"❌ qBittorrent login failed: {login_result}", flush=True)
                            self.send_response(400)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            response = json.dumps({
                                'success': False,
                                'error': f'qBittorrent login failed: {login_result}',
                                'configured': True,
                                'login_failed': True
                            })
                            self.wfile.write(response.encode('utf-8'))
                            return
                        else:
                            print(f"✅ qBittorrent login successful", flush=True)
                    except Exception as e:
                        print(f"❌ qBittorrent login exception: {e}", flush=True)
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        response = json.dumps({
                            'success': False,
                            'error': f'Failed to connect to qBittorrent: {str(e)}',
                            'configured': True,
                            'connection_failed': True
                        })
                        self.wfile.write(response.encode('utf-8'))
                        return

                # Get qBittorrent version/info to verify connection
                try:
                    version_url = f"{qbt_url}/api/v2/app/version"
                    version_req = urllib.request.Request(version_url)
                    version_resp = opener.open(version_req, timeout=10)
                    version = version_resp.read().decode('utf-8').strip()

                    print(f"✅ qBittorrent validation successful - version: {version}", flush=True)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': True,
                        'version': version,
                        'configured': True,
                        'url': qbt_url
                    })
                    self.wfile.write(response.encode('utf-8'))

                except Exception as e:
                    print(f"❌ qBittorrent version check failed: {e}", flush=True)
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': f'Failed to connect to qBittorrent: {str(e)}',
                        'configured': True,
                        'connection_failed': True
                    })
                    self.wfile.write(response.encode('utf-8'))

            except Exception as e:
                import traceback
                print(f"❌ qBittorrent validate error: {e}", flush=True)
                print(f"❌ Traceback: {traceback.format_exc()}", flush=True)
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': str(e)})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Bulk delete books from Calibre library
        if self.path == '/api/books/bulk-delete':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))
                book_ids = data.get('book_ids', [])
                
                if not book_ids or not isinstance(book_ids, list):
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'book_ids array is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                deleted_count = 0
                errors = []

                # Delete each book using calibredb remove
                for book_id in book_ids:
                    try:
                        book_id_int = int(book_id)
                        # Use calibredb remove command
                        result = run_calibredb(['remove', str(book_id_int)])
                        if result['success']:
                            deleted_count += 1
                            print(f"✅ Deleted book {book_id_int} from library")
                        else:
                            errors.append(f"Book {book_id_int}: {result.get('error', 'Unknown error')}")
                    except ValueError:
                        errors.append(f"Invalid book ID: {book_id}")
                    except Exception as e:
                        errors.append(f"Book {book_id}: {str(e)}")

                if deleted_count > 0:
                    # Invalidate cover cache after deleting books
                    cover_cache.invalidate()
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': True,
                        'deleted_count': deleted_count,
                        'errors': errors if errors else None
                    })
                    self.wfile.write(response.encode('utf-8'))
                else:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': 'Failed to delete books',
                        'errors': errors
                    })
                    self.wfile.write(response.encode('utf-8'))

            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Invalid JSON in request body'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': f'Server error: {str(e)}'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Bulk add books to reading list
        if self.path == '/api/reading-list/bulk-add':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))
                book_ids = data.get('book_ids', [])
                
                if not book_ids or not isinstance(book_ids, list):
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'book_ids array is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                added_count = 0
                errors = []

                # Add each book to reading list using direct database access
                for book_id in book_ids:
                    try:
                        book_id_int = int(book_id)
                        if add_to_reading_list(book_id_int):
                            added_count += 1
                        else:
                            errors.append(f"Book {book_id_int}: Failed to add")
                    except ValueError:
                        errors.append(f"Invalid book ID: {book_id}")
                    except Exception as e:
                        errors.append(f"Book {book_id}: {str(e)}")

                # Get updated reading list IDs
                ids = get_reading_list_ids()

                if added_count > 0:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': True,
                        'added_count': added_count,
                        'ids': ids,
                        'errors': errors if errors else None
                    })
                    self.wfile.write(response.encode('utf-8'))
                else:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({
                        'success': False,
                        'error': 'Failed to add books to reading list',
                        'errors': errors
                    })
                    self.wfile.write(response.encode('utf-8'))

            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Invalid JSON in request body'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': f'Server error: {str(e)}'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Add book to reading list (set #reading_list:true)
        if self.path == '/api/reading-list':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))
                book_id = data.get('book_id')

                if book_id is None:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'error': 'book_id is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                try:
                    book_id_int = int(book_id)
                except ValueError:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'error': 'book_id must be an integer'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                # Add to reading list using direct database access
                if add_to_reading_list(book_id_int):
                    ids = get_reading_list_ids()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'ids': ids})
                    self.wfile.write(response.encode('utf-8'))
                else:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'Failed to add book to reading list'})
                    self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_error(400, f"Bad Request: {e}")
            return

        self.send_error(404, "Not Found")

    def do_DELETE(self):
        """Handle DELETE requests"""
        # API: Remove book request
        match = re.match(r'/api/requests/(\d+)', self.path)
        if match:
            book_id = int(match.group(1))

            requested_books = config.get('requested_books', [])
            config['requested_books'] = [b for b in requested_books if b.get('id') != book_id]
            save_config()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'success': True, 'books': config['requested_books']})
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Remove book from reading list
        match = re.match(r'/api/reading-list/(\d+)', self.path)
        if match:
            book_id = int(match.group(1))

            # Remove from reading list using direct database access
            if remove_from_reading_list(book_id):
                ids = get_reading_list_ids()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': True, 'ids': ids})
                self.wfile.write(response.encode('utf-8'))
            else:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': 'Failed to remove book from reading list'})
                self.wfile.write(response.encode('utf-8'))
            return

        self.send_error(404, "Not Found")

    def do_PUT(self):
        """Handle metadata update requests"""
        # Match /api/metadata-and-cover/{book_id}
        match = re.match(r'/api/metadata-and-cover/(\d+)', self.path)
        if not match:
            self.send_error(404, "Not Found")
            return

        book_id = match.group(1)

        # Read request body
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        errors = []

        # Update metadata fields
        metadata_fields = ['title', 'authors', 'publisher', 'comments', 'tags']
        for field in metadata_fields:
            if field in data and data[field]:
                value = data[field]
                if isinstance(value, list):
                    value = ', '.join(value)

                result = run_calibredb(['set_metadata', book_id, '--field', f'{field}:{value}'])
                if not result['success']:
                    errors.append(f'Failed to update {field}: {result.get("error", "Unknown error")}')
                else:
                    print(f"✅ Updated {field} for book {book_id}")
        
        # Handle pubdate (year) separately
        if 'pubdate' in data and data['pubdate']:
            # Format as YYYY-MM-DD for Calibre
            pubdate_value = data['pubdate']
            if isinstance(pubdate_value, int):
                # If it's just a year, format it as YYYY-01-01
                pubdate_value = f"{pubdate_value}-01-01"
            
            result = run_calibredb(['set_metadata', book_id, '--field', f'pubdate:{pubdate_value}'])
            if not result['success']:
                errors.append(f'Failed to update pubdate: {result.get("error", "Unknown error")}')
            else:
                print(f"✅ Updated pubdate for book {book_id}")

        # Update cover if provided (either data URL or remote URL)
        if 'coverData' in data and data['coverData']:
            try:
                cover_data = data['coverData']
                image_data = None
                
                if cover_data.startswith('data:image'):
                    # Base64 encoded image
                    header, encoded = cover_data.split(',', 1)
                    image_data = base64.b64decode(encoded)
                elif cover_data.startswith('http'):
                    # Remote URL - download it
                    with urllib.request.urlopen(cover_data, timeout=10) as img_response:
                        image_data = img_response.read()
                
                if image_data:
                    # Get book path from database
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
                    row = cursor.fetchone()

                    if row:
                        book_path = row['path']
                        library_path = get_calibre_library()
                        cover_path = os.path.join(library_path, book_path, 'cover.jpg')

                        # Write cover file directly to book directory
                        with open(cover_path, 'wb') as f:
                            f.write(image_data)
                            f.flush()  # Force flush to disk
                            os.fsync(f.fileno())  # Ensure written to disk

                        # Update has_cover flag in database
                        cursor.execute("UPDATE books SET has_cover = 1 WHERE id = ?", (book_id,))
                        conn.commit()
                        
                        # Invalidate cover cache so new cover is served immediately
                        cover_cache.invalidate(int(book_id))

                        print(f"✅ Cover updated for book {book_id}")
                    else:
                        errors.append(f'Failed to update cover: Book not found')

                    conn.close()
            except Exception as e:
                errors.append(f'Failed to process cover: {str(e)}')
                print(f"❌ Cover update error: {e}")

        # Send response
        # Treat cover issues as non-fatal: metadata changes should still be considered success
        metadata_errors = [e for e in errors if not e.lower().startswith('failed to update cover')
                           and not e.lower().startswith('failed to process cover')]

        if metadata_errors:
            print(f"❌ Metadata update failed for book {book_id}:")
            for error in metadata_errors:
                print(f"   - {error}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'success': False, 'errors': metadata_errors})
            self.wfile.write(response.encode('utf-8'))
        else:
            if errors:
                print(f"⚠️  Metadata updated with cover warnings for book {book_id}:")
                for error in errors:
                    print(f"   - {error}")
            else:
                print(f"✅ Metadata updated successfully for book {book_id}")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'success': True, 'message': 'Metadata updated successfully'})
            self.wfile.write(response.encode('utf-8'))

    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()


if __name__ == "__main__":
    # Load config on startup
    load_config()

    # Load previously imported files (survives restarts)
    load_imported_files()

    # Pre-load cover cache asynchronously (don't block server startup)
    def preload_cover_cache():
        print("📦 Pre-loading cover cache in background...")
        cover_cache.load_all()
    
    cache_thread = threading.Thread(target=preload_cover_cache, daemon=True)
    cache_thread.start()

    # Start import watcher if configured
    start_import_watcher()

    # Use threaded server to handle concurrent cover image requests
    class ThreadedTCPServer(ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True  # Threads die when main thread exits

    with ThreadedTCPServer(("", PORT), FolioHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{PORT}")
        print(f"📖 Calibre Library: {get_calibre_library()}")
        print(f"🔑 Hardcover API: {'Configured' if config.get('hardcover_token') else 'Not configured'}")
        print(f"🔍 Prowlarr: {'Configured (' + config.get('prowlarr_url', '') + ')' if config.get('prowlarr_url') and config.get('prowlarr_api_key') else 'Not configured'}")
        import_folder = config.get('import_folder', '')
        if import_folder:
            print(f"📂 Import Folder: {import_folder} (interval: {config.get('import_interval', 60)}s, recursive: {config.get('import_recursive', True)}, delete: {config.get('import_delete', False)})")
        else:
            print(f"📂 Import Folder: Not configured")
        print(f"\n   Library APIs:")
        print(f"   /api/books → Book list from metadata.db")
        print(f"   /api/cover/* → Book covers")
        print(f"   /api/download/{{id}}/{{format}} → Download book files")
        print(f"   /api/metadata-and-cover/* → Metadata editing")
        print(f"\n   Hardcover APIs:")
        print(f"   /api/itunes/search?q=query → Search iTunes (for metadata)")
        print(f"   /api/hardcover/trending → Most popular books from 2025")
        print(f"\n   Lists:")
        print(f"   /api/requests → Manage book requests")
        print(f"   /api/reading-list → Manage reading list (library books)")
        print(f"\n   Config:")
        print(f"   /api/config → Configuration")
        print(f"   /api/browse → Directory browser")
        print(f"\n   Import:")
        print(f"   /api/import/status → Import watcher status")
        print(f"   /api/import/scan → Trigger manual import (POST)")
        print(f"\n   📱 E-ink interface: http://localhost:{PORT}/eink.html")
        print(f"   📖 Kobo interface: http://localhost:{PORT}/kobo")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
