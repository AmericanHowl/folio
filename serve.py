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

PORT = 9099
CONFIG_FILE = "config.json"

# Global config
config = {
    'calibre_library': os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library'))
}


def load_config():
    """Load configuration from file"""
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}")
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

            book = {
                'id': row['id'],
                'title': row['title'],
                'authors': row['authors'].split(' & ') if row['authors'] else [],
                'tags': row['tags'].split(', ') if row['tags'] else [],
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


def run_calibredb(args):
    """Execute calibredb command with the library path"""
    library_path = get_calibre_library()
    calibredb_path = '/Applications/calibre.app/Contents/MacOS/calibredb'
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
            response = json.dumps(config)
            self.wfile.write(response.encode('utf-8'))
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

                # Save to file
                if save_config():
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'config': config})
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
        metadata_fields = ['title', 'authors', 'publisher', 'comments', 'tags', 'pubdate']
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

        # Update cover if provided
        if 'coverData' in data and data['coverData']:
            try:
                cover_data = data['coverData']
                if cover_data.startswith('data:image'):
                    header, encoded = cover_data.split(',', 1)
                    image_data = base64.b64decode(encoded)

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

        # Send response
        if errors:
            print(f"❌ Metadata update failed for book {book_id}:")
            for error in errors:
                print(f"   - {error}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'success': False, 'errors': errors})
            self.wfile.write(response.encode('utf-8'))
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
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()


if __name__ == "__main__":
    # Load config on startup
    load_config()

    with socketserver.TCPServer(("", PORT), FolioHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{PORT}")
        print(f"📖 Calibre Library: {get_calibre_library()}")
        print(f"\n   /api/books → Book list from metadata.db")
        print(f"   /api/cover/* → Book covers")
        print(f"   /api/download/{id}/{format} → Download book files")
        print(f"   /api/metadata-and-cover/* → Metadata editing")
        print(f"   /api/config → Configuration")
        print(f"   /api/browse → Directory browser")
        print(f"\n   📱 E-ink interface: http://localhost:{PORT}/eink.html")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
