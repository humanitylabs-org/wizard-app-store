"""Claude one-tap Use first for the original Claude Code login: the intent survives the page and the server finishes it.

Fake broker and fake original login only: no CLI, no provider, no credentials. Exercises the real pool_server over
loopback HTTP (POST add with useFirst, submit, cancel, the watcher thread, prefer) plus the pure resolver."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
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
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude', 'WIZARD_CLAUDE_AUTO_ORDER': '0'}):
    spec = importlib.util.spec_from_file_location('claude_pool_use_first', os.environ.get('POOL_SERVER', ROOT / 'pool_server.py'))
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)

H = lambda e: hashlib.sha256(e.encode()).hexdigest()[:16]
OP = 'useFirstOperation0123456789'


class Broker:
    """Stateful stand-in for the host plugin's account broker (wizard.account-management/1)."""
    def __init__(self):
        self.calls, self.job, self.lock = [], None, threading.Lock()
        self.rows = [
            {'id': 'mirror', 'mirror': 'claude-code', 'name': 'claude_code', 'status': 'ready', 'priority': 1, 'preferred': False,
             'credentials': [{'id': 'bd6a0f', 'name': 'claude_code', 'managed': False, 'priority': 1}], 'actions': {'prefer': False}},
            {'id': 'oscar-row', 'name': 'oscar', 'email': 'o***@g***', 'emailHash': H('oscar@example.com'), 'status': 'ready',
             'priority': 0, 'preferred': True, 'credentials': [{'id': '2eaa09', 'name': 'oscar', 'managed': True, 'priority': 0}],
             'actions': {'prefer': True, 'reconnect': True, 'remove': True}}]
        self.prefer_409 = 0
        self.lost = False

    def accounts(self, provider):
        with self.lock:
            return json.loads(json.dumps({'owner': 'hermes', 'provider': provider, 'accounts': self.rows, 'actions': {'add': True},
                                          'identity': {'emailHash': True},
                                          'management': {'contract': 'wizard.account-management/1', 'status': 'available'}}))

    def grant(self, cid, email):
        self.rows.append({'id': cid + '-row', 'name': 'Subscription', 'email': email[0] + '***@e***', 'emailHash': H(email), 'status': 'ready',
                          'priority': 2, 'preferred': False, 'credentials': [{'id': cid, 'name': 'Subscription', 'managed': True, 'priority': 2}],
                          'actions': {'prefer': True, 'reconnect': True, 'remove': True}})

    def request(self, provider, suffix='', body=None):
        with self.lock:
            self.calls.append((suffix, json.loads(json.dumps(body)) if body else None))
            if suffix == '':
                pass
            if suffix == '/operations' and body['action'] == 'add':
                self.job = {'id': OP, 'provider': 'claude', 'action': 'add', 'status': 'running', 'inputRequired': True,
                            'url': 'https://claude.ai/oauth/authorize?fixture=1', 'credentialIds': []}
                return dict(self.job)
            if suffix == '/operations' and body['action'] == 'submit':
                code = body['code']
                done = {'status': 'succeeded', 'inputRequired': False, 'url': None}
                if code == 'same':
                    self.grant('b13833', 'miguel@example.com'); done['credentialIds'] = ['b13833']
                elif code == 'other':
                    self.grant('c0ffee', 'someone@example.com'); done['credentialIds'] = ['c0ffee']
                elif code == 'dup':
                    done.update(credentialIds=['4641e0'], duplicateOf='2eaa09', duplicateRemoved=True)
                else:
                    done = {'status': 'failed'}
                self.job.update(done)
                return dict(self.job)
            if suffix == '/operations' and body['action'] == 'cancel':
                self.job['status'] = 'cancelled'
                return dict(self.job)
            if suffix == '/operations' and body['action'] == 'prefer':
                if self.prefer_409:
                    self.prefer_409 -= 1
                    raise pool.BridgeError(409, 'unreachable')
                for r in self.rows:
                    mine = any(c['id'] == body['target'] for c in r['credentials'])
                    r['priority'] = 0 if mine else r['priority'] + 1
                    r['preferred'] = mine
                return {'id': 'preferOperation0123456789', 'action': 'prefer', 'status': 'succeeded'}
            if suffix.startswith('/operations/'):
                if self.lost or not self.job or suffix.rsplit('/', 1)[1] != self.job['id']:
                    raise pool.BridgeError(404, 'unreachable')
                return dict(self.job)
            raise AssertionError('unexpected ' + suffix)

    def actions(self):
        return [(s, (b or {}).get('action'), (b or {}).get('target')) for s, b in self.calls if s == '/operations']


class Login:
    def __init__(self, email='miguel@example.com'):
        self.email = email

    def read(self):
        return {'status': 'connected', 'account': self.email, 'plan': 'Max 20x', 'usage': None, 'error': None}


