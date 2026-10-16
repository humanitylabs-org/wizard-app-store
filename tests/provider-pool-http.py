"""Loopback HTTP fixtures only. No Hermes, Claude CLI, or credentials mounted."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
import urllib.error

ROOT=Path(__file__).parents[1]/'images/wizard-chatgpt'
sys.path.insert(0,str(ROOT))
os.environ['WIZARD_POOL_PROVIDER']='chatgpt'
spec=importlib.util.spec_from_file_location('pool_server',ROOT/'pool_server.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        m.PASSWORD='fixture-password';m.LEGACY=None
        self.calls=[]
        class Fake:
            @staticmethod
            def accounts(provider):return {'owner':'hermes','provider':provider,'name':'Fixture','accounts':[]}
            @staticmethod
            def request(provider,suffix,body=None):
                self.calls.append((provider,suffix,body))
                return {'id':'fixtureabcdefghijklmnop','status':'running'}
        m.Hermes=Fake
        self.server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,body=None,auth=True,headers=None):
        h={'Authorization':'Basic '+base64.b64encode(b'owner:fixture-password').decode()} if auth else {}
        h.update(headers or {})
        if body is not None:h['Content-Type']='application/json'
        req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,data=None if body is None else json.dumps(body).encode(),headers=h)
        try:
            with urllib.request.urlopen(req,timeout=3) as r:return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e:
            with e:return e.code,e.read(),e.headers
    def test_auth_and_csrf_before_bridge(self):
        self.assertEqual(self.request('/api/operations',{},auth=False)[0],401)
        self.assertEqual(self.request('/api/operations',{})[0],403)
        self.assertEqual(self.request('/api/operations',{},headers={'X-Wizard-Account-Action':'1','Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.calls,[])
    def test_narrow_proxy_and_cache(self):
        body={'action':'remove','target':'aa11bb','confirmed':True}
        code,_,headers=self.request('/api/operations',body,headers={'X-Wizard-Account-Action':'1'})
        self.assertEqual(code,200);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.calls,[('chatgpt','/operations',body)])
        self.assertEqual(self.request('/api/logout',{},headers={'X-Wizard-Account-Action':'1'})[0],404)
    def test_password_missing_fails_closed(self):
        m.PASSWORD=''
        self.assertEqual(self.request('/api/operations',{},headers={'X-Wizard-Account-Action':'1'})[0],503)
        self.assertEqual(self.calls,[])
    def test_box_only_connection_and_static_files(self):
        self.assertEqual(self.request('/api/connection',headers={'X-Forwarded-For':'1.2.3.4'})[0],403)
        for path in ['/','/app.js','/app.css','/SKILL.md','/.well-known/mcp/server-cards.json']:self.assertEqual(self.request(path)[0],200)
        for path in ['/auth.json','/pool_server.py','/.credentials.json']:self.assertEqual(self.request(path)[0],404)
    def test_legacy_claude_visible_without_hermes_and_no_mutation(self):
        class Legacy:
            def read(self):return {'status':'connected','plan':'Max 20x','usage':{'limits':[]}}
        m.LEGACY=Legacy()
        m.Hermes.accounts=lambda provider: (_ for _ in ()).throw(RuntimeError('fake outage'))
        code,raw,_=self.request('/api/accounts');self.assertEqual(code,200)
        out=json.loads(raw);self.assertEqual(out['accounts'][0]['id'],'legacy-claude-code')
        self.assertEqual(out['accounts'][0]['plan'],'Max 20x');self.assertEqual(out['inventoryStatus'],'unavailable')
        self.assertFalse(out['accounts'][0]['actions']['remove']);self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
