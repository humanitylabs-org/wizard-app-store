"""Sign-in reliability for the ChatGPT and Claude connection apps (shared pool_server/pool_client).

Loopback HTTP only: a stand-in agent dashboard (password login + Wizard OS account broker), a closed port for an
unreachable agent, a fake legacy Claude Code reader. No Hermes, CLI, token or provider access.

Covers the incident on an alongside box whose apps pointed at a stale agent address:
- an unreachable / misconfigured agent is reported as such (code + plain line + agent host:port), never as an empty
  \"not connected\" inventory, and Home's /api/connection says `unreachable` instead of `signed out`;
- on an alongside box Claude never falls back to the original Claude Code page (that login would not reach the
  agent), while the fresh-mode Hermes Agent app (no broker) still does;
- the original Claude Code sign-in and the agent's own row for the same account show as one row.
"""
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

STORE = Path(__file__).parents[1] / 'images'


def load(provider):
    root = STORE / ('wizard-' + provider)
    for name in ('server', 'pool_client', 'inference', 'usage', 'warm_spare'):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location('server', root / 'server.py')
        owner = importlib.util.module_from_spec(spec)
        sys.modules['server'] = owner
        spec.loader.exec_module(owner)
        with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': provider}):
            spec = importlib.util.spec_from_file_location(provider + '_pool', root / 'pool_server.py')
            pool = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pool)
    finally:
        sys.path.remove(str(root))
    return pool


CHATGPT = load('chatgpt')
CLAUDE = load('claude')
MANAGEMENT = {'contract': 'wizard.account-management/1', 'status': 'available'}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Dashboard(http.server.BaseHTTPRequestHandler):
    """Stand-in agent dashboard: password login, then the wizard-os provider-accounts routes."""
    password = 'dash-pass'
    broker = True
    rows = []
    identity = None

    def log_message(self, *args):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        if code == 200 and self.path == '/auth/password-login':
            self.send_header('Set-Cookie', 'session=ok; Path=/')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        size = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(size) or b'{}')
        if self.path == '/auth/password-login':
            return self.reply(200 if body.get('password') == self.password else 401, {})
        return self.reply(404, {})

    def do_GET(self):
        if 'session=ok' not in (self.headers.get('Cookie') or ''):
            return self.reply(401, {})
        provider = self.path.rsplit('/', 1)[-1]
        if not self.broker or not self.path.startswith('/api/plugins/wizard-os/provider-accounts/'):
            return self.reply(404, {'detail': 'Not Found'})
        body = {'owner': 'hermes', 'provider': provider, 'name': provider, 'accounts': list(self.rows),
                'actions': {'add': True}, 'management': dict(MANAGEMENT)}
        if self.identity:
            body['identity'] = dict(self.identity)
        return self.reply(200, body)