class UseFirstContinues(unittest.TestCase):
    def setUp(self):
        self.broker = Broker()
        pool.Hermes = self.broker
        pool.LEGACY, pool.LEGACY_RENEW, pool.PASSWORD = Login(), None, ''
        pool.USE_FIRST.clear()
        pool.USE_FIRST_POLL = 0.05
        self.server = pool.Server(('127.0.0.1', 0), pool.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()

    def http(self, path, body=None):
        h = {'Content-Type': 'application/json', 'X-Wizard-Account-Action': '1'} if body is not None else {}
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (self.server.server_port, path),
                                     data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b'{}')

    def wait_state(self, *states, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            uf = self.http('/api/accounts')[1].get('useFirst')
            if uf and uf['state'] in states:
                return uf
            time.sleep(0.05)
        self.fail('use first never reached %s: %r' % (states, self.http('/api/accounts')[1].get('useFirst')))

    def begin(self):
        status, job = self.http('/api/operations', {'action': 'add', 'label': '', 'confirmed': True, 'useFirst': 'legacy-claude-code'})
        self.assertEqual(status, 200, job)
        self.assertEqual(job['useFirst']['state'], 'signing-in')
        self.assertEqual(job['useFirst']['account'], 'legacy-claude-code')
        self.assertNotIn('emailHash', job['useFirst'])                 # the page never needs the hash
        sent = [b for s, b in self.broker.calls if s == '/operations' and b['action'] == 'add'][0]
        self.assertNotIn('useFirst', sent)                              # the broker gets the stock add request only
        return job

    def test_same_account_is_put_first_without_a_second_tap_even_with_no_page(self):
        self.begin()
        # The page is gone (reload, sheet closed, app reopened): only the code arrives, from wherever.
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'same'})
        uf = self.wait_state('done')
        self.assertEqual(uf['credential'], 'b13833')
        self.assertEqual(self.broker.actions()[-1], ('/operations', 'prefer', 'b13833'))
        self.assertEqual([a for a in self.broker.actions() if a[1] == 'prefer'], [('/operations', 'prefer', 'b13833')])
        rows = self.http('/api/accounts')[1]['accounts']
        lead = min(rows, key=lambda a: a['priority'])
        self.assertEqual(lead['credentials'][0]['id'], 'b13833')
        self.assertFalse(any(a['id'] == 'legacy-claude-code' for a in rows))   # the original row folded into it
        # The operation read carries the result too, so a page polling it finishes in place.
        self.assertEqual(self.http('/api/operations/' + OP)[1]['useFirst']['state'], 'done')

    def test_submit_from_the_page_is_annotated_and_finishes(self):
        self.begin()
        status, job = self.http('/api/operations', {'action': 'submit', 'operation': OP, 'code': 'same'})
        self.assertEqual(status, 200)
        self.assertIn(job['useFirst']['state'], pool.USE_FIRST_ACTIVE + ('done',))
        self.wait_state('done')

    def test_other_account_changes_no_order_and_says_so(self):
        self.begin()
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'other'})
        uf = self.wait_state('wrong-account')
        self.assertEqual(uf['signedInAs'], 'c0ffee-row')
        self.assertTrue(uf['kept'])
        self.assertFalse(any(a[1] == 'prefer' for a in self.broker.actions()))

    def test_duplicate_of_an_added_account_changes_no_order(self):
        self.begin()
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'dup'})
        uf = self.wait_state('wrong-account')
        self.assertEqual(uf['signedInAs'], 'oscar-row')
        self.assertFalse(uf['kept'])
        self.assertFalse(any(a[1] == 'prefer' for a in self.broker.actions()))

    def test_cancel_failure_and_lost_job_clear_the_intent(self):
        self.begin()
        status, job = self.http('/api/operations', {'action': 'cancel', 'operation': OP})
        self.assertEqual(status, 200)
        self.assertEqual(self.wait_state('cancelled')['state'], 'cancelled')
        pool.USE_FIRST.clear(); self.begin()
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'wrong'})
        self.wait_state('failed')
        pool.USE_FIRST.clear(); self.begin()
        self.broker.lost = True                                         # the agent restarted and forgot the job
        self.wait_state('expired')
        self.assertFalse(any(a[1] == 'prefer' for a in self.broker.actions()))

    def test_timeout_clears_the_intent(self):
        self.begin()
        self.wait_state('signing-in')
        with pool.USE_FIRST_LOCK:
            pool.USE_FIRST[OP]['startedAt'] -= pool.USE_FIRST_LIMIT + 1
        self.wait_state('expired')

    def test_finished_results_are_kept_for_a_while_then_dropped(self):
        self.begin()
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'same'})
        self.wait_state('done')
        self.assertIsNone(pool.use_first_latest(time.time() + pool.USE_FIRST_KEEP + 1))
        self.assertIsNone(self.http('/api/accounts')[1]['useFirst'])

    def test_busy_agent_prefer_is_retried(self):
        self.broker.prefer_409 = 2
        self.begin()
        self.broker.request('claude', '/operations', {'action': 'submit', 'operation': OP, 'code': 'same'})
        self.assertEqual(self.wait_state('done')['credential'], 'b13833')

    def test_refused_requests(self):
        # Only on an add, only for the original login, only while it is still its own row.
        self.assertEqual(self.http('/api/operations', {'action': 'prefer', 'target': '2eaa09', 'confirmed': True, 'useFirst': 'legacy-claude-code'})[0], 400)
        self.assertEqual(self.http('/api/operations', {'action': 'add', 'confirmed': True, 'useFirst': 'oscar-row'})[0], 403)
        self.broker.grant('b13833', 'miguel@example.com')                # already folded: plain Use first applies
        self.assertEqual(self.http('/api/operations', {'action': 'add', 'confirmed': True, 'useFirst': 'legacy-claude-code'})[0], 403)
        self.assertEqual([a for a in self.broker.actions() if a[1] == 'add'], [])
        self.assertEqual(pool.USE_FIRST, {})

    def test_plain_add_has_no_intent(self):
        status, job = self.http('/api/operations', {'action': 'add', 'label': '', 'confirmed': True})
        self.assertEqual(status, 200)
        self.assertNotIn('useFirst', job)
        self.assertIsNone(self.http('/api/accounts')[1]['useFirst'])


if __name__ == '__main__':
    unittest.main()
