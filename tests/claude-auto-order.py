"""Claude automatic order (soonest reset first), duplicate-row folding. Fake inventories only: no CLI, no provider."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'images/wizard-claude'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
owner = importlib.util.module_from_spec(spec)
sys.modules['server'] = owner
spec.loader.exec_module(owner)
with patch.dict(os.environ, {'WIZARD_POOL_PROVIDER': 'claude'}):
    spec = importlib.util.spec_from_file_location('claude_pool_order', os.environ.get('POOL_SERVER', ROOT / 'pool_server.py'))
    pool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pool)

MANAGEMENT = {'contract': 'wizard.account-management/1', 'status': 'available'}
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc).timestamp()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def acct(id, cred, priority, weekly_reset, used=30, prefer=True, status='ready', session=None, fetched=NOW - 30, **extra):
    limits = [{'id': 'weekly_all:weekly', 'usedPercent': used, 'remainingPercent': 100 - used, 'resetsAt': iso(weekly_reset)},
              {'id': 'weekly_scoped:Fable', 'usedPercent': 100, 'remainingPercent': 0, 'resetsAt': iso(weekly_reset)}]
    if session is not None:
        limits.append({'id': 'session:all', 'usedPercent': session[0], 'remainingPercent': 100 - session[0], 'resetsAt': iso(session[1])})
    return {'id': id, 'name': id, 'status': status, 'priority': priority, 'preferred': priority == 0,
            'usage': {'fetchedAt': iso(fetched), 'limits': limits},
            'credentials': [{'id': cred, 'name': id, 'managed': prefer, 'priority': priority}],
            'actions': {'prefer': prefer, 'reconnect': prefer, 'remove': prefer}, **extra}


def inventory(*rows):
    return {'owner': 'hermes', 'provider': 'claude', 'accounts': list(rows), 'actions': {'add': True}, 'management': dict(MANAGEMENT)}


H = 3600
D = 86400


class OrderPlan(unittest.TestCase):
    def live(self):
        # The live box on 2 Nov 2026: the original Claude Code login (seeded, Hermes keeps it behind added grants)
        # resets at 14:00Z today; the added oscar grant resets on 7 Nov and is first.
        legacy = acct('legacy-claude-code', 'bd6a0f', 1, NOW + 8 * H, used=50, prefer=False, source='legacy-claude-code', status='connected')
        oscar = acct('oscar-row', '2eaa09', 0, NOW + 5 * D + 12 * H, used=23)
        return legacy, oscar

    def test_live_case_soonest_is_the_seeded_login_so_it_needs_one_sign_in(self):
        plan = pool.order_plan(inventory(*self.live()), NOW)
        self.assertEqual((plan['status'], plan['wanted'], plan['needsSignIn'], plan['moves']),
                         ('blocked', 'legacy-claude-code', True, []))
        self.assertEqual(plan['order'], ['legacy-claude-code', 'oscar-row'])

    def test_live_case_after_the_reset_oscar_leads_and_nothing_changes(self):
        legacy, oscar = self.live()
        later = NOW + 8 * H + 5 * 60
        legacy = acct('legacy-claude-code', 'bd6a0f', 1, later + 7 * D, used=0, prefer=False, status='connected', fetched=later - 20)
        oscar['usage']['fetchedAt'] = iso(later - 20)
        plan = pool.order_plan(inventory(legacy, oscar), later)
        self.assertEqual((plan['status'], plan['wanted'], plan['needsSignIn'], plan['moves']), ('ok', 'oscar-row', False, []))

    def test_a_passed_reset_without_a_fresh_reading_changes_nothing(self):
        legacy, oscar = self.live()
        plan = pool.order_plan(inventory(legacy, oscar), NOW + 8 * H + 10 * 60)
        self.assertEqual(plan['status'], 'waiting')

    def test_two_added_accounts_soonest_reset_moves_first(self):
        a = acct('a', 'ca', 0, NOW + 5 * D)
        b = acct('b', 'cb', 1, NOW + 1 * D)
        plan = pool.order_plan(inventory(a, b), NOW)
        self.assertEqual((plan['status'], plan['wanted'], plan['moves'], plan['needsSignIn']), ('reorder', 'b', ['cb'], False))

    def test_exhausted_soonest_goes_last_and_session_limit_counts(self):
        a = acct('a', 'ca', 0, NOW + 5 * D)
        b = acct('b', 'cb', 1, NOW + 1 * D, used=100)
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['status'], 'ok')
        b = acct('b', 'cb', 1, NOW + 1 * D, session=(100, NOW + 2 * H))
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['order'], ['a', 'b'])
        # The leader hits its session limit: the other account takes over until that resets.
        a = acct('a', 'ca', 0, NOW + 1 * D, session=(100, NOW + 2 * H))
        b = acct('b', 'cb', 1, NOW + 5 * D)
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['moves'], ['cb'])
        # A model-scoped weekly meter at 100% (weekly_scoped) never stops an account.
        self.assertEqual(pool.order_plan(inventory(acct('a', 'ca', 0, NOW + 5 * D), acct('b', 'cb', 1, NOW + D)), NOW)['wanted'], 'b')

    def test_missing_or_stale_usage_changes_nothing(self):
        a = acct('a', 'ca', 0, NOW + 5 * D)
        b = acct('b', 'cb', 1, NOW + 1 * D, fetched=NOW - 3600)
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['status'], 'waiting')
        b = acct('b', 'cb', 1, NOW + 1 * D)
        b['usage'] = None
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['status'], 'waiting')
        b = acct('b', 'cb', 1, NOW + 1 * D)
        bad = inventory(a, b)
        bad['management'] = {'status': 'off'}
        self.assertEqual(pool.order_plan(bad, NOW)['status'], 'waiting')
        bad = inventory(a, b)
        bad['inventoryStatus'] = 'unavailable'
        self.assertEqual(pool.order_plan(bad, NOW)['status'], 'waiting')

    def test_signed_out_account_goes_last_without_blocking(self):
        a = acct('a', 'ca', 0, NOW + 5 * D)
        b = acct('b', 'cb', 1, NOW + 1 * D, status='expired')
        b['usage'] = None
        plan = pool.order_plan(inventory(a, b), NOW)
        self.assertEqual((plan['status'], plan['order']), ('ok', ['a', 'b']))

    def test_millisecond_reset_jitter_and_ties_keep_the_current_order(self):
        a = acct('a', 'ca', 0, NOW + 5 * D + 0.7)
        b = acct('b', 'cb', 1, NOW + 5 * D + 0.2)
        self.assertEqual(pool.order_plan(inventory(a, b), NOW)['status'], 'ok')

    def test_three_accounts_fewest_moves(self):
        a, b, c = acct('a', 'ca', 0, NOW + 3 * D), acct('b', 'cb', 1, NOW + 4 * D), acct('c', 'cc', 2, NOW + D)
        self.assertEqual(pool.order_plan(inventory(a, b, c), NOW)['moves'], ['cc'])
        a, b, c = acct('a', 'ca', 0, NOW + 5 * D), acct('b', 'cb', 1, NOW + D), acct('c', 'cc', 2, NOW + 2 * D)
        self.assertEqual(pool.order_plan(inventory(a, b, c), NOW)['moves'], ['cc', 'cb'])

    def test_one_account_is_left_alone(self):
        self.assertEqual(pool.order_plan(inventory(acct('a', 'ca', 0, NOW + D)), NOW)['status'], 'ok')


class Apply(unittest.TestCase):
    def setUp(self):
        self.rows = [acct('a', 'ca', 0, NOW + 5 * D), acct('b', 'cb', 1, NOW + 1 * D)]
        self.calls = []
        test = self

        class FakeHermes:
            @staticmethod
            def accounts(provider):
                return inventory(*[json.loads(json.dumps(r)) for r in test.rows])

            @staticmethod
            def request(provider, suffix, body=None):
                test.calls.append((suffix, body))
                if body and body.get('action') == 'prefer':
                    for r in test.rows:
                        r['priority'] = 0 if r['credentials'][0]['id'] == body['target'] else r['priority'] + 1
                    return {'id': 'operationabcdefghijklmnop', 'status': 'running', 'action': 'prefer'}
                return {'id': 'operationabcdefghijklmnop', 'status': 'succeeded', 'action': 'prefer'}

        for p in (patch.object(pool, 'Hermes', FakeHermes), patch.object(pool, 'LEGACY', None),
                  patch.object(pool, 'AUTO_ORDER', True), patch.object(pool.time, 'time', return_value=NOW),
                  patch.object(pool.time, 'sleep', return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        pool.AUTO_STATE.update(lastRun=0.0, changedAt=None, lastChange=None)

    def test_reorders_once_then_leaves_it(self):
        plan = pool.auto_order(force=True)
        self.assertEqual(plan['moves'], ['cb'])
        self.assertEqual([c[1]['target'] for c in self.calls if c[1]], ['cb'])
        self.assertEqual(self.calls[1][0], '/operations/operationabcdefghijklmnop')
        self.assertIsNotNone(pool.AUTO_STATE['lastChange'])
        self.calls.clear()
        self.assertEqual(pool.auto_order(force=True)['status'], 'ok')
        self.assertEqual(self.calls, [])
        # Rate limit: an unforced run right after does nothing.
        self.assertIsNone(pool.auto_order())

    def test_off_switch_and_failures_change_nothing(self):
        with patch.object(pool, 'AUTO_ORDER', False):
            self.assertIsNone(pool.auto_order(force=True))
        self.assertEqual(self.calls, [])

        def boom(*a, **k):
            raise pool.BridgeError(409, 'busy')
        with patch.object(pool.Hermes, 'request', boom):
            self.assertIsNone(pool.auto_order(force=True))
        self.assertEqual(self.rows[0]['priority'], 0)

    def test_next_check_follows_the_next_reset(self):
        result = inventory(acct('a', 'ca', 0, NOW + 5 * 60))
        self.assertEqual(pool._next_wait(result, NOW), 5 * 60 + 90)
        self.assertEqual(pool._next_wait(inventory(acct('a', 'ca', 0, NOW + 5 * D)), NOW), pool.AUTO_EVERY)


class Fold(unittest.TestCase):
    def test_same_email_hash_is_one_row_with_both_sign_ins(self):
        a = acct('main', '2eaa09', 0, NOW + 5 * D, emailHash='e56b')
        dup = acct('dup', '4641e0', 2, NOW + 5 * D, emailHash='e56b', status='ready')
        other = acct('other', 'bd6a0f', 1, NOW + D, emailHash='aaaa')
        out = pool.fold_same_email([dup, other, a])
        self.assertEqual(len(out), 2)
        row = [r for r in out if r.get('emailHash') == 'e56b'][0]
        self.assertEqual([c['id'] for c in row['credentials']], ['2eaa09', '4641e0'])
        self.assertEqual((row['priority'], row['preferred'], row['credentialCount']), (0, True, 2))
        self.assertTrue(row['actions']['prefer'])
        with patch.object(pool, 'PROVIDER', 'chatgpt'):
            self.assertEqual(len(pool.fold_same_email([dup, other, a])), 3)

    def test_legacy_login_plus_two_grants_of_another_account_is_two_rows(self):
        class Legacy:
            def read(self):
                return {'status': 'connected', 'account': 'miguel@example.com', 'plan': 'Max 20x', 'usage': {'limits': []}}
        result = inventory(acct('main', '2eaa09', 0, NOW + 5 * D, emailHash='e56b'),
                           acct('dup', '4641e0', 2, NOW + 5 * D, emailHash='e56b'),
                           acct('mirror', 'bd6a0f', 1, NOW + D, prefer=False, mirror='claude-code'))
        result['identity'] = {'emailHash': 'sha256-16'}
        with patch.object(pool, 'LEGACY', Legacy()), patch.object(pool, 'LEGACY_RENEW', None):
            out = pool.with_legacy(result)
        self.assertEqual([a['id'] for a in out['accounts']], ['legacy-claude-code', 'main'])
        self.assertEqual(out['accountCount'], 2)


class Http(unittest.TestCase):
    def test_accounts_page_reports_the_automatic_order(self):
        legacy = acct('mirror', 'bd6a0f', 1, NOW + 8 * H, used=50, prefer=False, mirror='claude-code')
        oscar = acct('oscar-row', '2eaa09', 0, NOW + 5 * D, emailHash='e56b')

        class Legacy:
            def read(self):
                return {'status': 'connected', 'account': 'miguel@example.com', 'plan': 'Max 20x',
                        'usage': {'fetchedAt': iso(NOW - 10), 'limits': [{'id': 'weekly_all:weekly', 'usedPercent': 50, 'remainingPercent': 50, 'resetsAt': iso(NOW + 8 * H)}]}}

        class FakeHermes:
            @staticmethod
            def accounts(provider):
                r = inventory(json.loads(json.dumps(legacy)), json.loads(json.dumps(oscar)))
                r['identity'] = {'emailHash': 'sha256-16'}
                return r

            @staticmethod
            def request(provider, suffix, body=None):
                raise AssertionError('no change expected')

        for p in (patch.object(pool, 'Hermes', FakeHermes), patch.object(pool, 'LEGACY', Legacy()),
                  patch.object(pool, 'LEGACY_RENEW', None), patch.object(pool, 'PASSWORD', ''), patch.object(pool, 'AUTO_ORDER', True),
                  patch.object(pool.time, 'time', return_value=NOW), patch.object(owner.inference, 'models', return_value=[]),
                  patch.dict(os.environ, {'WIZARD_CLAUDE_AUTO_RENEW': '0'})):
            p.start()
            self.addCleanup(p.stop)
        http = pool.Server(('127.0.0.1', 0), pool.Handler)
        threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .01}, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        with urllib.request.urlopen('http://127.0.0.1:%d/api/accounts' % http.server_port, timeout=10) as res:
            data = json.load(res)
        self.assertEqual([a['id'] for a in data['accounts']], ['legacy-claude-code', 'oscar-row'])
        auto = data['autoOrder']
        self.assertEqual((auto['enabled'], auto['rule'], auto['status'], auto['wanted'], auto['needsSignIn']),
                         (True, 'soonest-reset-first', 'blocked', 'legacy-claude-code', True))


if __name__ == '__main__':
    unittest.main()
