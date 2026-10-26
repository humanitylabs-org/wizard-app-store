"""Provider UI and narrow authenticated proxy to the Hermes lifecycle broker."""
import re
import base64
import hmac
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from pool_client import Hermes, BridgeError
import server as owner

PROVIDER = os.environ.get('WIZARD_POOL_PROVIDER', 'chatgpt')
assert PROVIDER in ('chatgpt', 'claude')
PREFIX = 'WIZARD_' + PROVIDER.upper()
ROOT = Path(__file__).parent / 'pool-static'
PASSWORD = os.environ.get(PREFIX + '_PASSWORD', '')
LEGACY = None
LEGACY_RENEW = None
if PROVIDER == 'claude':
    import server as claude_owner
    LEGACY = claude_owner.CONNECTION
    LEGACY_RENEW = claude_owner.renew_if_expired


def with_legacy(result):
    if LEGACY is not None:
        try:
            old = LEGACY.read()
            if LEGACY_RENEW is not None:
                old = LEGACY_RENEW(old, reader=LEGACY)
            if os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'):
                old = {**old, 'status': 'connected', 'error': None}
            if old.get('status') != 'not_connected':
                # Hermes mirrors this same Claude Code login into its pool; show one row, not two.
                mirrors = [a for a in result['accounts'] if a.get('mirror') == 'claude-code']
                result['accounts'] = [a for a in result['accounts'] if a.get('mirror') != 'claude-code']
                # The original sign-in is the first account; added subscriptions follow it.
                result['accounts'].insert(0, {'id': 'legacy-claude-code', 'name': old.get('account') or 'Claude',
                    'source': 'legacy-claude-code', 'email': old.get('account'), 'plan': old.get('plan'),
                    'status': old['status'], 'usage': old.get('usage'), 'error': old.get('error'),
                    'credentials': [c for m in mirrors for c in m.get('credentials') or []],
                    'actions': {'reconnect': False, 'remove': False}})
            result['legacyStatus'] = old.get('status', 'unknown')
        except Exception:
            result['legacyStatus'] = 'unavailable'
        result['accountCount'] = len(result['accounts'])
    return result

def connection(result):
    """An inventory row is not evidence of a usable subscription."""
    rows = result['accounts']
    selected = next((row for status in ('connected', 'ready', 'renewing', 'expired', 'cooldown', 'exhausted', 'error', 'not_connected')
                     for row in rows if row.get('status') == status), {})
    status = selected.get('status', 'error' if rows or result.get('inventoryStatus') == 'unavailable' else 'not_connected')
    if status == 'ready':
        status = 'connected'
    error = selected.get('error') or result.get('error')
    if status in ('cooldown', 'exhausted'):
        status = 'error'
        error = {'code': 'limit', 'message': 'Subscription limit reached; wait for its reset.'}
    elif status == 'error' and not isinstance(error, dict):
        error = {'code': 'provider_error', 'message': 'Subscription state is unavailable.'}
    elif status == 'expired' and not isinstance(error, dict):
        error = {'code': 'expired', 'message': 'Subscription sign-in expired; reconnect it in the app.'}
    answer = {**result, 'contract': 'wizard.ai-connection/2', 'status': status,
              'plan': selected.get('plan'), 'usage': selected.get('usage'),
              'account': selected.get('email') or selected.get('account'), 'error': error}
    try:
        answer['models'] = owner.inference.models(owner.Hermes) if PROVIDER == 'chatgpt' else owner.inference.models()
    except (owner.inference.Fault, getattr(owner, 'HermesError', owner.inference.Fault)) as error:
        answer['models'] = []
        answer['models_error'] = {'code': error.code, 'message': str(error)}
    return answer


class Handler(owner.Handler):
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
        if origins == ["'self'"]:
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def authorized(self):
        if urlsplit(self.path).path == '/api/connection' and self.headers.get('X-Wizard-Grant'):
            return super().authorized('/api/connection')
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
            return self.send(200, {'status': 'ok', 'version': owner.VERSION})
        if not self.authorized():
            return
        if path == '/.well-known/mcp/server-cards.json':
            card = owner.card(self.headers.get('Host', ''))
            card['x-wizard']['credential_owner'] = 'hermes (legacy Claude Code volume read-only inventory)'
            return self.send(200, card)
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
                if LEGACY is None and path != '/api/connection':
                    return self.send(503, {'error': 'Hermes inventory unavailable; existing subscriptions are unchanged.'})
                result = with_legacy({'provider': PROVIDER, 'name': 'Claude' if PROVIDER == 'claude' else 'ChatGPT', 'owner': 'hermes', 'accounts': [],
                    'inventoryStatus': 'unavailable', 'actions': {'add': False}, 'management': {'status': 'unavailable'},
                    'error': {'code': 'unreachable', 'message': 'Agent account inventory unavailable.'}})
            if path == '/api/connection':
                result = connection(result)
            return self.send(200, result)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8'), '/boot.js': ('boot.js', 'text/javascript; charset=utf-8'), '/theme-client.js': ('theme-client.js', 'text/javascript; charset=utf-8'), '/wizard-ui.css': ('wizard-ui.css', 'text/css; charset=utf-8')}
        if path in assets:
            name, ctype = assets[path]
            return self.send(200, (ROOT / name).read_bytes(), ctype)
        return self.send(404, {'error': 'not found'})

    def do_POST(self):
        if urlsplit(self.path).path == '/api/infer':
            # Preserve main's router grants, isolated providers and SSE contract.
            return owner.Handler.do_POST(self)
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
            inventory = Hermes.accounts(PROVIDER)
            management = inventory.get('management') or {}
            if management.get('contract') != 'wizard.account-management/1' or management.get('status') != 'available':
                return self.send(403, {'error': 'Account changes unavailable; subscriptions are unchanged'})
            action = body.get('action')
            if action == 'add':
                permitted = (inventory.get('actions') or {}).get('add') is True
            elif action in ('reconnect', 'remove'):
                permitted = any((row.get('actions') or {}).get(action) is True and
                    any(c.get('id') == body.get('target') and c.get('managed') is True for c in row.get('credentials', []))
                    for row in inventory.get('accounts', []))
            else:
                permitted = action in ('submit', 'cancel')
            if not permitted:
                return self.send(403, {'error': 'Account action unsupported'})
            return self.send(200, Hermes.request(PROVIDER, '/operations', body))
        except Exception:
            return self.send(503, {'error': 'Operation unavailable; refresh inventory before retrying'})

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def server_bind(self):
        # HTTPServer's reverse-DNS lookup can stall an isolated container startup.
        from socketserver import TCPServer
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


if __name__ == '__main__':
    import signal
    import threading
    http = Server((os.environ.get('WIZARD_POOL_BIND', owner.BIND), int(os.environ.get('WIZARD_POOL_PORT', owner.PORT))), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=http.shutdown, daemon=True).start())
    try:
        http.serve_forever()
    finally:
        http.server_close()
        if PROVIDER == 'claude':
            owner.inference.FAST_SPARE.close()
