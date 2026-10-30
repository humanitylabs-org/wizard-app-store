"""Private Tinfoil connection. Secrets never enter MCP, URLs or logs."""
import datetime
import hmac
import json
import re
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import http.cookiejar
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('DATA_DIR', ROOT / '.data'))
PORT = os.environ.get('PORT', '18803')
LOCK = threading.RLock()
TYPES = {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript'}
def csv(k): return {v.strip().lower() for v in os.environ.get(k,'').split(',') if v.strip()}
HOSTS = csv('WIZARD_TRUSTED_HOSTS') | {f'127.0.0.1:{PORT}',f'localhost:{PORT}',f'wizard-tinfoil:{PORT}'}
APP_PORT = os.environ.get('APP_PORT') or PORT
HOSTS |= {f'127.0.0.1:{APP_PORT}', f'localhost:{APP_PORT}'}
ORIGINS = csv('WIZARD_TRUSTED_ORIGINS') | {'http://'+h for h in HOSTS if h.startswith(('localhost:','127.0.0.1:'))}

# The agent on this box (Hermes). Fresh installs reach the Hermes Agent app by name; alongside boxes get the host
# dashboard address from the App Manager. Connect registers this app's local gateway as a Hermes custom provider:
# Hermes gets only the box-only gateway bearer, never the Tinfoil key, and a model it already has is never changed.
DEFAULT_HERMES = 'http://hermes-agent:9119'
HERMES_URL = (os.environ.get('WIZARD_TINFOIL_HERMES_URL') or DEFAULT_HERMES).rstrip('/')
HERMES_USER = os.environ.get('HERMES_DASHBOARD_BASIC_AUTH_USERNAME') or 'hermes'
HERMES_PASSWORD = os.environ.get('HERMES_DASHBOARD_BASIC_AUTH_PASSWORD', '')
AGENT_BASE = os.environ.get('WIZARD_TINFOIL_AGENT_URL') or (f'http://wizard-tinfoil:{PORT}/v1' if HERMES_URL == DEFAULT_HERMES else f'http://127.0.0.1:{APP_PORT}/v1')
ENDPOINT_ID = 'wizard-tinfoil'
# Tinfoil also serves embeddings, speech and tools; only chat models belong in the agent's model list.
NOT_CHAT = ('embed', 'tts', 'whisper', 'voxtral', 'doc-upload', 'pii-filter', 'websearch', 'safeguard')
# The owner's private model is the newest Kimi Tinfoil serves (kimi-k3 today; kimi-k3-1 / kimi-k3.1 the day it lands),
# then the rest best first by the Hermes Index (portal.nousresearch.com/bench, 20 Oct 2026). The top REGISTERED become
# the agent's private choices, first one the default.
PREFERRED = ('glm-5-3', 'deepseek-v4-1-flash', 'gpt-oss-120b', 'llama3-3-70b')
KIMI = re.compile(r'^kimi-k(\d+)(?:[.-](\d+))?(-pro)?$')
REGISTERED = 2
MODEL_REFRESH = int(os.environ.get('WIZARD_TINFOIL_MODEL_REFRESH','21600'))  # re-read Tinfoil's catalogue every 6 h
def chat_models(models): return [m for m in models if not any(x in m for x in NOT_CHAT)]
def kimi_version(m):
    k = KIMI.match(m); return (int(k[1]), int(k[2] or 0), bool(k[3])) if k else None
def ranked(models):
    chat = chat_models(models)
    kimis = sorted((m for m in chat if kimi_version(m)), key=kimi_version, reverse=True)
    return (kimis[:1] + [m for m in PREFERRED if m in chat]) or chat[:1]

def atomic(name, obj):
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA,0o700)
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix='.pending-')
    try:
        with os.fdopen(fd,'w') as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(obj,f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, DATA/name)
        d = os.open(DATA,os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def stored():
    try: return json.loads((DATA/'connection.json').read_text())
    except FileNotFoundError: return None

def agent_call(method, path, body=None):
    """One signed-in call to the agent's dashboard. Errors never carry credentials."""
    if not HERMES_PASSWORD: raise RuntimeError('agent dashboard login missing')
    jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(HERMES_URL+'/auth/password-login', data=json.dumps({'provider':'basic','username':HERMES_USER,'password':HERMES_PASSWORD}).encode(), method='POST', headers={'Content-Type':'application/json'})
    with op.open(login, timeout=20) as r: r.read()
    req = urllib.request.Request(HERMES_URL+path, data=None if body is None else json.dumps(body).encode(), method=method, headers={'Content-Type':'application/json'} if body is not None else {})
    with op.open(req, timeout=40) as r: return json.loads(r.read() or b'{}')

def register(models):
    """Add (or refresh) Tinfoil in the agent's model list. Returns 'registered' or 'unavailable'."""
    picked = ranked(models)[:REGISTERED]
    if not picked: return 'unavailable'
    model = picked[0]
    token = json.loads((DATA/'gateway-token.json').read_text())['token']
    try:
        # A fresh Wizard's agent starts with no model: Tinfoil chosen in the Welcome must be the model it chats with,
        # or its first message fails ("no model configured"). A model the owner (or another app) chose is never changed.
        try: first = not (agent_call('GET', '/api/model/info') or {}).get('provider')
        except Exception: first = False
        agent_call('POST', '/api/providers/custom-endpoints', {'id':ENDPOINT_ID,'name':'Tinfoil','base_url':AGENT_BASE,'model':model,'models':picked,'api_key':token,'api_mode':'chat_completions','discover_models':False,'make_default':first})
        return 'registered'
    except Exception:
        return 'unavailable'

# Apps on this box (e.g. Search's AI overviews) can use the same private gateway when the owner turns that on from
# the app's own page. Each app gets its own box-only token (app-tokens.json, 0600): the Tinfoil key never leaves
# this app, the agent's token is unchanged, and Remove here (or Turn off in the app) revokes it at once.
APP_ID = re.compile(r'^[a-z0-9][a-z0-9-]{1,40}$')
APP_BASE = f'http://wizard-tinfoil:{PORT}/v1'
def app_tokens():
    try: return json.loads((DATA/'app-tokens.json').read_text())
    except FileNotFoundError: return {}
def bearer_ok(header):
    gateway=json.loads((DATA/'gateway-token.json').read_text())['token']
    ok=hmac.compare_digest(header,'Bearer '+gateway)
    for t in app_tokens().values(): ok=hmac.compare_digest(header,'Bearer '+t['token']) or ok
    return ok

def unregister():
    try: agent_call('DELETE', f'/api/providers/custom-endpoints/{ENDPOINT_ID}')
    except Exception: pass


# Billing (optional second key). The owner pastes a Tinfoil *admin* key on this app's page; it lives only in
# admin.json (0600) and is used for exactly two read-only calls: usage cost and transaction history. It is never
# used to create, change or delete keys, never returned by any route, and never reaches the agent or MCP.
ADMIN_API = 'https://api.tinfoil.sh'
BILLING_TTL = 300
BILL = {'at': 0.0, 'data': None, 'error': None}
STARTING_CREDIT_MINOR = 100
TOPUP = ('credit', 'top-up', 'top up', 'topup', 'reload', 'prepaid', 'promo')
def admin_stored():
    try: return json.loads((DATA/'admin.json').read_text())
    except FileNotFoundError: return None
def admin_get(key, path):
    req = urllib.request.Request(ADMIN_API+path, headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'wizard-tinfoil/0.3'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        raise PermissionError('rejected') if e.code in (401,403) else RuntimeError('provider') from None
    except Exception:
        raise RuntimeError('unreachable') from None
def money(v):
    try: v=float(v)
    except (TypeError,ValueError): return None
    return round(v*100) if v==v and abs(v)<1e9 else None
def summarize(period, alltime, tx):
    """Turn Tinfoil billing reads into minor-unit numbers. Balance = $1 starting credit + credit top-ups minus
    all-time usage cost. Full tank = the last top-up (or the $1 starting credit before any)."""
    rows = [t for t in (tx or {}).get('transactions') or [] if isinstance(t,dict) and str(t.get('status','completed')).lower() in ('completed','succeeded','paid')]
    tops = [t for t in rows if any(w in (str(t.get('description',''))+' '+str(t.get('type',''))).lower() for w in TOPUP) and (money(t.get('amount')) or 0) > 0]
    tops.sort(key=lambda t: str(t.get('date','')))
    spent_all, spent_period = money((alltime or {}).get('cost')), money((period or {}).get('cost'))
    # Every Tinfoil account starts with $1 of API credit that never appears as a transaction.
    bought = STARTING_CREDIT_MINOR + sum(money(t.get('amount')) or 0 for t in tops)
    balance = max(0, bought-(spent_all or 0)) if spent_all is not None else None
    last = money(tops[-1].get('amount')) if tops else STARTING_CREDIT_MINOR
    return {'periodSpendMinor':spent_period,'allTimeSpendMinor':spent_all,'topUpsMinor':bought,'lastTopUpMinor':last,'balanceMinor':balance,
            'transactions':[{'date':str(t.get('date',''))[:25],'type':str(t.get('type',''))[:40],'description':str(t.get('description',''))[:80],'amountMinor':money(t.get('amount'))} for t in rows[-20:]]}
REFRESHING = threading.Lock()
def billing(force=False, wait=True):
    """Cached read; failures keep the last good numbers and report the error. Never raises. wait=False (status
    reads) returns the cache at once and refreshes in the background, so /api/connection never waits on Tinfoil."""
    import time
    if not wait:
        if admin_stored() and (BILL['data'] is None or time.time()-BILL['at'] >= BILLING_TTL) and REFRESHING.acquire(blocking=False):
            def run():
                try: billing(True)
                finally: REFRESHING.release()
            threading.Thread(target=run, daemon=True).start()
        return BILL['data'] if admin_stored() else None
    a = admin_stored()
    if not a:
        BILL.update(at=0.0, data=None, error=None); return None
    if not force and BILL['data'] is not None and time.time()-BILL['at'] < BILLING_TTL: return BILL['data']
    if not force and BILL['error'] and time.time()-BILL['at'] < 60: return BILL['data']
    try:
        d = summarize(admin_get(a['key'],'/api/billing/usage?time=period'), admin_get(a['key'],'/api/billing/usage?time=all'), admin_get(a['key'],'/api/billing/transactions'))
        d['fetchedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        BILL.update(at=time.time(), data=d, error=None)
    except PermissionError:
        BILL.update(at=time.time(), error='rejected')
    except Exception:
        BILL.update(at=time.time(), error='unreachable')
    return BILL['data']
def usage():
    d = billing(wait=False)
    if not d: return None
    paid = {'type':'credits','enabled':True,'currency':'USD','exponent':2,'usedMinor':d['periodSpendMinor'],'limitMinor':d['lastTopUpMinor'],'balanceMinor':d['balanceMinor'],'unlimited':False}
    return {'fetchedAt':d['fetchedAt'],'limits':[],'paid':paid}
def hint(k): return ('…'+k[-4:]) if isinstance(k,str) and len(k)>=16 else None
def billing_status():
    a = admin_stored()
    return {'adminKeyStored':bool(a),'adminKeyHint':hint((a or {}).get('key')),'billing':'off' if not a else ('rejected' if BILL['error']=='rejected' else 'unavailable' if BILL['error'] and not BILL['data'] else 'ok' if BILL['data'] else 'pending')}

def status():
    # Atomic replace makes this a safe snapshot; never wait behind network verification.
    s = stored()
    return {'contract':'wizard.ai-connection/1','provider':'tinfoil','name':'Tinfoil','status':'connected' if s and s.get('authenticated') else 'not_connected','credentialStored':bool(s),'credentialVerified':bool(s and s.get('authenticated')),'plan':None,'account':None,'usage':usage(),'error':None,**billing_status(),'models':s['models'] if s else [],'verification':{'mode':'official-sdk-attestation','sdk':'tinfoil==0.14.0','lastVerifiedAt':s['verifiedAt'] if s else None},'chatIntegration':(s or {}).get('agent','not_registered'),'apiKeyHint':hint((s or {}).get('key')),'apps':sorted(app_tokens())}

def worker(action, key, payload=None):
    # Kill on timeout; no upstream exception/headers/body may reach logs or clients.
    result = subprocess.run([sys.executable,str(ROOT/'app/provider.py'),action],input=json.dumps({'key':key,'payload':payload}),text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=45 if action=='verify' else 180)
    if result.returncode: raise ValueError('Verification or provider request failed. Saved connection unchanged.')
    return json.loads(result.stdout)

# Standard chat-completions fields, plus model hints OpenAI-compatible agents send. None can change the
# enclave, URL, headers or key; extras ride in the SDK's extra_body (provider.py).
CHAT_FIELDS = {'model','messages','temperature','top_p','max_tokens','max_completion_tokens','tools','tool_choice','parallel_tool_calls','stop','response_format','stream','stream_options','seed','presence_penalty','frequency_penalty','reasoning_effort','prompt_cache_key','user','n','logprobs','top_logprobs','logit_bias'}
BODY_EXTRAS = {'thinking','reasoning','chat_template_kwargs','top_k','min_p','repetition_penalty'}

def key_ok(k): return isinstance(k,str) and 16 <= len(k) <= 512 and all(33<=ord(c)<=126 for c in k)

TOOLS = [{'name':'billing_summary','description':'Read Tinfoil spend and credit balance (USD minor units) from the owner\'s saved billing key. Read-only; never returns credentials. If adminKeyStored is false, the owner adds a Tinfoil admin key on the Tinfoil app page; never ask for keys in chat.','inputSchema':{'type':'object','properties':{},'additionalProperties':False},'annotations':{'readOnlyHint':True}},{'name':'connection_status','description':'Read Tinfoil connection and attestation status. Never returns credentials. To connect, the owner enters a key in the Tinfoil app; do not request keys in chat.','inputSchema':{'type':'object','properties':{},'additionalProperties':False},'annotations':{'readOnlyHint':True}}]
def rpc(m):
    i=m.get('id'); method=m.get('method'); p=m.get('params') or {}
    if 'id' not in m: return None
    if method=='initialize': r={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'wizard-tinfoil','version':'0.3.6'}}
    elif method=='tools/list': r={'tools':TOOLS}
    elif method=='ping': r={}
    elif method=='tools/call' and p.get('name')=='connection_status' and not p.get('arguments'):
        s=status(); r={'content':[{'type':'text','text':json.dumps(s)}],'structuredContent':s,'isError':False}
    elif method=='tools/call' and p.get('name')=='billing_summary' and not p.get('arguments'):
        b={**billing_status(),'summary':billing()}; r={'content':[{'type':'text','text':json.dumps(b)}],'structuredContent':b,'isError':False}
    else: return {'jsonrpc':'2.0','id':i,'error':{'code':-32602,'message':'Unknown method, tool or arguments.'}}
    return {'jsonrpc':'2.0','id':i,'result':r}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def send(self,code,obj=None,kind='application/json'):
        b=obj if isinstance(obj,bytes) else json.dumps(obj).encode()
        self.send_response(code)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(b)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self' "+' '.join(sorted(ORIGINS))}.items(): self.send_header(k,v)
        self.end_headers()
        if self.command!='HEAD': self.wfile.write(b)
    def refused(self,path,write=False):
        if self.headers.get('Host','').lower() not in HOSTS: self.send(403,{'error':'Untrusted host.'}); return True
        origin=self.headers.get('Origin','').lower()
        if origin and origin not in ORIGINS or self.headers.get('Sec-Fetch-Site')=='cross-site': self.send(403,{'error':'Cross-site request refused.'}); return True
        if path=='/mcp' or path=='/api/connection' or path.startswith('/v1/'):
            if any(k.lower() in {'tailscale-user-login','x-forwarded-for','forwarded','x-real-ip'} or k.lower().startswith('cf-') for k in self.headers): self.send(403,{'error':'Box-only endpoint.'}); return True
        if write and path.startswith('/api/') and (origin not in ORIGINS or self.headers.get('X-Wizard-Request')!='1'): self.send(403,{'error':'Use the trusted connection page.'}); return True
        if path.startswith('/v1/'):
            if origin or not bearer_ok(self.headers.get('Authorization','')): self.send(401,{'error':'Local gateway credential required.'}); return True
        return False
    def do_HEAD(self): self.do_GET()
    def do_GET(self):
        path=urlsplit(self.path).path
        if self.refused(path): return
        if path=='/healthz': return self.send(200,{'ok':True,'app':'wizard-tinfoil','version':'0.3.6'})
        if path in ('/api/connection', '/api/status'): return self.send(200,status())
        if path=='/v1/models': return self.send(200,{'object':'list','data':[{'id':x,'object':'model','owned_by':'tinfoil'} for x in status()['models']]})
        if path=='/openapi.json': return self.send(200,(ROOT/'openapi.json').read_bytes())
        name='index.html' if path=='/' else path[1:]
        if '/' not in name and not name.startswith('.') and Path(name).suffix in TYPES and (ROOT/'web'/name).is_file(): return self.send(200,(ROOT/'web'/name).read_bytes(),TYPES[Path(name).suffix])
        self.send(404,{'error':'Not found.'})
    def do_POST(self):
        path=urlsplit(self.path).path
        if self.refused(path,True): return
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.send(415,{'error':'Use application/json.'})
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=1048576: return self.send(413,{'error':'Invalid body size.'})
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict): raise ValueError()
            if path=='/mcp':
                r=rpc(body); return self.send(202 if r is None else 200,r)
            if path=='/api/connect':
                if set(body)!={'apiKey'} or not key_ok(body['apiKey']): return self.send(400,{'error':'Enter a valid API key (16–512 non-space ASCII characters).'})
                with LOCK:
                    result=worker('verify',body['apiKey'])
                    atomic('connection.json',{'key':body['apiKey'],'authenticated':False,**result})
                    atomic('connection.json',{**stored(),'agent':register(result['models']),'picked':ranked(result['models'])[:REGISTERED]})
                return self.send(200,status())
            if path=='/api/admin-key':
                if set(body)!={'adminKey'} or not key_ok(body['adminKey']): return self.send(400,{'error':'Enter a valid admin key.'})
                k=body['adminKey']
                try:
                    ctx=admin_get(k,'/api/auth/context'); admin_get(k,'/api/billing/usage?time=24h')
                except PermissionError: return self.send(400,{'error':'Tinfoil rejected that key for billing. Use an unscoped admin key (Dashboard → Admin Keys), not an API key.'})
                except Exception: return self.send(503,{'error':'Could not reach Tinfoil. Nothing was saved.'})
                with LOCK: atomic('admin.json',{'key':k,'context':str((ctx or {}).get('context_type',''))[:20],'savedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()})
                billing(True); return self.send(200,status())
            if path=='/api/admin-key/remove':
                if body: raise ValueError()
                with LOCK: (DATA/'admin.json').unlink(missing_ok=True)
                billing(True); return self.send(200,status())
            if path=='/api/app-tokens':
                # Owner action from an app's own page on this box (trusted origin + X-Wizard-Request, checked above).
                if set(body)!={'app'} or not isinstance(body['app'],str) or not APP_ID.match(body['app']): return self.send(400,{'error':'Name the app.'})
                with LOCK:
                    s=stored()
                    if not s: return self.send(409,{'error':'Connect Tinfoil first.'})
                    token=secrets.token_urlsafe(48); atomic('app-tokens.json',{**app_tokens(),body['app']:{'token':token,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}})
                return self.send(200,{'app':body['app'],'token':token,'baseUrl':APP_BASE,'models':chat_models(s['models']),'recommended':ranked(s['models'])[:1]})
            if path=='/api/app-tokens/remove':
                if set(body)!={'app'} or not isinstance(body['app'],str): return self.send(400,{'error':'Name the app.'})
                with LOCK:
                    t=app_tokens(); t.pop(body['app'],None); atomic('app-tokens.json',t)
                return self.send(200,status())
            if path=='/api/test':
                if body: raise ValueError()
                with LOCK:
                    s=stored()
                    if not s: return self.send(409,{'error':'Connect an API key first.'})
                    result=worker('verify',s['key']); atomic('connection.json',{**s,**result})
                    atomic('connection.json',{**stored(),'agent':register(result['models']),'picked':ranked(result['models'])[:REGISTERED]})
                return self.send(200,status())
            if path=='/api/disconnect':
                if body: raise ValueError()
                with LOCK:
                    (DATA/'connection.json').unlink(missing_ok=True)
                    unregister()
                    # Keep the box-only app credential stable across provider logout.
                    # Removing connection.json immediately disables all inference.

                return self.send(200,status())
            if path=='/v1/chat/completions':
                s=stored()
                if not s: return self.send(409,{'error':'Tinfoil is not connected.'})
                if not isinstance(body.get('messages'),list) or not body['messages'] or body.get('model') not in s['models']: return self.send(400,{'error':'Choose a connected Tinfoil model and supply messages.'})
                # SDK owns transport; callers cannot override enclave, URL, headers or key.
                # Body fields only: agents (Hermes) add reasoning/thinking/cache hints per model.
                allowed=CHAT_FIELDS|BODY_EXTRAS
                unknown=sorted(set(body)-allowed)
                if unknown: return self.send(400,{'error':'Unsupported request field(s): '+', '.join(k[:40] for k in unknown[:8])})
                if body.get('stream') not in (None,False,True): raise ValueError()
                result=worker('infer',s['key'],body)
                with LOCK:
                    current=stored()
                    if current and hmac.compare_digest(current['key'],s['key']): atomic('connection.json',{**current,'authenticated':True})
                if body.get('stream'):
                    return self.send(200,result['sse'].encode(),'text/event-stream')
                return self.send(200,result)
            self.send(404,{'error':'Not found.'})
        except (ValueError,TypeError,KeyError,json.JSONDecodeError): self.send(400,{'error':'Invalid request or provider verification failed. Saved connection unchanged.'})
        except subprocess.TimeoutExpired: self.send(504,{'error':'Provider verification timed out. Saved connection unchanged.'})
        except Exception: self.send(503,{'error':'Connection unavailable. No unverified fallback was used.'})

def initialize():
    os.umask(0o077)
    DATA.mkdir(mode=0o700,parents=True,exist_ok=True); os.chmod(DATA,0o700)
    if not (DATA/'gateway-token.json').exists(): atomic('gateway-token.json',{'token':secrets.token_urlsafe(48)})

def reconcile():
    """Register a saved key whose agent registration is missing (older version, agent installed later) or whose
    private choices changed (a newer Kimi on Tinfoil, a new ranking in this version)."""
    with LOCK:
        s = stored()
        want = ranked((s or {}).get('models') or [])[:REGISTERED]
        if s and (s.get('agent') != 'registered' or s.get('picked') != want):
            atomic('connection.json',{**s,'agent':register(s.get('models') or []),'picked':want})

def refresh_models():
    """Every MODEL_REFRESH seconds re-read Tinfoil's verified model list, so a new model (Kimi K3.1) becomes the
    private choice without the owner reconnecting. Failures keep the saved connection unchanged."""
    while MODEL_REFRESH > 0:
        time.sleep(MODEL_REFRESH)
        try:
            s = stored()
            if not s: continue
            result = worker('verify', s['key'])
            with LOCK:
                cur = stored()
                if cur and hmac.compare_digest(cur['key'], s['key']): atomic('connection.json',{**cur,**result})
            reconcile()
        except Exception: pass

if __name__=='__main__':
    initialize()
    threading.Thread(target=reconcile, daemon=True).start()
    threading.Thread(target=refresh_models, daemon=True).start()
    ThreadingHTTPServer((os.environ.get('BIND','0.0.0.0'),int(PORT)),Handler).serve_forever()
