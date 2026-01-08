#!/usr/bin/env python3
"""
Folio Server - Serves static files and manages Calibre library via direct DB access
No Calibre Content Server needed - reads directly from metadata.db
"""
import http.server
import socketserver
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

PORT = 9099
CONFIG_FILE = "config.json"
HARDCOVER_API_URL = "https://api.hardcover.app/v1/graphql"

# Global config
config = {
    'calibre_library': os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library')),
    'calibredb_path': os.getenv('CALIBREDB_PATH', ''),  # Auto-detected if empty
    'hardcover_token': os.getenv('HARDCOVER_TOKEN', ''),
    'prowlarr_url': os.getenv('PROWLARR_URL', ''),
    'prowlarr_api_key': os.getenv('PROWLARR_API_KEY', ''),
    'requested_books': []  # Store requested book IDs with timestamps
}


def load_config():
    """Load configuration from file, merging with environment variables.

    Environment variables take precedence over file values when set.
    This allows Docker deployments to override config via env vars.
    """
    global config

    # Start with environment variable defaults
    env_config = {
        'calibre_library': os.getenv('CALIBRE_LIBRARY', ''),
        'calibredb_path': os.getenv('CALIBREDB_PATH', ''),
        'hardcover_token': os.getenv('HARDCOVER_TOKEN', ''),
        'prowlarr_url': os.getenv('PROWLARR_URL', ''),
        'prowlarr_api_key': os.getenv('PROWLARR_API_KEY', ''),
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


def get_calibre_library():
    """Get the current Calibre library path"""
    return config.get('calibre_library', os.path.expanduser('~/Calibre Library'))


def get_db_connection():
    """Get a connection to the Calibre metadata database"""
    library_path = get_calibre_library()
    db_path = os.path.join(library_path, 'metadata.db')

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Calibre database not found at {db_path}")

    conn = sqlite3.connect(db_path)
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


def get_books(limit=50, offset=0, search=None):
    """Get books from the Calibre database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

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

        query += " GROUP BY b.id ORDER BY b.sort LIMIT ? OFFSET ?"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        books = []
        for row in rows:
            # Get formats
            cursor.execute(
                "SELECT format, name FROM data WHERE book = ?",
                (row['id'],)
            )
            formats = [f['format'].upper() for f in cursor.fetchall()]

            # Parse authors - handle various separators and formats, and deduplicate
            # Calibre stores authors as "LastName, FirstName" - convert to "FirstName LastName"
            authors_list = []
            seen_authors = set()  # Use set for O(1) lookup
            
            if row['authors']:
                authors_str = str(row['authors']).strip()
                if authors_str:
                    # Split by common separators: ' & ', '|', ', and ', ' and '
                    # First normalize separators
                    authors_str = authors_str.replace('|', ' & ').replace(', and ', ' & ').replace(' and ', ' & ')
                    
                    # Split by ' & ' (multiple authors)
                    for author in authors_str.split(' & '):
                        author = author.strip()
                        if not author:
                            continue
                            
                        # Convert "LastName, FirstName" to "FirstName LastName"
                        # Handle both ", " and "," separators
                        if ', ' in author:
                            parts = author.split(', ', 1)
                            if len(parts) == 2:
                                last_name = parts[0].strip()
                                first_name = parts[1].strip()
                                if first_name and last_name:
                                    author = f"{first_name} {last_name}"
                        elif author.count(',') == 1 and not author.startswith(','):
                            # Handle "LastName,FirstName" (no space)
                            parts = author.split(',', 1)
                            if len(parts) == 2:
                                last_name = parts[0].strip()
                                first_name = parts[1].strip()
                                if first_name and last_name:
                                    author = f"{first_name} {last_name}"
                        
                        # Normalize and deduplicate
                        author_normalized = author.strip()
                        if author_normalized and author_normalized.lower() not in seen_authors:
                            seen_authors.add(author_normalized.lower())
                            authors_list.append(author_normalized)
            
            book = {
                'id': row['id'],
                'title': row['title'],
                'authors': authors_list,
                'tags': [t.strip() for t in row['tags'].split(',')] if row['tags'] else [],
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
    """Get the cover image for a book"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT path, has_cover FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or not row['has_cover']:
            return None

        library_path = get_calibre_library()
        cover_path = os.path.join(library_path, row['path'], 'cover.jpg')

        if os.path.exists(cover_path):
            with open(cover_path, 'rb') as f:
                return f.read()

        return None
    except Exception as e:
        print(f"❌ Error loading cover: {e}")
        return None


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


def run_calibredb(args):
    """Execute calibredb command with the library path"""
    library_path = get_calibre_library()
    calibredb_path = find_calibredb()
    
    if not calibredb_path:
        error_msg = 'calibredb not found. Please install Calibre or set CALIBREDB_PATH environment variable.'
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}
    
    cmd = [calibredb_path] + args + ['--library-path', library_path]
    print(f"🔧 Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {'success': True, 'output': result.stdout}
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        print(f"❌ calibredb error: {error_msg}")
        return {'success': False, 'error': error_msg}
    except FileNotFoundError:
        error_msg = f'calibredb not found at {calibredb_path}. Please install Calibre.'
        print(f"❌ {error_msg}")
        return {'success': False, 'error': error_msg}


def get_reading_list_ids():
    """
    Get IDs of books on the reading list using Calibre custom column #reading_list.
    Expects a Yes/No custom column with lookup name 'reading_list' configured in Calibre.
    """
    result = run_calibredb(['list', '--fields', 'id', '--search', '#reading_list:true'])
    if not result['success']:
        return []

    ids = []
    for line in result['output'].splitlines():
        line = line.strip()
        if not line or line.lower().startswith('id'):
            continue
        try:
            # calibredb list with --fields id prints just the id per line
            book_id = int(line.split()[0])
            ids.append(book_id)
        except ValueError:
            continue
    return ids

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
    """Search iTunes API for books"""
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
            return {'books': transformed}

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


def get_trending_hardcover(token, limit=20):
    """Get most popular books from 2025 on Hardcover"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

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
            return {'books': books}

    except Exception as e:
        print(f"❌ Hardcover trending error: {e}")
        return {'error': str(e)}


def get_recent_releases_hardcover(token, limit=20):
    """Get recent book releases from Hardcover - matches /upcoming/recent page"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

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
            return {'books': books}

    except Exception as e:
        print(f"❌ Hardcover recent releases error: {e}")
        return {'error': str(e)}


def get_hardcover_popular_lists(token):
    """Get popular lists from Hardcover - first 30, then pick 3 random"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

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
    """Get books from a specific Hardcover list by ID"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

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
            return {
                'books': books,
                'list_name': list_data.get('name', ''),
                'list_description': list_data.get('description', '')
            }

    except Exception as e:
        print(f"❌ Hardcover list error: {e}")
        return {'error': str(e)}


def get_books_by_author_hardcover(token, author_name, limit=20):
    """Get books by a specific author from Hardcover"""
    if not token:
        return {'error': 'No Hardcover API token configured'}

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

            return {
                'books': books,
                'author_name': author_name
            }

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
        # API: Get config
        if path == '/api/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Don't expose the full tokens, just whether they're set
            safe_config = {
                **config,
                'calibredb_path': config.get('calibredb_path', ''),
                'hardcover_token': bool(config.get('hardcover_token')),
                'prowlarr_url': config.get('prowlarr_url', ''),
                'prowlarr_api_key': bool(config.get('prowlarr_api_key'))
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
                search_url = f"{prowlarr_url}/api/v1/search?query={urllib.parse.quote(search_query)}"
                req = urllib.request.Request(search_url)
                req.add_header('X-Api-Key', prowlarr_api_key)
                
                with urllib.request.urlopen(req) as response:
                    results = json.loads(response.read().decode('utf-8'))
                    
                    # Transform results to a simpler format
                    formatted_results = []
                    for item in results:
                        formatted_results.append({
                            'title': item.get('title', 'Unknown'),
                            'author': item.get('author', 'Unknown'),
                            'indexer': item.get('indexer', 'Unknown'),
                            'size': item.get('size', 0),
                            'seeders': item.get('seeders', 0),
                            'leechers': item.get('leechers', 0),
                            'downloadUrl': item.get('downloadUrl', ''),
                            'guid': item.get('guid', ''),
                            'publishDate': item.get('publishDate', ''),
                            'categories': item.get('categories', [])
                        })
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'results': formatted_results})
                    self.wfile.write(response.encode('utf-8'))
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
                response = json.dumps({'error': f'Prowlarr API error: {error_body}'})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'error': f'Failed to search Prowlarr: {str(e)}'})
                self.wfile.write(response.encode('utf-8'))
            return

        # API: Get requested books
        if path == '/api/requests':
            requested_books = config.get('requested_books', [])
            # Ensure all books have a requested_at timestamp (set to today if missing)
            current_timestamp = int(time.time())
            for book in requested_books:
                if 'requested_at' not in book or not book.get('requested_at'):
                    book['requested_at'] = current_timestamp
            # Save updated books back to config
            if any('requested_at' not in book or not book.get('requested_at') for book in requested_books):
                config['requested_books'] = requested_books
                save_config()
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'books': requested_books})
            self.wfile.write(response.encode('utf-8'))
            return

        # API: Get reading list (IDs of library books)
        if path == '/api/reading-list':
            try:
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
                authors = [row['name'] for row in cursor.fetchall()]
                conn.close()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps(authors)
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

            books = get_books(limit=limit, offset=offset, search=search)

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
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(cover_data)
            else:
                self.send_error(404, "Cover not found")
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

                if not os.path.exists(book_file_path):
                    self.send_error(404, f"Book file not found at {book_file_path}")
                    return

                # Determine MIME type based on format
                mime_types = {
                    'EPUB': 'application/epub+zip',
                    'PDF': 'application/pdf',
                    'MOBI': 'application/x-mobipocket-ebook',
                    'AZW3': 'application/vnd.amazon.ebook',
                    'TXT': 'text/plain',
                }
                mime_type = mime_types.get(format, 'application/octet-stream')

                # Send the file
                with open(book_file_path, 'rb') as f:
                    book_data = f.read()

                self.send_response(200)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Disposition', f'attachment; filename="{row["title"]}.{format.lower()}"')
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
        # API: Update config
        if self.path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))

                # Update config
                if 'calibre_library' in data:
                    config['calibre_library'] = os.path.expanduser(data['calibre_library'])
                if 'calibredb_path' in data:
                    config['calibredb_path'] = data['calibredb_path'].strip()
                if 'hardcover_token' in data:
                    config['hardcover_token'] = data['hardcover_token']
                if 'prowlarr_url' in data:
                    config['prowlarr_url'] = data['prowlarr_url']
                if 'prowlarr_api_key' in data:
                    config['prowlarr_api_key'] = data['prowlarr_api_key']

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

        # API: Download from Prowlarr (send to bittorrent client)
        if self.path == '/api/prowlarr/download':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body.decode('utf-8'))
                guid = data.get('guid')
                
                if not guid:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'GUID is required'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                prowlarr_url = config.get('prowlarr_url', '').rstrip('/')
                prowlarr_api_key = config.get('prowlarr_api_key', '')
                
                if not prowlarr_url or not prowlarr_api_key:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': 'Prowlarr not configured'})
                    self.wfile.write(response.encode('utf-8'))
                    return

                try:
                    # Prowlarr command endpoint to send download to bittorrent client
                    # The DownloadRelease command requires guid parameter
                    command_url = f"{prowlarr_url}/api/v1/command"
                    command_payload = json.dumps({
                        'name': 'DownloadRelease',
                        'guid': guid
                    }).encode('utf-8')
                    
                    req = urllib.request.Request(command_url, data=command_payload, method='POST')
                    req.add_header('Content-Type', 'application/json')
                    req.add_header('X-Api-Key', prowlarr_api_key)
                    
                    with urllib.request.urlopen(req) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        
                        # Check if command was successful
                        if response.status == 201 or response.status == 200:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            response = json.dumps({
                                'success': True,
                                'message': 'Download sent to bittorrent client successfully'
                            })
                            self.wfile.write(response.encode('utf-8'))
                            print(f"✅ Sent download to Prowlarr: {data.get('title', guid)}")
                        else:
                            error_msg = result.get('message', 'Unknown error')
                            self.send_response(500)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            response = json.dumps({'success': False, 'error': f'Prowlarr error: {error_msg}'})
                            self.wfile.write(response.encode('utf-8'))
                            
                except urllib.error.HTTPError as e:
                    error_body = ''
                    try:
                        error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
                        error_data = json.loads(error_body) if error_body else {}
                        error_msg = error_data.get('message') or error_data.get('error') or error_body or str(e)
                    except:
                        error_msg = error_body or str(e)
                    
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': f'Prowlarr API error: {error_msg}'})
                    self.wfile.write(response.encode('utf-8'))
                    print(f"❌ Prowlarr download error: {error_msg}")
                    
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': False, 'error': f'Failed to send download: {str(e)}'})
                    self.wfile.write(response.encode('utf-8'))
                    print(f"❌ Download error: {e}")
                    
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

                # Add each book to reading list using calibredb set_metadata
                for book_id in book_ids:
                    try:
                        book_id_int = int(book_id)
                        # Set custom column #reading_list:true via calibredb
                        result = run_calibredb(['set_metadata', str(book_id_int), '--field', '#reading_list:true'])
                        if result['success']:
                            added_count += 1
                            print(f"✅ Added book {book_id_int} to reading list")
                        else:
                            errors.append(f"Book {book_id_int}: {result.get('error', 'Unknown error')}")
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

                # Set custom column #reading_list:true via calibredb
                result = run_calibredb(['set_metadata', str(book_id_int), '--field', '#reading_list:true'])
                if result['success']:
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
                    response = json.dumps({'success': False, 'error': result.get('error', 'Unknown error')})
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

        # API: Remove book from reading list (set #reading_list:false)
        match = re.match(r'/api/reading-list/(\d+)', self.path)
        if match:
            book_id = int(match.group(1))

            result = run_calibredb(['set_metadata', str(book_id), '--field', '#reading_list:false'])
            if result['success']:
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
                response = json.dumps({'success': False, 'error': result.get('error', 'Unknown error')})
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

                        # Update has_cover flag in database
                        cursor.execute("UPDATE books SET has_cover = 1 WHERE id = ?", (book_id,))
                        conn.commit()

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

    with socketserver.TCPServer(("", PORT), FolioHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{PORT}")
        print(f"📖 Calibre Library: {get_calibre_library()}")
        print(f"🔑 Hardcover API: {'Configured' if config.get('hardcover_token') else 'Not configured'}")
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
        print(f"\n   📱 E-ink interface: http://localhost:{PORT}/eink.html")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
