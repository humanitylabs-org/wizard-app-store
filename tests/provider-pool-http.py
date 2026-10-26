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
        m.PASSWORD='fixture-password';m.LEGACY=None;m.LEGACY_RENEW=None
        self.management={'contract':'wizard.account-management/1','status':'available'}
        self.calls=[]
        class Fake:
            @staticmethod
            def accounts(provider):return {'owner':'hermes','provider':provider,'name':'Fixture','accounts':[{'id':'fixture','actions':{'remove':True,'reconnect':True},'credentials':[{'id':'aa11bb','managed':True}]}],'actions':{'add':True},'management':self.management}
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
        # No page password (Tailscale-only box): same-origin requests only, and still the exact broker contract.
        m.PASSWORD=''
        self.assertEqual(self.request('/api/operations',{'action':'add','confirmed':True},headers={'X-Wizard-Account-Action':'1','Origin':'https://evil.example','Host':'wizard.example'})[0],403)
        self.assertEqual(self.request('/api/operations',{'action':'add','confirmed':True},headers={'X-Wizard-Account-Action':'1','Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.request('/api/operations',{},headers={'X-Wizard-Account-Action':'1'})[0],403)
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

    def test_capabilities_fail_closed_without_losing_read_only_inventory(self):
        for cap in [None, {}, {'status':'available'}, {'contract':'wizard.account-management/2','status':'available'}, *[{'contract':'wizard.account-management/1','status':s} for s in ['off','blocked','unsupported','unavailable']]]:
            self.management=cap
            self.assertEqual(self.request('/api/accounts')[0],200)
            self.assertEqual(self.request('/api/operations',{'action':'add'},headers={'X-Wizard-Account-Action':'1'})[0],403)
        self.assertEqual(self.calls,[])

    def test_exact_boolean_action_and_managed_target_are_required(self):
        for inventory in [
            {'actions':{'add':'true'},'accounts':[]},
            {'actions':{'add':False},'accounts':[]},
            {'actions':{'add':True},'accounts':[{'actions':{'remove':False},'credentials':[{'id':'aa11bb','managed':True}]}]},
            {'actions':{'add':True},'accounts':[{'actions':{'remove':True},'credentials':[{'id':'aa11bb','managed':'true'}]}]},
        ]:
            m.Hermes.accounts=lambda _, i=inventory:{**i,'management':self.management}
            action='remove' if inventory['accounts'] else 'add'
            self.assertEqual(self.request('/api/operations',{'action':action,'target':'aa11bb'},headers={'X-Wizard-Account-Action':'1'})[0],403)
        self.assertEqual(self.calls,[])

    def test_legacy_expired_preserves_reason_and_renewal_readback(self):
        class Legacy:
            def read(self):return {'status':'expired','usage':None,'error':{'code':'expired','message':'Reconnect through Claude Code'}}
        m.LEGACY=Legacy()
        code,raw,_=self.request('/api/accounts')
        out=json.loads(raw);self.assertEqual(code,200)
        self.assertEqual(next(a for a in out['accounts'] if a['id']=='legacy-claude-code')['error']['code'],'expired')
        seen=[]
        def renew(answer,reader):
            seen.append(reader)
            return {'status':'connected','usage':{'limits':[{'usedPercent':23}]}}
        m.LEGACY_RENEW=renew
        code,raw,_=self.request('/api/accounts')
        self.assertEqual(next(a for a in json.loads(raw)['accounts'] if a['id']=='legacy-claude-code')['usage']['limits'][0]['usedPercent'],23)
        self.assertEqual(seen,[m.LEGACY])

if __name__=='__main__':unittest.main()
