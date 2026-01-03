#!/usr/bin/env python3
"""
Folio Server - Serves static files, proxies Calibre API, and handles metadata editing
This solves CORS issues and provides metadata management in a single script
"""
import http.server
import socketserver
import urllib.request
from urllib.parse import urlparse
import json
import subprocess
import os
import base64
import tempfile
import re

PORT = 9099
CALIBRE_URL = "http://localhost:8080"
CALIBRE_LIBRARY = os.getenv('CALIBRE_LIBRARY', os.path.expanduser('~/Calibre Library'))


def run_calibredb(args):
    """Execute calibredb command with the library path"""
    cmd = ['calibredb'] + args + ['--library-path', CALIBRE_LIBRARY]
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


class FolioHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Proxy API requests to Calibre Content Server
        if self.path.startswith('/api/'):
            calibre_path = self.path.replace('/api/', '/', 1)
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
    with socketserver.TCPServer(("", PORT), FolioHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{PORT}")
        print(f"📚 Calibre Content Server: {CALIBRE_URL}")
        print(f"📖 Calibre Library: {CALIBRE_LIBRARY}")
        print(f"\n   /api/* → {CALIBRE_URL}/* (read)")
        print(f"   /api/metadata-and-cover/* → calibredb (write)")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