class Base(unittest.TestCase):
    pool = CHATGPT
    provider = 'chatgpt'

    def setUp(self):
        Dashboard.password, Dashboard.broker, Dashboard.rows, Dashboard.identity = 'dash-pass', True, [], None
        self.dash = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Dashboard)
        threading.Thread(target=self.dash.serve_forever, daemon=True).start()
        self.app = self.pool.Server(('127.0.0.1', 0), self.pool.Handler)
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.pool.PASSWORD = ''
        self.pool.Hermes.opener = None
        self.env = patch.dict(os.environ, {'WIZARD_%s_HERMES_PASSWORD' % self.provider.upper(): 'dash-pass',
                                           'WIZARD_%s_HERMES_URL' % self.provider.upper(): 'http://127.0.0.1:%d' % self.dash.server_port})
        self.env.start()
        self.models = patch.object(self.pool.owner.inference, 'models', lambda *a: [])
        self.models.start()

    def tearDown(self):
        self.models.stop()
        self.env.stop()
        for s in (self.app, self.dash):
            s.shutdown()
            s.server_close()

    def get(self, path, headers=None):
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (self.app.server_port, path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b'{}')

    def post(self, body):
        req = urllib.request.Request('http://127.0.0.1:%d/api/operations' % self.app.server_port, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Wizard-Account-Action': '1'})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b'{}')


class ChatGPTSignin(Base):
    def test_reachable_agent_lists_its_rows(self):
        Dashboard.rows = [{'id': 'a1', 'email': 'h***@e***', 'status': 'ready', 'usage': {'limits': [{'usedPercent': 5}]},
                           'credentials': [{'id': 'c1', 'managed': True}], 'actions': {'reconnect': True, 'remove': True}}]
        code, out = self.get('/api/accounts')
        self.assertEqual((code, out['management']['status'], len(out['accounts'])), (200, 'available', 1))
        self.assertNotIn('inventoryStatus', out)
        code, conn = self.get('/api/connection')
        self.assertEqual((conn['status'], conn['contract'], len(conn['accounts'])), ('connected', 'wizard.ai-connection/2', 1))

    def test_stale_agent_address_is_reported_not_signed_out(self):
        port = free_port()
        os.environ['WIZARD_CHATGPT_HERMES_URL'] = 'http://127.0.0.1:%d' % port
        code, out = self.get('/api/accounts')
        self.assertEqual(code, 200)
        self.assertEqual((out['inventoryStatus'], out['error']['code']), ('unavailable', 'unreachable'))
        self.assertEqual(out['agent'], '127.0.0.1:%d' % port)
        self.assertIn("Can't reach your agent", out['error']['message'])
        self.assertFalse(out['actions']['add'])
        self.assertIs(out['legacySignin'], False)
        code, conn = self.get('/api/connection')
        # Home must read \"unreachable\" (keeps its last reading), never an explicit empty inventory (\"signed out\").
        self.assertNotIn('accounts', conn)
        self.assertEqual((conn['status'], conn['error']['code']), ('error', 'unreachable'))
        # Starting a sign-in against it fails with the same plain reason, not a fake success.
        code, op = self.post({'action': 'add', 'confirmed': True})
        self.assertEqual(code, 503)

    def test_home_never_shows_hermes_default_labels(self):
        # Hermes labels a Codex sign-in without an email claim `openai-codex-oauth-1`; Home shows the name whenever the
        # email is masked, so /api/connection names such rows by position and keeps an owner's own nickname.
        row = lambda id, name: {'id': id, 'name': name, 'email': 'h***@e***', 'status': 'ready', 'usage': {'limits': []},
                                'credentials': [], 'actions': {'reconnect': True, 'remove': True}}
        Dashboard.rows = [row('a1', 'openai-codex-oauth-1'), row('a2', 'Work'), row('a3', 'openai-codex-oauth-3')]
        conn = self.get('/api/connection')[1]
        self.assertEqual([a['name'] for a in conn['accounts']], ['ChatGPT', 'Work', 'ChatGPT 3'])
        # The page keeps the plugin's rows untouched (it labels by email itself).
        self.assertEqual(self.get('/api/accounts')[1]['accounts'][0]['name'], 'openai-codex-oauth-1')

    def test_wrong_dashboard_password(self):
        Dashboard.password = 'rotated'
        code, out = self.get('/api/accounts')
        self.assertEqual(out['error']['code'], 'login_rejected')
        self.assertNotIn('dash-pass', json.dumps(out))

    def test_not_linked(self):
        del os.environ['WIZARD_CHATGPT_HERMES_PASSWORD']
        self.assertEqual(self.get('/api/accounts')[1]['error']['code'], 'not_configured')

    def test_agent_without_broker(self):
        Dashboard.broker = False
        code, out = self.get('/api/accounts')
        self.assertEqual((out['error']['code'], out['legacySignin']), ('no_broker', False))

    def test_page_explains_device_code_setting_before_the_code(self):
        root = STORE / 'wizard-chatgpt/pool-static'
        js, html = (root / 'app.js').read_text(), (root / 'index.html').read_text()
        self.assertIn('Device code sign-in for Codex', js)
        self.assertLess(html.index('id="code-step"'), html.index('id="signin-step"'), 'copy the code before opening sign-in')
        self.assertIn('id="retry"', html)
        for name in sorted(p.name for p in (STORE / 'wizard-claude/pool-static').iterdir()):
            self.assertEqual((root / name).read_bytes(), (STORE / 'wizard-claude/pool-static' / name).read_bytes(), name)
        self.assertEqual(sorted(p.name for p in root.iterdir()), sorted(p.name for p in (STORE / 'wizard-claude/pool-static').iterdir()))
        for name in ('pool_server.py', 'pool_client.py'):
            self.assertEqual((STORE / 'wizard-chatgpt' / name).read_bytes(), (STORE / 'wizard-claude' / name).read_bytes(), name)


class Legacy:
    def __init__(self, account='heidi@example.com', status='connected'):
        self.account, self.status = account, status

    def read(self):
        return {'status': self.status, 'account': self.account, 'plan': 'Max 5x', 'usage': {'limits': []}, 'error': None}


def agent_row(email, **extra):
    return {'id': 'agent1', 'name': 'Subscription', 'email': email, 'plan': 'Max 5x', 'status': 'ready',
            'usage': {'limits': [{'usedPercent': 12}]}, 'credentials': [{'id': 'c1', 'name': 'Subscription', 'managed': True}],
            'actions': {'reconnect': True, 'remove': True}, **extra}


class ClaudeSignin(Base):
    pool = CLAUDE
    provider = 'claude'

    def setUp(self):
        super().setUp()
        self.legacy = patch.multiple(self.pool, LEGACY=Legacy(), LEGACY_RENEW=None)
        self.legacy.start()

    def tearDown(self):
        self.legacy.stop()
        super().tearDown()

    def ids(self):
        return [a['id'] for a in self.get('/api/accounts')[1]['accounts']]

    def test_same_account_in_agent_and_original_signin_is_one_row(self):
        Dashboard.rows = [agent_row('h***@e***')]          # what the plugin reports for heidi@example.com
        self.assertEqual(self.ids(), ['agent1'])
        out = self.get('/api/accounts')[1]
        self.assertEqual(out['legacyStatus'], 'same-as-agent')
        conn = self.get('/api/connection')[1]
        self.assertEqual((conn['status'], len(conn['accounts'])), ('connected', 1))

    def test_exact_identity_wins_over_mask(self):
        h = self.pool.email_hash('heidi@example.com')
        Dashboard.rows = [agent_row('h***@e***', emailHash=h)]
        self.assertEqual(self.ids(), ['agent1'])
        # Same mask, different account (hank@example.com): both rows stay.
        Dashboard.rows = [agent_row('h***@e***', emailHash=self.pool.email_hash('hank@example.com'))]
        self.assertEqual(self.ids(), ['legacy-claude-code', 'agent1'])

    def test_current_plugin_never_merges_by_mask(self):
        # A plugin that reports email hashes (identity marker, Agent Service #203): an agent row without a hash is an
        # unattested account, so a matching mask alone (heidi@ vs hank@) must not hide the original sign-in.
        Dashboard.identity = {'emailHash': 'sha256-16'}
        Dashboard.rows = [agent_row('h***@e***')]
        self.assertEqual(self.ids(), ['legacy-claude-code', 'agent1'])
        # Same without the marker when another row carries a hash (#196 before #203).
        Dashboard.identity = None
        Dashboard.rows = [agent_row('h***@e***'), {**agent_row('o***@e***', emailHash=self.pool.email_hash('olga@example.com')), 'id': 'agent2'}]
        self.assertEqual(self.ids(), ['legacy-claude-code', 'agent1', 'agent2'])
        # And the exact hash still merges under the marker.
        Dashboard.identity = {'emailHash': 'sha256-16'}
        Dashboard.rows = [agent_row('h***@e***', emailHash=self.pool.email_hash('Heidi@Example.com'))]
        self.assertEqual(self.ids(), ['agent1'])

    def test_claude_home_names(self):
        Dashboard.rows = [agent_row('o***@e***', name='anthropic-oauth-2')]
        conn = self.get('/api/connection')[1]
        self.assertEqual([a['name'] for a in conn['accounts']], ['heidi@example.com', 'Claude 2'])

    def test_different_accounts_stay_separate(self):
        Dashboard.rows = [agent_row('o***@e***')]
        self.assertEqual(self.ids(), ['legacy-claude-code', 'agent1'])

    def test_fresh_mode_masked_match_alone_never_merges(self):
        # Fresh mode: the original sign-in IS the agent's; without exact identity keep both.
        os.environ['WIZARD_CLAUDE_HERMES_URL'] = 'http://hermes-agent:9119'
        with patch.object(self.pool.Hermes, 'accounts', lambda provider: {'owner': 'hermes', 'provider': 'claude', 'accounts': [agent_row('h***@e***')],
                                                                            'actions': {'add': True}, 'management': dict(MANAGEMENT)}):
            self.assertEqual(self.ids(), ['legacy-claude-code', 'agent1'])

    def test_alongside_unreachable_never_offers_the_claude_code_page(self):
        os.environ['WIZARD_CLAUDE_HERMES_URL'] = 'http://127.0.0.1:%d' % free_port()
        out = self.get('/api/accounts')[1]
        self.assertEqual((out['inventoryStatus'], out['legacySignin'], out['alongside']), ('unavailable', False, True))
        conn = self.get('/api/connection')[1]
        self.assertEqual((conn['status'], conn['error']['code']), ('error', 'unreachable'))
        self.assertNotIn('accounts', conn)

    def test_fresh_mode_without_broker_keeps_original_signin(self):
        os.environ['WIZARD_CLAUDE_HERMES_URL'] = 'http://hermes-agent:9119'
        with patch.object(self.pool.Hermes, 'accounts', lambda provider: (_ for _ in ()).throw(self.pool.BridgeError(404, 'no_broker'))):
            out = self.get('/api/accounts')[1]
            self.assertEqual((out['legacySignin'], out['accounts'][0]['id']), (True, 'legacy-claude-code'))
            conn = self.get('/api/connection')[1]
            # The original sign-in is this agent's own login: Home keeps showing it connected.
            self.assertEqual((conn['status'], conn['accounts'][0]['id']), ('connected', 'legacy-claude-code'))


if __name__ == '__main__':
    unittest.main()
