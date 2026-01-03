#!/usr/bin/env python3
"""
Simple server that serves static files and proxies Calibre API
This solves CORS issues by making everything same-origin
"""
import http.server
import socketserver
import urllib.request
from urllib.parse import urlparse

PORT = 9099
CALIBRE_URL = "http://localhost:8080"


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Proxy API requests to Calibre
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

    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"🚀 Folio server running at http://localhost:{PORT}")
        print(f"📚 Proxying Calibre API from {CALIBRE_URL}")
        print(f"   /api/* → {CALIBRE_URL}/*")
        print("\nPress Ctrl+C to stop")
        httpd.serve_forever()
