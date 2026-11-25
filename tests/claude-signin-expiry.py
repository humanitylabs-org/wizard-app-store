"""Claude: the original sign-in's own end date (refreshTokenExpiresAt) is shown, warned about and honoured.

humanitylabs-org/claude-connection#26. Loopback only: a temp sign-in folder, a stand-in Anthropic usage server and a
fake Hermes inventory; no CLI and no provider access. Only the date is read; no token value may appear anywhere.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
owner = importlib.util.module_from_spec(spec)
sys.modules['server'] = owner
spec.loader.exec_module(owner)
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}):
    spec = importlib.util.spec_from_file_location('claude_pool', ROOT / 'pool_server.py')
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)
import usage  # noqa: E402

TOKEN, REFRESH = 'sk-ant-oat01-SECRET-ACCESS', 'sk-ant-ort01-SECRET-REFRESH'
DAY = 86400


class Anthropic(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Anthropic.hits.append(self.path)
        body = {'five_hour': {'utilization': 12, 'resets_at': '2030-01-01T00:00:00Z'}} if self.path.endswith('/usage') \
            else {'account': {'email': 'owner@example.com'}, 'organization': {'organization_type': 'claude_max'}}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SigninExpiry(unittest.TestCase):
    def setUp(self):
        self.up = ThreadingHTTPServer(('127.0.0.1', 0), Anthropic)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.addCleanup(self.up.shutdown)
        self.dir = tempfile.mkdtemp()
        reader = usage.ConnectionReader(self.dir, 'http://127.0.0.1:%d/api/oauth/usage' % self.up.server_port, timeout_s=2)

        class FakeHermes:
            @staticmethod
            def accounts(provider):
                return {'owner': 'hermes', 'provider': provider, 'name': 'Claude', 'accounts': [],
                        'actions': {'add': True}, 'management': {'contract': 'wizard.account-management/1', 'status': 'available'}}

            @staticmethod
            def request(provider, suffix, body=None):
                raise AssertionError('no account change expected')

        for p in (patch.object(pool, 'Hermes', FakeHermes), patch.object(pool, 'LEGACY', reader),
                  patch.object(pool, 'LEGACY_RENEW', owner.renew_if_expired), patch.object(pool, 'PASSWORD', ''),
                  patch.object(owner, 'PASSWORD', ''), patch.object(owner, 'CONNECTION', reader),
                  patch.object(owner, 'CLAUDE_DIR', self.dir), patch.object(pool, 'AUTO_ORDER', False),
                  patch.object(owner, 'claude_status', lambda: {'status': 'connected', 'plan': 'Claude Max', 'account': 'owner@example.com'}),
                  patch.object(owner, 'run_test', side_effect=AssertionError('an ended sign-in must not run a renewal turn')),
                  patch.object(owner.inference, 'models', return_value=[])):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
        self.http = pool.Server(('127.0.0.1', 0), pool.Handler)
        threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01}, daemon=True).start()
        self.addCleanup(lambda: (self.http.shutdown(), self.http.server_close()))
        self.base = 'http://127.0.0.1:%d' % self.http.server_port

    def sign_in(self, ends_in_s, refresh_date=True):
        oauth = {'accessToken': TOKEN, 'refreshToken': REFRESH, 'expiresAt': (time.time() + 8 * 3600) * 1000,
                 'subscriptionType': 'max', 'rateLimitTier': 'default_claude_max_20x'}
        if refresh_date:
            oauth['refreshTokenExpiresAt'] = (time.time() + ends_in_s) * 1000
        Path(self.dir, '.credentials.json').write_text(json.dumps({'claudeAiOauth': oauth}))
        Path(self.dir, '.claude.json').write_text(json.dumps({'oauthAccount': {'emailAddress': 'owner@example.com'}}))
        owner.CONNECTION.result = None  # a new sign-in file; the reader's 60 s cache is per token

    def get(self, path, headers=None):
        with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}), timeout=10) as r:
            text = r.read().decode()
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(REFRESH, text)
        return json.loads(text)

    def test_weeks_left_connected_with_date_no_warning(self):
        self.sign_in(20 * DAY + 600)
        conn = self.get('/api/connection')
        self.assertEqual(conn['status'], 'connected')
        self.assertEqual(conn['signin_days_left'], 20)
        self.assertRegex(conn['signin_expires_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
        row = self.get('/api/accounts')['accounts'][0]
        self.assertEqual((row['source'], row['signinDaysLeft']), ('legacy-claude-code', 20))
        self.assertEqual(self.get('/api/inbox'), {'inbox': 1, 'items': []})
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        self.assertEqual((page['status'], page['signin_days_left']), ('connected', 20))

    def test_five_days_left_warns_once_a_day_with_reconnect(self):
        self.sign_in(5 * DAY + 3600)
        self.assertEqual(self.get('/api/connection')['status'], 'connected')
        items = self.get('/api/inbox')['items']
        self.assertEqual(len(items), 1, items)
        item = items[0]
        self.assertEqual(item['title'], 'Claude sign-in ends in 5 days')
        self.assertEqual(item['open'], 'claude-code/?connect=1')
        self.assertEqual(item['time'] % DAY, 0, 'dated to the start of the day: back at most once a day')
        self.assertGreaterEqual(item['priority'], 4)
        later = pool.signin_inbox(time.time() + DAY)['items'][0]
        self.assertEqual(later['key'], item['key'], 'the same thing keeps one key')
        self.assertEqual(later['time'], item['time'] + DAY)
        self.sign_in(6 * DAY + 3600)
        self.assertEqual(self.get('/api/inbox')['items'], [], 'six days left: no warning yet')
        self.sign_in(3 * 3600)
        self.assertEqual(self.get('/api/inbox')['items'][0]['title'], 'Claude sign-in ends in 3 hours')

    def test_past_the_date_expired_not_connected(self):
        self.sign_in(-60)
        Anthropic.hits.clear()
        conn = self.get('/api/connection')
        self.assertEqual(conn['status'], 'expired')
        self.assertEqual(conn['error']['code'], 'signin_ended')
        self.assertEqual(conn['signin_days_left'], 0)
        self.assertFalse([h for h in Anthropic.hits if h.endswith('/usage')], 'an ended sign-in asks Anthropic nothing')
        row = self.get('/api/accounts')['accounts'][0]
        self.assertEqual(row['status'], 'expired')
        self.assertEqual(self.get('/api/inbox')['items'][0]['title'], 'Claude sign-in has ended')
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        self.assertEqual(page['status'], 'expired')
        self.assertIn('Reconnect', page['message'])

    def test_past_the_date_expired_even_when_the_agent_is_unreachable(self):
        self.sign_in(-60)
        with patch.object(pool, 'Hermes', type('Down', (), {'accounts': staticmethod(lambda p: (_ for _ in ()).throw(pool.BridgeError()))})):
            conn = self.get('/api/connection')
        self.assertEqual((conn['status'], conn['error']['code']), ('expired', 'signin_ended'))

    def test_no_date_in_file_behaves_as_before(self):
        self.sign_in(0, refresh_date=False)
        conn = self.get('/api/connection')
        self.assertEqual(conn['status'], 'connected')
        self.assertNotIn('signin_expires_at', conn)
        self.assertEqual(self.get('/api/inbox')['items'], [])

    def test_service_token_ignores_the_file_date(self):
        self.sign_in(-60)
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'x'}):
            conn = self.get('/api/connection')
            self.assertEqual(conn['status'], 'connected')
            self.assertNotIn('signin_expires_at', conn)
            self.assertEqual(self.get('/api/inbox')['items'], [])


if __name__ == '__main__':
    unittest.main()
