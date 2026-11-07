"""Owning CLI mocked: no real sign-in, provider calls, or spend."""
import importlib.util
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('claude_owner_fixture', ROOT / 'server.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
EXPIRED = {'status': 'expired', 'usage': None, 'error': {'code': 'expired'}}

class RenewalTests(unittest.TestCase):
    def setUp(self):
        m.Renew.at = 0
        m.Renew.thread = None
        self.env = patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_success_reads_back_same_owner_reader(self):
        class Reader:
            def read(self): return {'status': 'connected', 'usage': {'limits': []}}
        with patch.object(m, 'run_test', return_value=(200, {})) as run:
            self.assertEqual(m.renew_if_expired(EXPIRED, Reader())['status'], 'renewing')
            m.Renew.thread.join(3)
            self.assertFalse(m.Renew.thread.is_alive())
            self.assertEqual(m.renew_if_expired(EXPIRED), EXPIRED)
            run.assert_called_once_with()

    def test_failed_challenge_timeout_exception_cooldown(self):
        for result in [(502, {'message': 'sign in'}), (504, {}), RuntimeError('SECRET')]:
            m.Renew.at = 0
            kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with patch.object(m, 'run_test', **kwargs) as run:
                self.assertEqual(m.renew_if_expired(EXPIRED)['status'], 'renewing')
                m.Renew.thread.join(3)
                for _ in range(8): self.assertEqual(m.renew_if_expired(EXPIRED), EXPIRED)
                run.assert_called_once_with()

    def test_single_flight_and_cooldown_does_not_slide_on_poll(self):
        entered, release = threading.Event(), threading.Event()
        def run():
            entered.set()
            self.assertTrue(release.wait(3))
            return 502, {}
        with patch.object(m, 'run_test', side_effect=run) as mock:
            t = threading.Thread(target=m.renew_if_expired, args=(EXPIRED,))
            t.start()
            self.assertTrue(entered.wait(3))
            self.assertEqual(m.renew_if_expired(EXPIRED)['status'], 'renewing')
            release.set(); t.join(3)
            m.Renew.thread.join(3)
            self.assertFalse(t.is_alive())
            at = m.Renew.at
            self.assertEqual(m.renew_if_expired(EXPIRED), EXPIRED)
            self.assertEqual(m.Renew.at, at)
            mock.assert_called_once_with()
            with patch.object(m.time, 'monotonic', return_value=at + 601):
                self.assertEqual(m.renew_if_expired(EXPIRED)['status'], 'renewing')
                m.Renew.thread.join(3)
            self.assertEqual(mock.call_count, 2)

    def test_disable_and_non_expired_never_invoke_cli(self):
        with patch.object(m, 'run_test') as run:
            with patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '0'}):
                self.assertEqual(m.renew_if_expired(EXPIRED), EXPIRED)
            for status in ['connected', 'not_connected', 'error']:
                self.assertEqual(m.renew_if_expired({'status': status}), {'status': status})
            run.assert_not_called()

    def test_actual_claude_pool_http_renewal_and_expired_readback(self):
        import json
        import urllib.request
        class Reader:
            def read(self): return dict(EXPIRED)
        spec = importlib.util.spec_from_file_location('claude_pool_fixture', ROOT / 'pool_server.py')
        pool = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER':'claude'}), patch.dict(sys.modules, {'server':m}), patch.object(m, 'CONNECTION', Reader()):
            spec.loader.exec_module(pool)
        pool.PASSWORD = ''
        pool.Hermes.accounts = lambda _: {'provider':'claude','accounts':[]}
        http = pool.Server(('127.0.0.1',0),pool.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(m, 'run_test', return_value=(502, {'message':'SECRET challenge'})) as run:
                with urllib.request.urlopen('http://127.0.0.1:'+str(http.server_port)+'/api/accounts') as response:
                    self.assertIn(json.load(response)['accounts'][0]['status'], ('expired', 'renewing'))
                m.Renew.thread.join(3)
                for _ in range(3):
                    with urllib.request.urlopen('http://127.0.0.1:'+str(http.server_port)+'/api/accounts') as response:
                        out=json.load(response)
                    self.assertEqual(out['accounts'][0]['status'],'expired')
                    self.assertEqual(out['accounts'][0]['error']['code'],'expired')
                    self.assertNotIn('SECRET',json.dumps(out))
                run.assert_called_once_with()
        finally:
            http.shutdown();http.server_close();thread.join()

    def test_http_connection_preserves_unfolded_cooldown_grants(self):
        import json
        import time
        import urllib.request
        class Reader:
            def read(self): return {'status': 'connected', 'account': 'original@example.com', 'usage': {'limits': []}}
        spec = importlib.util.spec_from_file_location('claude_pool_cooldowns_fixture', ROOT / 'pool_server.py')
        pool = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}), patch.dict(sys.modules, {'server': m}), patch.object(m, 'CONNECTION', Reader()):
            spec.loader.exec_module(pool)
        pool.PASSWORD = ''
        evidence = {'contract': 'wizard.model-cooldowns/1', 'observedAt': time.time(), 'grants': [
            {'id': 'a' * 24, 'models': {'claude-opus-5-5': time.time() + 3600}},
            {'id': 'b' * 24, 'models': {'claude-opus-5-5': time.time() + 3600}}]}
        pool.Hermes.accounts = lambda _: {'provider': 'claude', 'owner': 'hermes', 'accounts': [
            {'id': 'mirror', 'mirror': 'claude-code', 'credentials': [{'name': 'claude_code'}]},
            {'id': 'manual', 'status': 'ready'}], 'modelCooldowns': evidence}
        http = pool.Server(('127.0.0.1', 0), pool.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        try:
            with patch.object(pool.owner.inference, 'models', return_value=[]):
                with urllib.request.urlopen('http://127.0.0.1:' + str(http.server_port) + '/api/connection') as response:
                    out = json.load(response)
            with patch.object(pool.Hermes, 'request', return_value=evidence) as bridge:
                with urllib.request.urlopen('http://127.0.0.1:' + str(http.server_port) + '/api/model-cooldowns') as response:
                    projection = json.load(response)
            bridge.assert_called_once_with('claude', '/model-cooldowns')
            self.assertEqual(projection, {'provider': 'claude', 'owner': 'hermes', 'modelCooldowns': evidence})
            self.assertEqual(out['contract'], 'wizard.ai-connection/2')
            self.assertEqual(out['accountCount'], 2)
            self.assertEqual(len(projection['modelCooldowns']['grants']), 2)
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def test_official_cli_is_noninteractive_bounded_and_no_login_command(self):
        from types import SimpleNamespace
        import tempfile
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as work:
            with patch.object(m, 'WORK', Path(work)), patch.object(m.subprocess, 'run', return_value=SimpleNamespace(stdout='{"result":"OK"}')) as run:
                self.assertEqual(m.run_test()[0], 200)
                args, kwargs = run.call_args
                self.assertEqual(args[0][0], m.CLAUDE)
                self.assertNotIn('login', args[0]); self.assertNotIn('auth', args[0])
                self.assertEqual(kwargs['timeout'], 120)
                self.assertEqual(kwargs['stdin'], m.subprocess.DEVNULL)
                self.assertEqual(kwargs['env']['CLAUDE_CONFIG_DIR'], m.CLAUDE_DIR)
                self.assertNotIn('ANTHROPIC_API_KEY', kwargs['env'])

if __name__ == '__main__': unittest.main()
