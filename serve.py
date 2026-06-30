#!/usr/bin/env python3
"""Serve MonitorMe dashboard with live save + regenerate."""
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).parent
PORT = 7070


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ('/', '/dashboard.html'):
            content = (BASE_DIR / 'dashboard.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != '/save':
            self.send_response(404)
            self.end_headers()
            return

        allowed_origins = {f'http://localhost:{PORT}', f'http://127.0.0.1:{PORT}'}
        origin = self.headers.get('Origin', '')
        if origin and origin not in allowed_origins:
            self.send_response(403)
            self.end_headers()
            return

        ct = self.headers.get('Content-Type', '')
        if 'application/json' not in ct:
            self.send_response(415)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))

        (BASE_DIR / 'data' / 'projects.json').write_text(
            json.dumps(body['projects'], indent=2, ensure_ascii=False), encoding='utf-8')
        (BASE_DIR / 'config.json').write_text(
            json.dumps(body['config'], indent=2, ensure_ascii=False), encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(BASE_DIR / 'generate_dashboard.py')],
            capture_output=True, text=True
        )

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', f'http://localhost:{PORT}')
        self.end_headers()
        self.wfile.write(json.dumps({
            'ok': result.returncode == 0,
            'output': result.stdout or result.stderr,
        }).encode())


if __name__ == '__main__':
    server = HTTPServer(('localhost', PORT), Handler)
    print(f'MonitorMe: http://localhost:{PORT}/')
    print('Ctrl+C to stop')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
