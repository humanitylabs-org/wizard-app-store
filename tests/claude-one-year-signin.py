"""Claude: the one-year sign-in (Claude Code setup-token) behind the `one-year-signin` switch.

humanitylabs-org/claude-connection#27. Loopback only: a temp shared login folder, a stand-in Claude Code CLI that
behaves like the real one's sign-in screens (checked against Claude Code 2.1.296: link, "Paste code here if prompted",
the one-year credential on screen after a good code, "OAuth error ... Press Enter to retry" after a bad one, and no
exit in either case), a stand-in Anthropic usage server and a fake Hermes inventory. No provider access.
The one-year credential must never appear in any answer, and with the switch off nothing may change.
"""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
STATE = tempfile.mkdtemp()
os.environ['WIZARD_SWITCHES_DIR'] = STATE  # before the modules load: the switch state lives here
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
owner = importlib.util.module_from_spec(spec)
sys.modules['server'] = owner
spec.loader.exec_module(owner)
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}):
    spec = importlib.util.spec_from_file_location('claude_pool', ROOT / 'pool_server.py')
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)
import one_year  # noqa: E402
import usage  # noqa: E402

YEAR_CREDENTIAL = 'sk-ant-oat01-' + 'Q' * 93 + 'AA'
TOKEN, REFRESH = 'sk-ant...CESS', 'sk-ant...RESH'
DAY = 86400
OWNER = {'Host': 'wizard.example.com', 'Origin': 'https://wizard.example.com', 'Tailscale-User-Login': 'owner@example.com',
         'X-Wizard-Switch': '1'}

# The stand-in CLI: records its arguments, and draws the sign-in screens the way the real full-screen UI does
# (cursor-forward instead of spaces, the code masked, no exit after the result).
FAKE = textwrap.dedent('''\
    #!@PY@
    import json, os, sys, time
    argv = sys.argv[1:]
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.log"), "a") as f:
        f.write(json.dumps({"argv": argv, "config": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\\n")
    out = sys.stdout
    if argv == ["setup-token"]:
        out.write("\\x1b[2KThis\\x1b[1Cwill\\x1b[1Cguide\\x1b[1Cyou\\x1b[1Cthrough\\x1b[1Clong-lived\\x1b[1C(1-year)\\x1b[1Cauth\\r\\n")
        out.write("https://claude.com/cai/oauth/authorize?code=true&scope=user%3Ainference&state=abc\\r\\n")
        out.write("Paste\\x1b[1Ccode\\x1b[1Chere\\x1b[1Cif\\x1b[1Cprompted\\x1b[1C>\\x1b[1C")
        out.flush()
        code = sys.stdin.readline().strip()
        out.write("\\r\\n" + "*" * len(code) + "\\r\\n")
        if code == "good#state":
            out.write("\\x1b[32m\\u2713\\x1b[1CLong-lived\\x1b[1Cauthentication\\x1b[1Ctoken\\x1b[1Ccreated\\x1b[1Csuccessfully!\\x1b[39m\\r\\n")
            out.write("Your\\x1b[1COAuth\\x1b[1Ctoken\\x1b[1C(valid\\x1b[1Cfor\\x1b[1C1y):\\r\\n\\x1b[33m%s\\x1b[39m\\r\\n" % "@CREDENTIAL@")
            out.write("Store\\x1b[1Cthis\\x1b[1Ctoken\\x1b[1Csecurely.\\r\\n")
        else:
            out.write("OAuth\\x1b[1Cerror:\\x1b[1CRequest\\x1b[1Cfailed\\x1b[1Cwith\\x1b[1Cstatus\\x1b[1Ccode\\x1b[1C400\\r\\nPress\\x1b[1CEnter\\x1b[1Cto\\x1b[1Cretry.\\r\\n")
        out.flush()
        time.sleep(120)
    elif argv[:2] == ["auth", "login"]:
        out.write("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&scope=user%3Aprofile\\r\\n")
        out.write("Paste code here if prompted > ")
        out.flush()
        code = sys.stdin.readline().strip()
        out.write("\\r\\nLogin successful.\\r\\n" if code == "good#state" else "\\r\\nLogin failed: bad code\\r\\n")
        out.flush()
        sys.exit(0 if code == "good#state" else 1)
    ''').replace('@PY@', sys.executable).replace('@CREDENTIAL@', YEAR_CREDENTIAL)


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


