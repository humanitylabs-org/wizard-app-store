"""Exercise the packaged CMD without network or real credential volumes."""
import json
import subprocess
import sys

provider, image = sys.argv[1:]
assert provider in ('chatgpt', 'claude')
prefix='WIZARD_'+provider.upper()
port='8801' if provider=='chatgpt' else '8799'
config=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]['Config']
assert config['Cmd']==['python3','/app/pool_server.py'],config['Cmd']
cid=subprocess.check_output(['docker','run','--rm','-d','--network','none','--read-only','--cap-drop','ALL',
    '--security-opt','no-new-privileges','--memory','128m','--pids-limit','64',
    '-e',prefix+'_PASSWORD=fixture-password',image],text=True).strip()
probe=r'''
import base64,json,time,urllib.request,urllib.error,os
base='http://127.0.0.1:PORT'
auth='Basic '+base64.b64encode(b'owner:fixture-password').decode()
def req(path,body=None,authenticated=True,extra=None):
 h={'Authorization':auth} if authenticated else {}
 if body is not None:h['Content-Type']='application/json'
 h.update(extra or {})
 r=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=h)
 try:
  with urllib.request.urlopen(r,timeout=3) as response:return response.status,response.read()
 except urllib.error.HTTPError as e:
  with e:return e.code,e.read()
for _ in range(100):
 try:
  assert req('/health')[0]==200;break
 except OSError as error:
  last=type(error).__name__+': '+str(error);time.sleep(.1)
else:raise AssertionError('entrypoint failed to listen: '+last)
assert os.getuid()==1000
assert req('/',authenticated=False)[0]==401
for p in ['/','/app.js','/app.css','/SKILL.md','/.well-known/mcp/server-cards.json']:
 assert req(p)[0]==200,p
for p in ['/auth.json','/.credentials.json','/pool_server.py']:
 assert req(p)[0]==404,p
assert req('/api/operations',{'action':'add','confirmed':True},authenticated=False)[0]==401
assert req('/api/operations',{'action':'add','confirmed':True})[0]==403
assert req('/api/operations',{'action':'add','confirmed':True},extra={'X-Wizard-Account-Action':'1','Sec-Fetch-Site':'cross-site'})[0]==403
assert req('/api/connection',extra={'X-Forwarded-For':'1.2.3.4'})[0]==403
assert req('/api/operations',{'action':'add','confirmed':True},extra={'X-Wizard-Account-Action':'1'})[0]==503
print('PASS packaged CMD, uid1000, assets/card, authentication, CSRF, box-only, missing-dashboard fail-closed; network=none, no volumes')
'''.replace('PORT',port)
try:
    subprocess.run(['docker','exec',cid,'python3','-c',probe],check=True,timeout=30)
except Exception:
    subprocess.run(['docker','logs',cid],check=False)
    subprocess.run(['docker','exec',cid,'python3','-c',"import os; print({k:v for k,v in os.environ.items() if k.startswith('WIZARD_POOL')})"],check=False)
    raise
finally:
    subprocess.run(['docker','rm','-f',cid],check=True,stdout=subprocess.DEVNULL)
