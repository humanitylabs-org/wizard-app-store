"""Real loopback GETs held against a slow fake owning CLI; no provider access."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
sys.path.insert(0, str(ROOT))
# Optional archived fixtures prove these tests fail on the original candidate.
spec = importlib.util.spec_from_file_location('server', os.environ.get('RENEWAL_SERVER', ROOT / 'server.py'))
owner = importlib.util.module_from_spec(spec)
sys.modules['server'] = owner
spec.loader.exec_module(owner)
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}):
    spec = importlib.util.spec_from_file_location('pool_fixture', os.environ.get('POOL_SERVER', ROOT / 'pool_server.py'))
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)
EXPIRED = {'status': 'expired', 'error': {'code': 'expired'}, 'usage': None}


class Regressions(unittest.TestCase):
    def setUp(self):
        owner.Renew.at = 0
        owner.Renew.thread = None
        self.reader = Mock()
        self.reader.read.return_value = dict(EXPIRED)
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls = 0
        self.patches = [patch.object(pool, 'LEGACY', self.reader),
                        patch.object(owner, 'CONNECTION', self.reader),
                        patch.object(pool.Hermes, 'accounts', return_value={'provider': 'claude', 'accounts': []}),
                        patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '1'})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.servers = []
        self.addCleanup(self.close)

    def close(self):
        self.release.set()
        worker = owner.Renew.thread
        if worker:
            worker.join(4)
        for http, thread in self.servers:
            http.shutdown(); http.server_close(); thread.join()

    def serve(self, module):
        http = module.Server(('127.0.0.1', 0), module.Handler)
        thread = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.servers.append((http, thread))
        return 'http://127.0.0.1:' + str(http.server_port)

    def get(self, base, path):
        with urlopen(base + path, timeout=1) as response:
            return json.load(response)

    def slow_cli(self):
        self.calls += 1
        self.entered.set()
        self.release.wait(3)  # longer than the HTTP timeout: old synchronous GET fails
        self.reader.read.return_value = {'status': 'connected', 'usage': {'limits': []}}
        return 200, {}

    def check_nonblocking(self, module, paths):
        base = self.serve(module)
        with patch.object(owner, 'run_test', side_effect=self.slow_cli):
            try:
                for _ in range(2):
                    for path in paths:
                        start = time.monotonic()
                        answer = self.get(base, path)
                        self.assertLess(time.monotonic() - start, .75)
                        self.assertTrue(self.entered.wait(.5))
                        self.assertFalse(self.release.is_set())
                        self.assertTrue(owner.Renew.thread.is_alive())
                        self.assertEqual(answer['status'] if path.endswith('connection') else answer['accounts'][0]['status'], 'renewing')
                self.assertEqual(self.calls, 1)
            finally:
                self.release.set()
                if owner.Renew.thread:
                    owner.Renew.thread.join(4)
            self.assertEqual(self.get(base, '/api/connection')['status'], 'connected')

    def test_pool_get_does_not_wait_for_cli(self):
        self.check_nonblocking(pool, ('/api/accounts', '/api/connection'))

    def test_legacy_get_does_not_wait_for_cli(self):
        self.check_nonblocking(owner, ('/api/connection',))

    def test_expired_status_is_not_connected(self):
        base = self.serve(pool)
        owner.Renew.at = time.monotonic()  # failed attempt is in cooldown
        with patch.object(owner, 'run_test') as run:
            answer = self.get(base, '/api/connection')
            self.assertEqual(answer['status'], 'expired')
            self.assertEqual(answer['error']['code'], 'expired')
            self.assertEqual(answer['contract'], 'wizard.ai-connection/2')
            run.assert_not_called()

    def test_mixed_and_ready_status_is_truthful(self):
        base = self.serve(pool)
        with patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '0'}):
            for status, expected in [('ready', 'connected'), ('connected', 'connected'), ('expired', 'expired'), ('cooldown', 'expired')]:
                with patch.object(pool.Hermes, 'accounts', return_value={'accounts': [{'status': status}]}):
                    self.assertEqual(self.get(base, '/api/connection')['status'], expected)

    def test_pool_only_limits_errors_and_signed_out_have_explanations(self):
        base = self.serve(pool)
        with patch.object(pool, 'LEGACY', None):
            for status, expected, code in [('cooldown', 'error', 'limit'), ('exhausted', 'error', 'limit'),
                                           ('expired', 'expired', 'expired'), ('unknown', 'error', 'provider_error'),
                                           ('not_connected', 'not_connected', None), ('ready', 'connected', None)]:
                with self.subTest(status=status), patch.object(pool.Hermes, 'accounts', return_value={'accounts': [{'status': status}]}):
                    answer = self.get(base, '/api/connection')
                    self.assertEqual(answer['status'], expected)
                    self.assertEqual((answer.get('error') or {}).get('code'), code)


if __name__ == '__main__':
    unittest.main()
