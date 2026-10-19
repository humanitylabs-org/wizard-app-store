"""Real HTTP + fake CLI; no external provider traffic or real credentials."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inference
import server


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'fake-only', 'ANTHROPIC_API_KEY': 'must-not-inherit',
                                          'ANTHROPIC_BASE_URL': 'http://invalid'}, clear=True)
        self.env.start()
        self.cli = Path(__file__).parent / 'tests/fake_claude.py'
        self.cli.chmod(0o755)
        self.settings = patch.multiple(server, CLAUDE=str(self.cli), CLAUDE_DIR=str(self.root / 'login'), WORK=self.root / 'work')
        self.settings.start()
        self.srv = server.Server(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.srv.server_port}'

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join()
        self.settings.stop()
        self.env.stop()
        self.tmp.cleanup()

    def call(self, data=None, headers=None, path='/api/infer', raw=None):
        if data is None:
            data = {'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'hello'}], 'stream': True}
        req = Request(self.base + path, data=raw if raw is not None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            res = urlopen(req, timeout=10)
        except HTTPError as e:
            res = e
        with res:
            return res.status, res.read().decode()

    def test_real_http_isolation_and_done(self):
        status, text = self.call()
        self.assertEqual(status, 200)
        self.assertIn('event: delta', text)
        done = json.loads(text.split('event: done\ndata: ')[1])
        self.assertEqual(done['model'], 'claude-sonnet-5')
        self.assertEqual(done['usage']['output_tokens'], 1)
        self.assertNotIn('fake-only', text)
        self.assertEqual(list((self.root / 'work').iterdir()), [])

    def test_web_opt_in(self):
        data = {'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'hello'}], 'abilities': ['web_search']}
        self.assertIn('event: done', self.call(data)[1])

    def test_completion_failures(self):
        for mode in ('missing', 'mismatch', 'bad-json', 'denied', 'no-model', 'no-usage', 'text-mismatch'):
            with self.subTest(mode=mode):
                _, text = self.call({'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': mode}]})
                self.assertNotIn('event: done', text)
                self.assertIn('provider_error', text)

    def test_error_codes(self):
        for message, code in [('rate_limit', 'limit'), ('expired', 'expired'), ('not logged in', 'signed_out'),
                              ('connection error', 'unreachable'), ('private diagnostic', 'provider_error')]:
            with self.subTest(code=code):
                _, text = self.call({'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'error:' + message}]})
                self.assertEqual(json.loads(text)['code'], code)
                self.assertNotIn('private diagnostic', text)

    def test_grant_enforcement(self):
        path = self.root / 'grants.json'
        path.write_text(json.dumps({'enforce': True, 'incoming': [
            {'from': 'wizard-connection-router', 'sha256': hashlib.sha256(b'router-test').hexdigest()},
            {'from': 'other-app', 'sha256': hashlib.sha256(b'other-test').hexdigest()}]}))
        os.environ['WIZARD_GRANTS_FILE'] = str(path)
        for headers in ({}, {'X-Wizard-App': 'wizard-connection-router'}, {'X-Wizard-Grant': 'bad'}, {'X-Wizard-Grant': 'other-test'}):
            self.assertEqual(self.call(headers=headers)[0], 403)
        self.assertIn('event: done', self.call(headers={'X-Wizard-Grant': 'router-test'})[1])
        path.write_text('{}')
        self.assertEqual(self.call()[0], 503)

    def test_proxy_refusal(self):
        for key in ('Origin', 'Forwarded', 'X-Forwarded-For', 'X-Real-IP', 'Tailscale-User-Login', 'CF-Ray'):
            with self.subTest(header=key):
                self.assertEqual(self.call(headers={key: ''})[0], 403)

    def test_invalid_requests(self):
        valid = {'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'hello'}]}
        for update in ({'model': 'other'}, {'messages': []}, {'abilities': ['Read']}, {'stream': False},
                       {'max_tokens': True}, {'max_tokens': 0}, {'profile': 'secret'}, {'tools': []},
                       {'messages': [{'role': 'system', 'content': 'no'}]}):
            with self.subTest(update=update):
                self.assertEqual(self.call({**valid, **update})[0], 400)
        self.assertEqual(self.call(raw=b'{"model":"a","model":"b"}')[0], 400)
        self.assertEqual(self.call(raw=b' ' * (inference.MAX_BODY + 1))[0], 413)

    def test_signed_out_and_expired(self):
        os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN')
        self.assertEqual(json.loads(self.call()[1])['code'], 'signed_out')
        login = self.root / 'login'
        login.mkdir()
        (login / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': 'fake', 'expiresAt': 1}}))
        self.assertEqual(json.loads(self.call()[1])['code'], 'expired')

    def test_limit(self):
        _, text = self.call({'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 1})
        self.assertIn('limit', text)
        self.assertNotIn('event: done', text)

    def test_deadline_cleanup_and_capacity(self):
        with patch.object(inference, 'TIMEOUT_S', .05):
            _, text = self.call({'model': 'claude-sonnet-5', 'messages': [{'role': 'user', 'content': 'stall'}]})
        self.assertIn('unreachable', text)
        self.assertEqual(list((self.root / 'work').iterdir()), [])
        with patch.object(inference, 'SLOTS', threading.BoundedSemaphore(0)):
            self.assertEqual(self.call()[0], 429)
        self.assertIn('event: done', self.call()[1])

    def test_page_password_not_bypassed_by_unknown_grant(self):
        with patch.object(server, 'PASSWORD', 'owner-page-password'):
            request = Request(self.base + '/api/connection', headers={'X-Wizard-Grant': 'unknown'})
            with self.assertRaises(HTTPError) as err:
                urlopen(request)
            self.assertEqual(err.exception.code, 401)
            err.exception.close()

    def test_discovery_additive(self):
        old = {'contract': 'wizard.ai-connection/1', 'provider': 'claude', 'name': 'Claude', 'status': 'connected',
               'plan': 'Pro', 'account': 'fake@example.test', 'usage': None, 'error': None}
        with patch.object(server.CONNECTION, 'read', return_value=old):
            with urlopen(self.base + '/api/connection') as response:
                data = json.load(response)
        self.assertEqual(data['contract'], 'wizard.ai-connection/2')
        self.assertEqual({k: v for k, v in data.items() if k not in ('contract', 'models')}, {k: v for k, v in old.items() if k != 'contract'})
        self.assertEqual([(m['tier'], m['id']) for m in data['models']], [('fast', 'claude-haiku-4-5'), ('standard', 'claude-sonnet-5'), ('frontier', 'claude-opus-5-5')])


if __name__ == '__main__':
    unittest.main()
