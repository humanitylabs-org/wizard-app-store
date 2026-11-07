"""Focused purchased-credit regressions. Synthetic data only; no login files or real network."""
import json
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usage  # noqa: E402

URL = 'https://api.anthropic.com/api/oauth/usage'
ORG = '00000000-0000-0000-0000-000000000001'
PAID = {'enabled': True, 'currency': 'USD', 'exponent': 2}
class Credits(unittest.TestCase):
    def read(self, payload, profile=None):
        with patch.object(usage, 'get_usage', side_effect=[profile or {'organization': {'uuid': ORG}}, payload]) as get:
            answer = usage.credit_balance(URL, 'synthetic-token', PAID, 8)
            self.assertEqual(get.call_args_list[0].args[0], 'https://api.anthropic.com/api/oauth/profile')
            if get.call_count > 1:
                self.assertEqual(get.call_args_list[1].args[0], 'https://api.anthropic.com/api/oauth/organizations/'+ORG+'/prepaid/credits')
            return answer
    def test_actual_balance_not_spend(self):
        self.assertEqual(self.read({'amount': 12345, 'currency': 'USD'}), 12345)
        self.assertEqual(self.read({'amount': 6789, 'currency': 'USD', 'decimal_places': None}), 6789)
        self.assertEqual(self.read({'amount': 123450, 'currency': 'USD', 'decimal_places': 3}), 12345)
    def test_zero_and_negative_are_real(self):
        self.assertEqual(self.read({'amount': 0, 'currency': 'USD'}), 0)
        self.assertEqual(self.read({'amount': -10, 'currency': 'USD'}), -10)
    def test_invalid_is_unknown(self):
        for d in [{'amount': None, 'currency': 'USD'}, {'amount': True, 'currency': 'USD'},
                  {'amount': '12345', 'currency': 'USD'}, {'amount': float('inf'), 'currency': 'USD'},
                  {'amount': 12345, 'currency': 'EUR'}, {'amount': 12345, 'currency': 'USD', 'decimal_places': 7},
                  {'amount': 12345, 'currency': 'USD', 'decimal_places': True}]:
            with self.subTest(payload=d): self.assertIsNone(self.read(d))
    def test_bad_profile_never_used_as_url(self):
        with patch.object(usage, 'get_usage', return_value={'organization': {'uuid': '../private'}}) as get:
            self.assertIsNone(usage.credit_balance(URL, 'synthetic-token', PAID, 8)); self.assertEqual(get.call_count, 1)
    def test_disabled_does_not_fetch(self):
        with patch.object(usage, 'get_usage') as get:
            self.assertIsNone(usage.credit_balance(URL, 'synthetic-token', {**PAID, 'enabled': False}, 8)); get.assert_not_called()
    def test_balance_failure_preserves_weekly_and_redacts_errors(self):
        reader = usage.ConnectionReader('/nonexistent-synthetic', now=lambda: 1800000000)
        reader.plan = 'Max 20x'
        payload = {'seven_day': {'utilization': 37}, 'spend': {'enabled': True, 'used': {'amount_minor': 99999}, 'limit': None}}
        with patch.object(usage, 'get_usage', side_effect=[payload, {'organization': {'uuid': ORG}}, usage.UsageError(usage.EXPIRED)]):
            result = reader._attempt('synthetic-private-token', 1800000000)
        self.assertEqual(result['status'], 'connected'); self.assertEqual(result['usage']['limits'][0]['remainingPercent'], 63)
        self.assertIsNone(result['usage']['paid']['balanceMinor']); self.assertNotIn(ORG, json.dumps(result)); self.assertNotIn('synthetic-private-token', json.dumps(result))
    def test_optional_credit_deadline_never_extends_a_slow_usage_read(self):
        reader = usage.ConnectionReader('/nonexistent-synthetic')
        payload = {'seven_day': {'utilization': 37}, 'spend': {'enabled': True, 'used': {'amount_minor': 99999}, 'limit': None}}
        with patch.object(usage.time, 'monotonic', side_effect=[100, 106]), patch.object(usage, 'get_usage', return_value=payload) as get:
            result = reader._attempt('synthetic-private-token', 1800000000)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(result['usage']['limits'][0]['remainingPercent'], 63)
        self.assertIsNone(result['usage']['paid']['balanceMinor'])
    def test_reader_propagates_balance_and_refreshes_not_screenshot(self):
        reader = usage.ConnectionReader('/nonexistent-synthetic')
        payload = {'seven_day': {'utilization': 37}, 'spend': {'enabled': True, 'used': {'amount_minor': 99999}, 'limit': None}}
        for balance in [12345, 12000]:
            with patch.object(usage, 'get_usage', side_effect=[payload, {'organization': {'uuid': ORG}}, {'amount': balance, 'currency': 'USD'}]):
                result = reader._attempt('synthetic-private-token', 1800000000)
            self.assertEqual(result['usage']['paid']['balanceMinor'], balance)
            self.assertEqual(result['usage']['limits'][0]['remainingPercent'], 63)
if __name__ == '__main__': unittest.main()
