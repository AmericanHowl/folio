#!/usr/bin/env python3
"""
Folio Server - Serves static files, proxies Calibre API, and handles metadata editing
This solves CORS issues and provides metadata management in a single script
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
from pathlib import Path

PORT = 9099
CALIBRE_URL = "http://localhost:8080"
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


def run_calibredb(args):
    """Execute calibredb command with the library path"""
    library_path = get_calibre_library()
    cmd = ['calibredb'] + args + ['--library-path', library_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {'success': True, 'output': result.stdout}
    except subprocess.CalledProcessError as e:
        return {'success': False, 'error': e.stderr}
    except FileNotFoundError:
        return {'success': False, 'error': 'calibredb command not found. Please install Calibre.'}


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

        # Proxy API requests to Calibre Content Server
        if path.startswith('/api/'):
            calibre_path = path.replace('/api/', '/', 1)
            try:
                req = urllib.request.Request(f"{CALIBRE_URL}{calibre_path}")
                with urllib.request.urlopen(req) as response:
                    self.send_response(response.status)
                    for header, value in response.headers.items():
                        if header.lower() not in ['transfer-encoding', 'connection']:
                            self.send_header(header, value)
                    self.end_headers()
                    self.wfile.write(response.read())
            except Exception as e:
                self.send_error(502, f"Bad Gateway: {e}")
            return

        # Serve static files from public/
        self.directory = "public"
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
        metadata_fields = ['title', 'authors', 'publisher', 'comments']
        for field in metadata_fields:
            if field in data and data[field]:
                value = data[field]
                if isinstance(value, list):
                    value = ', '.join(value)

                result = run_calibredb(['set_metadata', book_id, '--field', f'{field}:{value}'])
                if not result['success']:
                    errors.append(f'Failed to update {field}: {result.get("error", "Unknown error")}')

        # Update cover if provided
        if 'coverData' in data and data['coverData']:
            try:
                cover_data = data['coverData']
                if cover_data.startswith('data:image'):
                    header, encoded = cover_data.split(',', 1)
                    image_data = base64.b64decode(encoded)

                    # Determine file extension from MIME type
                    mime_type = header.split(';')[0].split(':')[1]
                    ext_map = {
                        'image/jpeg': '.jpg',
                        'image/jpg': '.jpg',
                        'image/png': '.png',
                        'image/gif': '.gif'
                    }
                    ext = ext_map.get(mime_type, '.jpg')

                    # Save to temporary file
                    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
                        tmp_file.write(image_data)
                        tmp_path = tmp_file.name

                    # Update cover using calibredb
                    result = run_calibredb(['set_metadata', book_id, '--cover', tmp_path])

                    # Clean up temp file
                    os.unlink(tmp_path)

                    if not result['success']:
                        errors.append(f'Failed to update cover: {result.get("error", "Unknown error")}')
            except Exception as e:
                errors.append(f'Failed to process cover: {str(e)}')

        # Send response
        if errors:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({'success': False, 'errors': errors})
            self.wfile.write(response.encode('utf-8'))
        else:
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
        print(f"📚 Calibre Content Server: {CALIBRE_URL}")
        print(f"📖 Calibre Library: {get_calibre_library()}")
        print(f"\n   /api/* → {CALIBRE_URL}/* (read)")
        print(f"   /api/metadata-and-cover/* → calibredb (write)")
        print(f"   /api/config → Configuration")
        print(f"   /api/browse → Directory browser")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
