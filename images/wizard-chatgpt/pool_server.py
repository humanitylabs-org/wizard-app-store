"""Provider UI and narrow authenticated proxy to the Hermes lifecycle broker."""
import re
import base64
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from pool_client import Hermes, BridgeError

PROVIDER = os.environ.get('WIZARD_POOL_PROVIDER', 'chatgpt')
assert PROVIDER in ('chatgpt', 'claude')
PREFIX = 'WIZARD_' + PROVIDER.upper()
ROOT = Path(__file__).parent / 'pool-static'
PASSWORD = os.environ.get(PREFIX + '_PASSWORD', '')
LEGACY = None
if PROVIDER == 'claude':
    import usage
    LEGACY = usage.ConnectionReader(os.environ.get('WIZARD_CLAUDE_CLAUDE_DIR', '/claude'), usage.USAGE_URL)


def with_legacy(result):
    if LEGACY is not None:
        try:
            old = LEGACY.read()  # read-only usage reader, never renew_if_expired/login
            if old.get('status') != 'not_connected':
                result['accounts'].append({'id': 'legacy-claude-code', 'name': 'Legacy Claude Code source',
                    'source': 'legacy-claude-code', 'email': None, 'plan': old.get('plan'),
                    'status': old['status'], 'usage': old.get('usage'), 'credentials': [],
                    'actions': {'reconnect': False, 'remove': False}})
            result['legacyStatus'] = old.get('status', 'unknown')
        except Exception:
            result['legacyStatus'] = 'unavailable'
        result['accountCount'] = len(result['accounts'])
    return result

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(60)

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
        if path == '/.well-known/mcp/server-cards.json':
            base = 'http://wizard-' + PROVIDER + ':' + ('8799' if PROVIDER == 'claude' else '8801')
            return self.send(200, {'name': 'wizard-' + PROVIDER, 'version': '0.2.0', 'title': PROVIDER.title(),
                'remotes': [], 'x-wizard': {'kind': 'system-agent-app', 'provides': ['ai-connection', PROVIDER + '-subscription'],
                'contract': 'wizard.ai-connection/1', 'skill': base + '/SKILL.md', 'connection_api': base + '/api/connection',
                'credential_owner': 'hermes', 'secrets_exposed': False}})
        if path == '/SKILL.md':
            return self.send(200, (ROOT.parent / 'SKILL.md').read_bytes(), 'text/markdown; charset=utf-8')
        if re.fullmatch(r'/api/operations/[A-Za-z0-9_-]{20,64}', path):
            if not PASSWORD:
                return self.send(503, {'error': 'Configure app password before account management'})
            try:
                return self.send(200, Hermes.request(PROVIDER, '/operations/' + path.rsplit('/', 1)[1]))
            except BridgeError as error:
                return self.send(error.status, {'error': 'Operation status unavailable; check inventory'})
            except Exception:
                return self.send(503, {'error': 'Operation status unavailable; do not restart the operation'})
        if path in ('/api/accounts', '/api/connection'):
            if path == '/api/connection' and any(k.lower() in ('tailscale-user-login', 'x-forwarded-for', 'forwarded', 'x-real-ip') or k.lower().startswith('cf-') for k in self.headers):
                return self.send(403, {'error': 'box-only'})
            try:
                result = with_legacy(Hermes.accounts(PROVIDER))
            except Exception:
                if LEGACY is None:
                    return self.send(503, {'error': 'Hermes inventory unavailable; existing subscriptions are unchanged.'})
                result = with_legacy({'provider': PROVIDER, 'name': 'Claude', 'owner': 'hermes', 'accounts': [],
                    'inventoryStatus': 'unavailable', 'error': 'Hermes inventory unavailable; legacy source shown separately'})
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
        if not PASSWORD:
            return self.send(503, {'error': 'Configure app password before account management'})
        if urlsplit(self.path).path != '/api/operations':
            return self.send(404, {'error': 'not found'})
        if self.headers.get('X-Wizard-Account-Action') != '1' or self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': 'Cross-site action rejected'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                return self.send(413, {'error': 'Request too large'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or set(body) - {'action', 'target', 'label', 'confirmed', 'operation', 'code'}:
                return self.send(400, {'error': 'Invalid request'})
            return self.send(200, Hermes.request(PROVIDER, '/operations', body))
        except Exception:
            return self.send(503, {'error': 'Operation unavailable; refresh inventory before retrying'})

class Server(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's reverse-DNS lookup can stall an isolated container startup.
        from socketserver import TCPServer
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


if __name__ == '__main__':
    Server((os.environ.get('WIZARD_POOL_BIND', '127.0.0.1'), int(os.environ.get('WIZARD_POOL_PORT', '18801'))), Handler).serve_forever()
