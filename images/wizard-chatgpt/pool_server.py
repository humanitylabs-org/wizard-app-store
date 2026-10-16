"""Candidate provider view. No credential volume and no provider login process.
Lifecycle controls deliberately fail closed until stock account-scoped OAuth exists.
"""
import base64
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from pool_client import Hermes

PROVIDER = os.environ.get('WIZARD_POOL_PROVIDER', 'chatgpt')
assert PROVIDER in ('chatgpt', 'claude')
PREFIX = 'WIZARD_' + PROVIDER.upper()
ROOT = Path(__file__).parent / 'pool-static'
PASSWORD = os.environ.get(PREFIX + '_PASSWORD', '')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, data, ctype='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        origins = ["'self'"]
        for origin in os.environ.get('WIZARD_TRUSTED_ORIGINS', '').split(','):
            origin = origin.strip().rstrip('/')
            parsed = urlsplit(origin)
            if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.path and not parsed.query and not parsed.fragment and not parsed.username:
                origins.append(origin)
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors " + ' '.join(origins) + "; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not PASSWORD:
            return True
        try:
            scheme, value = self.headers.get('Authorization', '').split(' ', 1)
            given = base64.b64decode(value).decode().partition(':')[2]
            if scheme == 'Basic' and hmac.compare_digest(given.encode(), PASSWORD.encode()):
                return True
        except (ValueError, UnicodeError):
            pass
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Subscriptions"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send(200, {'status': 'ok', 'candidate': True})
        if not self.authorized():
            return
        if path in ('/api/accounts', '/api/connection'):
            if path == '/api/connection' and any(k.lower() in ('tailscale-user-login', 'x-forwarded-for', 'forwarded', 'x-real-ip') or k.lower().startswith('cf-') for k in self.headers):
                return self.send(403, {'error': 'box-only'})
            try:
                result = Hermes.accounts(PROVIDER)
            except Exception:
                return self.send(503, {'error': 'Hermes inventory unavailable; existing subscriptions are unchanged.'})
            if path == '/api/connection':
                result = {**result, 'contract': 'wizard.ai-connection/1', 'status': 'connected' if result['accounts'] else 'not_connected', 'plan': None, 'usage': None, 'account': None}
            return self.send(200, result)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8')}
        if path in assets:
            name, ctype = assets[path]
            return self.send(200, (ROOT / name).read_bytes(), ctype)
        return self.send(404, {'error': 'not found'})

    def do_POST(self):
        if not self.authorized():
            return
        self.send(409, {'ok': False, 'message': 'Account-scoped lifecycle requires Hermes. No subscriptions were changed.'})

if __name__ == '__main__':
    ThreadingHTTPServer((os.environ.get('WIZARD_POOL_BIND', '127.0.0.1'), int(os.environ.get('WIZARD_POOL_PORT', '18801'))), Handler).serve_forever()
