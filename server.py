#!/usr/bin/env python3
"""
Local dev server. Serves static files + POST /api/refresh runs fetch_data.py.
Usage: python3 server.py [port]  (default 3000)
"""
import http.server, json, subprocess, sys, urllib.request
from pathlib import Path

PRICELABS_API = 'https://api.pricelabs.co/v1/listings'
PRICELABS_KEY = 'd1z1lA1vbZYsVWaPJ2Kg2iwc8yBtzDGXZnD0cUvc'

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
SERVE_DIR = Path(__file__).parent.resolve()

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        if self.path == '/api/pricelabs':
            try:
                req = urllib.request.Request(PRICELABS_API,
                    headers={'X-API-Key': PRICELABS_KEY,
                             'User-Agent': 'curl/7.88.1',
                             'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                err = json.dumps({'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != '/api/refresh':
            self.send_error(404); return
        try:
            r = subprocess.run([sys.executable, 'fetch_data.py'],
                capture_output=True, text=True, cwd=str(SERVE_DIR), timeout=120)
            body = json.dumps({'ok': r.returncode == 0,
                'error': (r.stderr or r.stdout)[-500:] if r.returncode != 0 else None}).encode()
        except Exception as e:
            body = json.dumps({'ok': False, 'error': str(e)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ('200', '304'):
            super().log_message(fmt, *args)

if __name__ == '__main__':
    with http.server.ThreadingHTTPServer(('', PORT), DashboardHandler) as s:
        print(f'Dashboard at http://localhost:{PORT}  (Ctrl+C to stop)')
        s.serve_forever()