class OneYearSignin(unittest.TestCase):
    def setUp(self):
        for f in Path(STATE).glob('*'):
            f.unlink()
        self.up = ThreadingHTTPServer(('127.0.0.1', 0), Anthropic)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.addCleanup(self.up.shutdown)
        self.dir = tempfile.mkdtemp()
        self.work = Path(tempfile.mkdtemp())
        self.log = Path(self.work, 'cli.log')
        cli = Path(self.work, 'claude')
        cli.write_text(FAKE)
        cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
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
                  patch.object(owner, 'CLAUDE_DIR', self.dir), patch.object(owner, 'CLAUDE', str(cli)),
                  patch.object(owner, 'WORK', self.work), patch.object(pool, 'AUTO_ORDER', False),
                  patch.object(owner, 'claude_status', lambda: {'status': 'connected', 'plan': 'Claude Max', 'account': 'owner@example.com'}),
                  patch.object(owner, 'run_test', side_effect=AssertionError('no renewal turn expected')),
                  patch.object(owner.State, 'after_sign_in', None),
                  patch.object(owner.inference, 'models', return_value=[])):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
        self.http = pool.Server(('127.0.0.1', 0), pool.Handler)
        threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01}, daemon=True).start()
        self.addCleanup(lambda: (self.http.shutdown(), self.http.server_close()))
        self.addCleanup(lambda: owner.end_login())
        self.base = 'http://127.0.0.1:%d' % self.http.server_port

    # ---- helpers ----
    def call(self, path, body=None, headers=None):
        h = dict(headers or {})
        if body is not None:
            h.setdefault('Content-Type', 'application/json')
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                code, text = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            code, text = e.code, e.read().decode()
        self.assertNotIn(YEAR_CREDENTIAL, text)
        self.assertNotIn('sk-ant-oat', text)
        self.assertNotIn(TOKEN, text)
        return code, json.loads(text) if text else None

    def get(self, path, headers=None):
        code, data = self.call(path, headers=headers)
        self.assertEqual(code, 200, data)
        return data

    def switch(self, on):
        code, data = self.call('/api/switches', {'id': 'one-year-signin', 'on': on}, OWNER)
        self.assertEqual(code, 200, data)
        return data

    def four_week(self, ends_in_s=20 * DAY + 600):
        oauth = {'accessToken': TOKEN, 'refreshToken': REFRESH, 'expiresAt': (time.time() + 8 * 3600) * 1000,
                 'refreshTokenExpiresAt': (time.time() + ends_in_s) * 1000, 'scopes': ['user:profile', 'user:inference'],
                 'subscriptionType': 'max', 'rateLimitTier': 'default_claude_max_20x'}
        Path(self.dir, '.credentials.json').write_text(json.dumps({'claudeAiOauth': oauth, 'mcpOAuth': {'kept': 1}}))
        Path(self.dir, '.claude.json').write_text(json.dumps({'oauthAccount': {'emailAddress': 'owner@example.com'}}))
        owner.CONNECTION.result = None

    def one_year(self, ends_in_s):
        oauth = {'accessToken': YEAR_CREDENTIAL, 'refreshToken': None, 'expiresAt': int((time.time() + ends_in_s) * 1000),
                 'scopes': ['user:inference'], 'wizardSignin': 'one-year', 'subscriptionType': 'max',
                 'rateLimitTier': 'default_claude_max_20x'}
        Path(self.dir, '.credentials.json').write_text(json.dumps({'claudeAiOauth': oauth}))
        Path(self.dir, '.claude.json').write_text(json.dumps({'oauthAccount': {'emailAddress': 'owner@example.com'}}))
        owner.CONNECTION.result = None

    def runs(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    # ---- the switch ----
    def test_switch_listed_off_by_default_owner_only_and_kept_on_the_box(self):
        doc = self.get('/api/switches', OWNER)
        self.assertEqual(doc['contract'], 'wizard.app-switches/1')
        row = next(s for s in doc['switches'] if s['id'] == 'one-year-signin')
        self.assertEqual((row['on'], row['default']), (False, False))
        self.assertEqual(row['issues'], ['humanitylabs-org/claude-connection#27'])
        self.assertEqual(self.call('/api/switches', headers={'X-Wizard-Switch': '1'})[0], 403, 'a box-local caller is not the owner')
        self.assertEqual(self.call('/api/switches', {'id': 'one-year-signin', 'on': True}, {**OWNER, 'Tailscale-User-Login': ''})[0], 403)
        self.assertEqual(self.call('/api/switches', {'id': 'nope', 'on': True}, OWNER)[0], 404)
        self.assertTrue(next(s for s in self.switch(True)['switches'] if s['id'] == 'one-year-signin')['on'])
        self.assertTrue(json.loads(Path(STATE, 'switches.json').read_text())['one-year-signin'])
        self.assertTrue(owner.one_year_on())
        self.assertEqual(self.get('/claude-code/api/switches', OWNER)['switches'][0]['on'], True)

    # ---- switch off: nothing changes ----
    def test_switch_off_connect_is_the_normal_login_and_answers_are_unchanged(self):
        self.four_week()
        code, started = self.call('/claude-code/api/claude/connect', {})
        self.assertEqual(code, 200, started)
        self.assertNotIn('year', started)
        self.assertEqual(self.runs()[-1]['argv'], ['auth', 'login', '--claudeai'])
        self.assertEqual(self.runs()[-1]['config'], self.dir, 'the normal login signs in the shared folder itself')
        code, done = self.call('/claude-code/api/claude/code', {'login_id': started['login_id'], 'code': 'good#state'})
        self.assertEqual(code, 200, done)
        self.assertNotIn('until', done)
        conn = self.get('/api/connection')
        for key in ('signin_kind',):
            self.assertNotIn(key, conn)
        self.assertEqual(conn['signin_days_left'], 20)
        accounts = self.get('/api/accounts')
        self.assertNotIn('oneYearSignin', accounts)
        self.assertEqual(accounts['signin']['warnDays'], 5)
        self.assertNotIn('kind', accounts['signin'])
        self.assertNotIn('signinKind', accounts['accounts'][0])
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        for key in ('signin_kind', 'signin_warn_days', 'one_year_signin'):
            self.assertNotIn(key, page)
        self.assertTrue(any(h.endswith('/usage') for h in Anthropic.hits), 'a four-week sign-in still reads usage')

    # ---- switch on: Connect signs in for one year ----
    def test_switch_on_connect_runs_the_one_year_signin_and_stores_it_in_the_shared_folder(self):
        self.four_week()
        self.switch(True)
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        self.assertTrue(page['one_year_signin'])
        self.assertTrue(self.get('/api/accounts')['oneYearSignin'])
        code, started = self.call('/claude-code/api/claude/connect', {})
        self.assertEqual(code, 200, started)
        self.assertTrue(started['year'])
        self.assertIn('scope=user%3Ainference', started['url'])
        run = self.runs()[-1]
        self.assertEqual(run['argv'], ['setup-token'])
        self.assertNotEqual(run['config'], self.dir, 'the one-year sign-in runs on a scratch folder')
        before = time.time()
        code, done = self.call('/claude-code/api/claude/code', {'login_id': started['login_id'], 'code': 'good#state'})
        self.assertEqual(code, 200, done)
        self.assertTrue(done['ok'])
        self.assertRegex(done['message'], r'^Signed in for one year, until \d{1,2} \w{3} \d{4}\.$')
        saved = json.loads(Path(self.dir, '.credentials.json').read_text())
        oauth = saved['claudeAiOauth']
        self.assertEqual(oauth['accessToken'], YEAR_CREDENTIAL)
        self.assertEqual(oauth['scopes'], ['user:inference'])
        self.assertEqual(oauth['wizardSignin'], 'one-year')
        self.assertIsNone(oauth['refreshToken'])
        self.assertAlmostEqual(oauth['expiresAt'] / 1000, before + 365 * DAY, delta=60)
        self.assertEqual((oauth['subscriptionType'], oauth['rateLimitTier']), ('max', 'default_claude_max_20x'), 'plan kept')
        self.assertEqual(saved['mcpOAuth'], {'kept': 1}, 'the rest of the file is kept')
        self.assertEqual(stat.S_IMODE(os.stat(Path(self.dir, '.credentials.json')).st_mode), 0o600)
        self.assertFalse(list(Path(self.dir).glob('*.tmp')))
        self.assertFalse(Path(self.work, 'one-year-login').exists(), 'scratch folder removed')
        self.assertIsNone(owner.State.login)
        # No env file, no second login anywhere: the one shared file is the only place it is written.
        self.assertEqual(sorted(p.name for p in Path(self.dir).iterdir() if not p.name.startswith('.wizard')),
                         ['.claude.json', '.credentials.json'])
        Anthropic.hits.clear()
        conn = self.get('/api/connection')
        self.assertEqual(conn['status'], 'connected')
        self.assertEqual(conn['signin_kind'], 'one_year')
        self.assertIn(conn['signin_days_left'], (364, 365))
        self.assertEqual(conn['plan'], 'Max 20x')
        self.assertIsNone(conn['usage'])
        self.assertEqual(Anthropic.hits, [], 'usage and profile need a scope the one-year sign-in lacks: never asked')
        row = self.get('/api/accounts')['accounts'][0]
        self.assertEqual((row['source'], row['status'], row['signinKind']), ('legacy-claude-code', 'connected', 'one_year'))
        self.assertEqual(self.get('/api/accounts')['signin']['warnDays'], 14)
        self.assertEqual(self.get('/api/inbox')['items'], [])

    def test_switch_on_wrong_code_fails_cleanly_and_keeps_the_old_signin(self):
        self.four_week()
        self.switch(True)
        old = Path(self.dir, '.credentials.json').read_bytes()
        _, started = self.call('/claude-code/api/claude/connect', {})
        t = time.monotonic()
        code, done = self.call('/claude-code/api/claude/code', {'login_id': started['login_id'], 'code': 'wrong#state'})
        self.assertLess(time.monotonic() - t, 15, 'the screen waits for Enter; the app must not wait for an exit')
        self.assertEqual(code, 400)
        self.assertIn('did not accept that code', done['message'])
        self.assertEqual(Path(self.dir, '.credentials.json').read_bytes(), old)

    # ---- reading a one-year sign-in ----
    def test_until_date_and_warnings_14_and_3_days_ahead(self):
        self.one_year(200 * DAY + 600)
        conn = self.get('/api/connection')
        self.assertEqual((conn['status'], conn['signin_kind'], conn['signin_days_left']), ('connected', 'one_year', 200))
        self.assertEqual(self.get('/api/inbox')['items'], [])
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        self.assertEqual((page['signin_kind'], page['signin_warn_days']), ('one_year', 14))
        self.one_year(15 * DAY + 3600)
        self.assertEqual(self.get('/api/inbox')['items'], [], '15 days: not yet')
        self.one_year(14 * DAY + 3600)
        first = self.get('/api/inbox')['items']
        self.assertEqual(len(first), 1, first)
        self.assertEqual(first[0]['title'], 'Claude sign-in ends in 14 days')
        self.assertEqual(first[0]['open'], 'claude-code/?connect=1')
        self.assertTrue(first[0]['key'].endswith(':14'))
        later = pool.signin_inbox(time.time() + 5 * DAY)['items'][0]
        self.assertEqual((later['key'], later['time']), (first[0]['key'], first[0]['time']), 'the 14-day warning comes once')
        self.one_year(3 * DAY + 3600)
        second = self.get('/api/inbox')['items']
        self.assertEqual(len(second), 1, second)
        self.assertEqual(second[0]['title'], 'Claude sign-in ends in 3 days')
        self.assertTrue(second[0]['key'].endswith(':3'), 'a new item: it shows again even if the first was archived')
        self.assertEqual(second[0]['time'] % DAY, 0)
        self.assertGreaterEqual(second[0]['priority'], 4)
        self.assertEqual(self.get('/api/connection')['status'], 'connected')

    def test_past_the_date_expired_with_reconnect(self):
        self.one_year(-60)
        Anthropic.hits.clear()
        conn = self.get('/api/connection')
        self.assertEqual((conn['status'], conn['error']['code']), ('expired', 'signin_ended'))
        self.assertIn('one-year', conn['error']['message'])
        self.assertEqual(Anthropic.hits, [])
        self.assertEqual(self.get('/api/inbox')['items'][0]['title'], 'Claude sign-in has ended')
        page = self.get('/claude-code/api/accounts')['accounts'][0]
        self.assertEqual(page['status'], 'expired')
        self.assertIn('Reconnect', page['message'])

    def test_inference_scope_alone_is_not_a_one_year_signin(self):
        self.four_week()
        data = json.loads(Path(self.dir, '.credentials.json').read_text())
        data['claudeAiOauth']['scopes'] = ['user:inference']
        Path(self.dir, '.credentials.json').write_text(json.dumps(data))
        owner.CONNECTION.result = None
        conn = self.get('/api/connection')
        self.assertNotIn('signin_kind', conn)
        self.assertEqual(conn['signin_days_left'], 20)

    def test_one_year_signin_keeps_working_with_the_switch_off(self):
        self.one_year(100 * DAY)
        conn = self.get('/api/connection')
        self.assertEqual((conn['status'], conn['signin_kind']), ('connected', 'one_year'))


class Pieces(unittest.TestCase):
    def test_screen_reader(self):
        raw = 'Paste\x1b[1Ccode\x1b[1Chere\x1b[1Cif\x1b[1Cprompted\x1b[1C>'
        self.assertTrue(one_year.ready(raw))
        self.assertTrue(one_year.ready('Pastecodehereifprompted>'))
        self.assertFalse(one_year.ready('Opening browser'))
        self.assertIsNone(one_year.outcome('\r\n********\r\n', tempfile.mkdtemp()))

    def test_server_never_names_the_credential(self):
        text = (ROOT / 'server.py').read_text()
        for word in ('accessToken', 'refreshToken', 'setup-token', '.credentials.json', 'sk-ant'):
            self.assertNotIn(word, text)


if __name__ == '__main__':
    unittest.main()
