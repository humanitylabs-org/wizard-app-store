import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('relay_proxy_test', Path(__file__).parents[1] / 'app/relay.py')
relay = importlib.util.module_from_spec(spec); spec.loader.exec_module(relay)
class ProxyTests(unittest.TestCase):
    def test_explicit_connect_target_and_tls_upstream(self):
        with patch.dict(os.environ, {'HTTPS_PROXY':'http://wizard-egress-proxy:3128'}, clear=True), patch.object(relay.http.client, 'HTTPSConnection') as cls:
            value = relay.upstream_connection('inference.tinfoil.sh')
            cls.assert_called_once_with('wizard-egress-proxy',3128,timeout=180)
            value.set_tunnel.assert_called_once_with('inference.tinfoil.sh',443)
    def test_no_proxy_legacy_and_bad_proxy_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(relay.http.client, 'HTTPSConnection') as cls:
            relay.upstream_connection('inference.tinfoil.sh')
            cls.assert_called_once_with('inference.tinfoil.sh',timeout=180)
        for bad in ('https://proxy:3128','http://user:password@proxy:3128','http://proxy:3128/path'):
            with patch.dict(os.environ, {'HTTPS_PROXY':bad}, clear=True), self.assertRaises(ValueError):
                relay.upstream_connection('inference.tinfoil.sh')
if __name__=='__main__': unittest.main()
