"""Claude subscriptions: any number of accounts, no page password, original sign-in kept.

Loopback HTTP only: a fake Hermes inventory, a fake legacy Claude Code reader, no CLI, no provider access.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
owner = importlib.util.module_from_spec(spec)
sys.modules['server'] = owner
spec.loader.exec_module(owner)
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}):
    spec = importlib.util.spec_from_file_location('claude_pool', os.environ.get('POOL_SERVER', ROOT / 'pool_server.py'))
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)

MANAGEMENT = {'contract': 'wizard.account-management/1', 'status': 'available'}


def account(n, status='ready', managed=True, **extra):
    used = 10 * n % 100
    return {'id': 'acct%02d' % n, 'name': 'Sub %d' % n, 'email': 'o***%d@e***' % n, 'plan': 'Max 20x', 'status': status,
            'usage': {'limits': [{'id': 'weekly', 'label': 'All models · weekly', 'usedPercent': used,
                                  'remainingPercent': 100 - used, 'resetsAt': None}]},
            'credentials': [{'id': 'cred%02d' % n, 'name': 'Sub %d' % n, 'managed': managed}],
            'actions': {'reconnect': True, 'remove': True}, **extra}


class Legacy:
    def __init__(self, status='connected'):
        self.status = status

    def read(self):
        return {'status': self.status, 'account': 'owner@example.com', 'plan': 'Max 20x',
                'usage': {'limits': []} if self.status == 'connected' else None, 'error': None}


class ClaudePool(unittest.TestCase):
    def setUp(self):
        self.rows = [account(i) for i in range(1, 4)]
        self.calls = []
        test = self

        class FakeHermes:
            @staticmethod
            def accounts(provider):
                return {'owner': 'hermes', 'provider': provider, 'name': 'Claude', 'accounts': [dict(r) for r in test.rows],
                        'actions': {'add': True}, 'management': dict(MANAGEMENT)}

            @staticmethod
            def request(provider, suffix, body=None):
                test.calls.append((provider, suffix, body))
                if body and body.get('action') == 'add':
                    test.rows.append(account(len(test.rows) + 1))
                return {'id': 'operationabcdefghijklmnop', 'status': 'succeeded', 'action': (body or {}).get('action')}

        self.legacy = Legacy()
        for p in (patch.object(pool, 'Hermes', FakeHermes), patch.object(pool, 'LEGACY', self.legacy),
                  patch.object(pool, 'LEGACY_RENEW', None), patch.object(pool, 'PASSWORD', ''),
                  patch.object(owner, 'PASSWORD', ''), patch.object(owner, 'CONNECTION', self.legacy),
                  patch.object(owner.inference, 'models', return_value=[]),
                  patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '0'})):
            p.start()
            self.addCleanup(p.stop)
        self.http = pool.Server(('127.0.0.1', 0), pool.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = 'http://127.0.0.1:%d' % self.http.server_port

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def call(self, path, body=None, headers=None):
        h = dict(headers or {})
        if body is not None:
            h.setdefault('Content-Type', 'application/json')
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=3) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read(), e.headers

    def accounts(self):
        code, raw, _ = self.call('/api/accounts')
        self.assertEqual(code, 200)
        return json.loads(raw)

    def test_three_and_more_subscriptions_each_listed_with_own_usage(self):
        for total in (3, 5, 12):
            with self.subTest(total=total):
                self.rows = [account(i) for i in range(1, total + 1)]
                data = self.accounts()
                hermes = [a for a in data['accounts'] if a['source' if 'source' in a else 'id'] != 'legacy-claude-code']
                self.assertEqual(data['accounts'][0]['id'], 'legacy-claude-code')
                self.assertEqual(len(hermes), total)
                self.assertEqual(data['accountCount'], total + 1)
                self.assertEqual(len({a['id'] for a in hermes}), total)
                self.assertEqual([a['usage']['limits'][0]['usedPercent'] for a in hermes], [10 * i % 100 for i in range(1, total + 1)])
                self.assertTrue(all(a['status'] == 'ready' for a in hermes))
                self.assertIs(data['actions']['add'], True)

    def test_adding_a_fourth_and_fifth_subscription_is_not_capped(self):
        same = {'X-Wizard-Account-Action': '1', 'Origin': self.base, 'Sec-Fetch-Site': 'same-origin'}
        for expected in (4, 5):
            code, raw, _ = self.call('/api/operations', {'action': 'add', 'label': 'Sub', 'confirmed': True}, same)
            self.assertEqual(code, 200, raw)
            self.assertEqual(len([a for a in self.accounts()['accounts'] if a['id'] != 'legacy-claude-code']), expected)
        # Removing any one of five managed grants is allowed by the same rules.
        code, _, _ = self.call('/api/operations', {'action': 'remove', 'target': 'cred05', 'confirmed': True}, same)
        self.assertEqual(code, 200)
        self.assertEqual([c[2]['action'] for c in self.calls], ['add', 'add', 'remove'])

    def test_no_page_password_allows_same_origin_changes_only(self):
        body = {'action': 'add', 'confirmed': True}
        self.assertEqual(self.call('/api/operations', body)[0], 403)  # custom action header is required
        cross = [{'X-Wizard-Account-Action': '1', 'Origin': 'https://evil.example'},
                 {'X-Wizard-Account-Action': '1', 'Sec-Fetch-Site': 'cross-site'},
                 {'X-Wizard-Account-Action': '1', 'Sec-Fetch-Site': 'same-site'}]
        for headers in cross:
            with self.subTest(headers=headers):
                self.assertEqual(self.call('/api/operations', body, headers)[0], 403)
        self.assertEqual(self.call('/api/operations/operationabcdefghijklmnop', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.call('/api/operations', body, {'X-Wizard-Account-Action': '1', 'Origin': self.base})[0], 200)
        self.assertEqual(self.call('/api/operations/operationabcdefghijklmnop', headers={'Sec-Fetch-Site': 'same-origin'})[0], 200)

    def test_page_password_still_required_when_set(self):
        with patch.object(pool, 'PASSWORD', 'fixture-password-123456'):
            self.assertEqual(self.call('/api/operations', {'action': 'add', 'confirmed': True},
                                       {'X-Wizard-Account-Action': '1'})[0], 401)
            self.assertEqual(self.call('/api/accounts')[0], 401)
        self.assertEqual(self.calls, [])

    def test_claude_code_mirror_folds_into_the_original_row_old_and_new_plugins(self):
        flagged = account(7, mirror='claude-code', managed=False)
        old_style = account(8, managed=False)
        old_style['credentials'][0]['name'] = 'claude_code'
        self.rows = [flagged, old_style, account(1)]
        data = self.accounts()
        ids = [a['id'] for a in data['accounts']]
        self.assertEqual(ids, ['legacy-claude-code', 'acct01'])
        self.assertEqual(sorted(c['id'] for c in data['accounts'][0]['credentials']), ['cred07', 'cred08'])
        # A single box with only its original login reports no extra subscription (the shell keeps legacy routing).
        self.rows = [old_style]
        self.assertEqual([a['id'] for a in self.accounts()['accounts']], ['legacy-claude-code'])

    def test_unmanaged_non_mirror_rows_stay_listed(self):
        other = account(9, managed=False)  # e.g. a Hermes-imported grant that is not Claude Code's
        self.rows = [other]
        self.assertEqual([a['id'] for a in self.accounts()['accounts']], ['legacy-claude-code', 'acct09'])

    def test_original_sign_in_page_stays_reachable(self):
        code, _, headers = self.call('/claude-code')
        self.assertEqual(code, 308)
        self.assertEqual(headers['Location'], 'claude-code/')
        code, raw, headers = self.call('/claude-code/')
        self.assertEqual(code, 200)
        self.assertIn(b'api/claude/connect', self.call('/claude-code/app.js')[1])
        self.assertTrue(headers['Content-Type'].startswith('text/html'))
        code, raw, _ = self.call('/claude-code/api/accounts')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['accounts'][0]['id'], 'claude-subscription')
        # Cross-site POSTs to the original sign-in are refused before any CLI starts.
        with patch.object(owner, 'connect', side_effect=AssertionError('must not run')):
            self.assertEqual(self.call('/claude-code/api/claude/connect', {}, {'Origin': 'https://evil.example'})[0], 403)
        with patch.object(owner, 'connect', return_value=(200, {'ok': True, 'fixture': True})) as connect:
            code, raw, _ = self.call('/claude-code/api/claude/connect', {}, {'Origin': self.base})
            self.assertEqual((code, json.loads(raw)), (200, {'ok': True, 'fixture': True}))
            connect.assert_called_once()
        # Pool routes are unchanged by the prefix.
        self.assertEqual(self.call('/api/claude/connect', {}, {'Origin': self.base})[0], 404)

    def test_unreachable_inventory_keeps_original_login_visible(self):
        with patch.object(pool.Hermes, 'accounts', side_effect=RuntimeError('down')):
            data = self.accounts()
            self.assertEqual([a['id'] for a in data['accounts']], ['legacy-claude-code'])
            self.assertEqual(data['management']['status'], 'unavailable')
            self.assertIs(data['actions']['add'], False)
            code, raw, _ = self.call('/api/connection')
            self.assertEqual(json.loads(raw)['status'], 'connected')


class AgentDefaultAfterSignIn(unittest.TestCase):
    """Fresh mode: the Hermes Agent app starts with no main model, so a Claude sign-in here must become its model
    (else the first chat says "not connected to any AI provider"); a model the owner chose is never changed."""

    LIVE = ['claude-sonnet-5[1m]', 'claude-haiku-4-5-20251001', 'claude-opus-5-5[1m]', 'claude-opus-5[1m]',
            'claude-opus-4-8[1m]', 'claude-fable-5-1[1m]']  # the demo's list, 30 Oct 2026

    def serve(self, current, models=LIVE):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        seen = self.seen = []

        class Dash(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                seen.append(('GET', self.path))
                if self.path == '/api/model/info':
                    return self.reply({'provider': current, 'model': 'x' if current else ''})
                if self.path == '/api/model/options':
                    return self.reply({'provider': '', 'model': '', 'providers': [
                        {'slug': 'anthropic', 'models': ['claude-opus-9']},
                        {'slug': 'claude-subscription-directsdk-experimental', 'models': models}]})
                return self.reply({'provider': 'claude-subscription-directsdk-experimental', 'model': 'claude-sonnet-5[1m]'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(('POST', self.path, body))
                return self.reply({'ok': True})

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Dash)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return 'http://127.0.0.1:%d' % httpd.server_address[1]

    def adopt(self, url, **env):
        import pool_client
        with patch.dict(os.environ, {'WIZARD_CLAUDE_HERMES_PASSWORD': 'pw', **env}), patch.object(pool_client, 'agent_url', lambda p: url), \
                patch.object(pool_client, 'alongside', lambda p: False):
            return pool_client.adopt_as_agent_default('claude')

    def test_no_model_yet_gets_the_claude_subscription(self):
        self.assertEqual(self.adopt(self.serve('')), 'set')
        posts = [c for c in self.seen if c[0] == 'POST' and c[1] == '/api/model/set']
        self.assertEqual(posts[0][2]['provider'], 'claude-subscription-directsdk-experimental')
        self.assertEqual(posts[0][2]['model'], 'claude-opus-5-5[1m]')  # newest Opus, not the Sonnet recommended default
        self.assertEqual(posts[0][2]['scope'], 'main')

    def test_newest_opus_wins_whatever_the_order(self):
        import pool_client
        opts = lambda models: {'providers': [{'slug': 'claude-subscription-directsdk-experimental', 'models': models}]}
        self.assertEqual(pool_client.newest_opus(opts(['claude-opus-4-8[1m]', 'claude-opus-5[1m]', 'claude-opus-4-1-20250805'])), 'claude-opus-5[1m]')
        self.assertEqual(pool_client.newest_opus(opts([{'id': 'claude-opus-5-5'}, {'id': 'claude-opus-5-5[1m]'}])), 'claude-opus-5-5[1m]')
        self.assertEqual(pool_client.newest_opus(opts(['claude-sonnet-5[1m]'])), '')
        self.assertEqual(pool_client.newest_opus({}), '')

    def test_no_opus_listed_falls_back_to_the_recommended_default(self):
        self.assertEqual(self.adopt(self.serve('', models=['claude-sonnet-5[1m]', 'claude-haiku-4-5-20251001'])), 'set')
        posts = [c for c in self.seen if c[0] == 'POST' and c[1] == '/api/model/set']
        self.assertEqual(posts[0][2]['model'], 'claude-sonnet-5[1m]')

    def test_a_chosen_model_is_never_changed(self):
        self.assertEqual(self.adopt(self.serve('openai-codex')), 'kept')
        self.assertFalse([c for c in self.seen if c[0] == 'POST' and c[1] == '/api/model/set'])

    def test_alongside_or_no_agent_password_does_nothing(self):
        import pool_client
        with patch.dict(os.environ, {'WIZARD_CLAUDE_HERMES_PASSWORD': ''}):
            self.assertEqual(pool_client.adopt_as_agent_default('claude'), 'skipped')

    def test_the_sign_in_page_calls_it_after_a_good_code_only(self):
        self.assertIsNotNone(owner.State.after_sign_in)
        calls = []

        class Login:
            def alive(self):
                return True

            def submit(self, code):
                return {'ok': code == 'good', 'message': ''}

            def close(self):
                pass
        with patch.object(owner.State, 'after_sign_in', lambda: calls.append(1) or 'set'), patch.object(owner, 'claude_status', lambda: {}):
            for code in ('bad', 'good'):
                owner.State.login, owner.State.login_id = Login(), 'id'
                status, body = owner.submit_code('id', code)
        self.assertEqual(calls, [1])
        self.assertEqual(body.get('agent_default'), 'set')


class SignInCodeIsMasked(unittest.TestCase):
    """The pasted Claude code is a secret, so it shows as dots like a password (Miguel, 30 Oct 2026)."""

    def test_code_inputs_are_password_fields(self):
        import re
        for page in ('static/index.html', 'pool-static/index.html'):
            tag = re.search(r'<input id="code"[^>]*>', (ROOT / page).read_text()).group(0)
            self.assertIn('type="password"', tag, page)
            self.assertIn('autocomplete="off"', tag, page)
        tag = re.search(r'<input id="code"[^>]*>', (ROOT / 'static/index.html').read_text()).group(0)
        for keep in ('inputmode="text"', 'autocapitalize="off"', 'spellcheck="false"', 'required'):
            self.assertIn(keep, tag)


if __name__ == '__main__':
    unittest.main()
