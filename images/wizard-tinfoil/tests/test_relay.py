"""Relay boundary tests; real enclave proof is tests/live_relay.py."""
import contextlib
import hashlib
import http.client
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('relay_server_tests', ROOT/'app/server.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        s.DATA = Path(self.temp.name)
        s.initialize()
        self.env = patch.dict(os.environ, {'WIZARD_SWITCHES_DIR': self.temp.name})
        self.env.start()
        self.set_switch(True)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def set_switch(self, on):
        (Path(self.temp.name)/'switches.json').write_text(json.dumps({'private-relay': on}))

    def test_switch_declared_off_by_default_with_issue(self):
        (Path(self.temp.name)/'switches.json').unlink()
        sw = next(x for x in s.switches_doc()['switches'] if x['id'] == 'private-relay')
        self.assertFalse(sw['default']); self.assertFalse(sw['on'])
        self.assertEqual(sw['issues'], ['humanitylabs-org/wizard-tinfoil#2'])
        self.assertFalse(s.relay_on())

    def test_switch_off_tokens_never_admitted(self):
        token = s.private_client('agent-one')['token']
        self.assertTrue(s.private_token_ok(token))
        self.set_switch(False)
        self.assertFalse(s.private_token_ok(token))

    def test_token_rotate_revoke_restart_hash_only(self):
        first = s.private_client('agent-one')
        self.assertGreaterEqual(len(first['token']), 43)
        self.assertEqual(first['relay_url'], 'http://wizard-tinfoil-relay:8090')
        self.assertTrue(s.private_token_ok(first['token']))
        data = (s.DATA/'private-clients.json').read_text()
        self.assertNotIn(first['token'], data)
        self.assertIn(hashlib.sha256(first['token'].encode()).hexdigest(), data)
        self.assertEqual((s.DATA/'private-clients.json').stat().st_mode & 0o777, 0o600)
        second = s.private_client('agent-one')
        self.assertFalse(s.private_token_ok(first['token']))
        self.assertTrue(s.private_token_ok(second['token']))
        other_spec = importlib.util.spec_from_file_location('restarted_relay_server', ROOT/'app/server.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        other.DATA = s.DATA
        self.assertTrue(other.private_token_ok(second['token']))
        s.revoke_private_client('agent-one')
        s.revoke_private_client('agent-one')
        self.assertFalse(s.private_token_ok(second['token']))
        for bad in ('', '../oops', 'a/b', 'a'*129):
            with self.assertRaises(ValueError): s.private_client(bad)

    def test_actual_subnet_not_entire_pool(self):
        r = s.relay
        with patch.object(r, 'interface_networks', return_value=[ipaddress.ip_network('10.252.4.0/24')]):
            self.assertTrue(r.peer_allowed('10.252.4.10'))
            for ip in ('10.252.5.10', '127.0.0.1', '100.64.1.1', '::1', 'invalid'):
                self.assertFalse(r.peer_allowed(ip))
        with patch.object(r, 'interface_networks', return_value=[]):
            self.assertFalse(r.peer_allowed('10.252.4.10'))
        self.assertTrue(all(n.subnet_of(ipaddress.ip_network('10.252.0.0/16')) for n in r.interface_networks()))

    def test_multiple_agent_subnets_are_admitted_but_not_the_pool(self):
        with patch.object(s.relay, 'interface_networks', return_value=[ipaddress.ip_network('10.252.4.0/24'),ipaddress.ip_network('10.252.5.0/24')]):
            self.assertTrue(s.relay.peer_allowed('10.252.4.3'))
            self.assertTrue(s.relay.peer_allowed('10.252.5.3'))
            self.assertFalse(s.relay.peer_allowed('10.252.6.3'))

    def test_management_refuses_relay_peer_even_with_owner_headers(self):
        handler = object.__new__(s.Handler)
        handler.client_address = ('10.252.4.3', 1234)
        handler.headers = {'Host':'localhost:18804','Origin':'http://localhost:18804','X-Wizard-Request':'1'}
        with patch.object(handler, 'send') as send:
            self.assertTrue(handler.refused('/api/private-clients', True))
            self.assertEqual(send.call_args.args[0], 403)
        handler.headers = {'Host': f'localhost:{s.PORT}'}
        with patch.object(handler, 'send'):
            self.assertTrue(handler.refused('/healthz'))
        self.set_switch(False)  # off: today's management behaviour, unchanged
        with patch.object(handler, 'send'):
            self.assertFalse(handler.refused('/healthz'))

    def test_strict_enclave_origin(self):
        for good in ('https://inference.tinfoil.sh', 'https://enclave-1.tinfoil.sh/', 'https://a.b.tinfoil.sh:443'):
            self.assertTrue(s.relay.enclave_host(good).endswith('.tinfoil.sh'))
        for bad in ('http://inference.tinfoil.sh', 'https://tinfoil.sh', 'https://evil.tinfoil.sh.evil.com', 'https://x.tinfoil.sh@evil.com', 'https://user@x.tinfoil.sh', 'https://x.tinfoil.sh:444', 'https://x.tinfoil.sh/path', 'https://x.tinfoil.sh/?x', 'https://x.tinfoil.sh/#x', 'https://-x.tinfoil.sh', 'https://x.tinfoil.sh\r\nX: y', 'https://127.0.0.1'):
            with self.assertRaises(ValueError, msg=bad): s.relay.enclave_host(bad)

    def test_http_guards_headers_streaming_and_no_logs(self):
        token = s.private_client('probe')['token']
        s.atomic('connection.json', {'key': 'synthetic-provider-key'})
        upstream = io.BytesIO(b'encrypted-response')
        class Response:
            status = 200
            def getheaders(self): return [('Content-Type', 'application/octet-stream'), ('Ehbp-Response-Nonce', 'nonce'), ('Set-Cookie', 'must-not-forward')]
            def read1(self, n): return upstream.read(n)
        calls = []
        class Connection:
            def __init__(self, host, **kwargs): calls.append(('host', host))
            def putrequest(self, method, path): calls.append(('request', method, path))
            def putheader(self, k, v): calls.append(('header', k.lower(), v))
            def endheaders(self): pass
            def send(self, data): calls.append(('body', data))
            def getresponse(self): return Response()
            def close(self): pass
        http = s.relay.make_server(('127.0.0.1', 0), s.private_token_ok, s.stored, s.relay_on)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        def call(path, method='GET', body=None, headers=None):
            c = http_module.HTTPConnection('127.0.0.1', http.server_port, timeout=3)
            c.request(method, path, body=body, headers=headers or {})
            response = c.getresponse(); result = (response.status, dict(response.getheaders()), response.read()); c.close(); return result
        http_module = __import__('http.client', fromlist=['HTTPConnection'])
        log = io.StringIO()
        try:
            self.set_switch(False)
            with contextlib.redirect_stderr(log), patch.object(s.relay, 'peer_allowed', return_value=True), patch.object(s.relay.http.client, 'HTTPSConnection', Connection):
                self.assertEqual(call('/healthz')[0], 404)
                self.assertEqual(call('/attestation', headers={'Authorization':'Bearer '+token})[0], 404)
                self.assertEqual(call('/v1/chat/completions','POST', b'ciphertext', {'Authorization': 'Bearer '+token, 'X-Tinfoil-Enclave-Url':'https://inference.tinfoil.sh', 'Ehbp-Encapsulated-Key':'k'})[0], 404)
            self.assertEqual(calls, [])
            self.set_switch(True)
            with contextlib.redirect_stderr(log), patch.object(s.relay, 'peer_allowed', return_value=False):
                self.assertEqual(call('/healthz')[0], 403)
            with contextlib.redirect_stderr(log), patch.object(s.relay, 'peer_allowed', return_value=True), patch.object(s.relay.http.client, 'HTTPSConnection', Connection):
                self.assertEqual(call('/healthz')[0], 200)
                self.assertEqual(call('/attestation')[0], 401)
                self.assertEqual(call('/attestation', headers={'Authorization':'Bearer '+'x'*64})[0],401)
                headers = {'Authorization': 'Bearer '+token, 'X-Tinfoil-Enclave-Url':'https://inference.tinfoil.sh', 'Ehbp-Encapsulated-Key':'encapsulated', 'Content-Type':'application/octet-stream', 'Cookie':'secret-cookie'}
                self.assertEqual(call('/v1/chat/completions','POST', b'ciphertext', headers)[0], 200)
                self.assertIn(('header','ehbp-encapsulated-key','encapsulated'), calls)
                self.assertIn(('header','authorization','Bearer synthetic-provider-key'), calls)
                self.assertNotIn(token, repr(calls))
                self.assertNotIn('secret-cookie', repr(calls))
                upstream.seek(0)
                code, h, body = call('/v1/responses', 'POST', iter([b'cipher', b'text']), headers)
                self.assertEqual(code, 200); self.assertEqual(body,b'encrypted-response')
                self.assertEqual(h['Ehbp-Response-Nonce'], 'nonce'); self.assertNotIn('Set-Cookie', h)
                self.assertEqual(b''.join(x[1] for x in calls if x[0]=='body'), b'ciphertext6\r\ncipher\r\n4\r\ntext\r\n0\r\n\r\n')
                headers['X-Tinfoil-Enclave-Url']='https://evil.invalid'
                self.assertEqual(call('/v1/chat/completions','POST',b'PRIVPROBE-unit',headers)[0],400)
                self.assertEqual(call('/attestation', headers={'Authorization':'Bearer '+token})[0],200)
                self.assertIn(('request','POST','/attestation'),calls)
                self.assertIn(('body',b'{"enclaveUrl":"https://inference.tinfoil.sh","repo":"tinfoilsh/confidential-model-router"}'),calls)
                headers['X-Tinfoil-Enclave-Url']='https://inference.tinfoil.sh'
                (s.DATA/'connection.json').unlink()
                self.assertEqual(call('/v1/chat/completions','POST',b'ciphertext',headers)[0],503)
                s.atomic('connection.json', {'key':'synthetic-provider-key'})
                with patch.object(Connection, 'getresponse', side_effect=OSError('PRIVPROBE-do-not-log')):
                    self.assertEqual(call('/v1/chat/completions','POST',b'ciphertext',headers)[0],502)
            self.assertEqual(log.getvalue(), '')
            self.assertNotIn('PRIVPROBE-unit', ''.join(p.read_text() for p in s.DATA.iterdir()))
        finally:
            http.shutdown(); http.server_close()

    def test_owner_write_route_protection(self):
        http = s.ThreadingHTTPServer(('127.0.0.1',0), s.Handler)
        base = f'http://127.0.0.1:{http.server_port}'
        s.HOSTS.add(f'127.0.0.1:{http.server_port}'); s.ORIGINS.add(base)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        def call(method, path, headers, body=None):
            c = http_client.HTTPConnection('127.0.0.1', http.server_port)
            c.request(method,path,body=body,headers=headers)
            r = c.getresponse(); result=(r.status, r.read()); c.close(); return result
        http_client = __import__('http.client', fromlist=['HTTPConnection'])
        try:
            valid={'Origin':base,'X-Wizard-Request':'1','Content-Type':'application/json'}
            self.set_switch(False)
            self.assertEqual(call('POST','/api/private-clients',valid,'{"agent":"probe"}')[0],404)
            self.assertEqual(call('DELETE','/api/private-clients/probe',valid)[0],404)
            self.assertFalse((s.DATA/'private-clients.json').exists())
            self.set_switch(True)
            for bad in ({}, {**valid,'Origin':'https://evil.invalid'}, {**valid,'Host':'evil.invalid'}, {**valid,'X-Wizard-Request':''}, {**valid,'Sec-Fetch-Site':'cross-site'}, {**valid,'X-Forwarded-For':'10.252.4.10'}):
                self.assertEqual(call('POST','/api/private-clients',bad,'{"agent":"probe"}')[0],403)
                self.assertEqual(call('DELETE','/api/private-clients/probe',bad)[0],403)
            code, body=call('POST','/api/private-clients',valid,'{"agent":"probe"}')
            self.assertEqual(code,200); token=json.loads(body)['token']
            self.assertTrue(s.private_token_ok(token))
            self.assertEqual(call('DELETE','/api/private-clients/probe',valid)[0],204)
            self.assertFalse(s.private_token_ok(token))
            self.assertEqual(call('POST','/api/private-clients',valid,'{"agent":"../x"}')[0],400)
            self.assertEqual(call('POST','/api/private-clients',valid,'{"agent":"probe","extra":1}')[0],400)
        finally:
            http.shutdown(); http.server_close()


if __name__ == '__main__': unittest.main()
