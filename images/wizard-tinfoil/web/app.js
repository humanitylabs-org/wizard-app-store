"use strict";
const el=id=>document.getElementById(id);
let busy=false,last=null;const editing={api:false,admin:false};
const usd=m=>m==null?'—':'$'+(m/100).toFixed(m%100?2:0);
const K={api:{box:el('k-api'),save:'api/connect',field:'apiKey',remove:'api/disconnect',name:'API key'},admin:{box:el('k-admin'),save:'api/admin-key',field:'adminKey',remove:'api/admin-key/remove',name:'Admin key'}};
const q=(k,sel)=>K[k].box.querySelector(sel);
const row=(k,sel)=>document.querySelector(`[data-row="${k}"] ${sel}`);
// Every pop-up is a kit sheet (wizard-sheet.js): ×, Esc, tap outside, Back and swipe down all close it.
const openSheet=d=>{if(window.WzSheet)WzSheet.open(d);else if(!d.open)d.showModal();};
function pill(k,s,stored){
  if(!stored)return['off','Not added'];
  if(k==='api')return s.status==='connected'?['ok','Active']:['off','Saved'];
  return s.billing==='rejected'?['warn','Rejected']:s.billing==='unavailable'?['warn','Unavailable']:['ok','Active'];
}
function view(k,s){
  const stored=k==='api'?s.credentialStored:s.adminKeyStored,h=k==='api'?s.apiKeyHint:s.adminKeyHint;let state='Not added',sub=k==='api'?'Needed for private models in chat.':'Optional: shows your Tinfoil credit on Home.';
  if(stored&&k==='api'){state='Saved '+(h||'');sub=s.status==='connected'?'Connected · private models available':'Saved · connects on first private chat';}
  if(stored&&k==='admin'){const p=s.usage&&s.usage.paid;state='Saved '+(h||'');sub=s.billing==='rejected'?'Tinfoil rejected this key. Replace it with an unscoped admin key.':p?(p.balanceMinor!=null?usd(p.balanceMinor)+' credit left · '+usd(p.usedMinor)+' spent this period':usd(p.usedMinor)+' spent this period'):s.billing==='unavailable'?'Billing unavailable right now':'Reading billing…';}
  q(k,'[data-state]').textContent=state;q(k,'[data-sub]').textContent=sub;
  row(k,'[data-state]').textContent=K[k].name+(stored&&h?' '+h:'');
  // The credit meter under the admin row carries the numbers; the row line says what the key is for.
  row(k,'[data-sub]').textContent=k==='admin'&&stored&&s.usage&&s.usage.paid&&s.usage.paid.balanceMinor!=null&&s.billing!=='rejected'?'Reads billing only':sub;
  const [kind,word]=pill(k,s,stored);row(k,'[data-pill]').className='wz-pill '+kind;row(k,'[data-pill]').textContent=word;
  const open=!stored||editing[k];q(k,'[data-form]').hidden=!open;q(k,'[data-saved]').hidden=open;q(k,'[data-cancel]').hidden=!stored;
  if(stored&&q(k,'[data-remove]').dataset.armed!=='1')q(k,'[data-remove]').textContent='Remove';
}
function credit(s){
  const p=s.adminKeyStored&&s.usage&&s.usage.paid,m=el('credit');
  // Tinfoil has no top-up API; buying credit (or auto-reload) happens on its Billing tab, one tap from here.
  el('topup').hidden=!s.credentialStored;
  m.hidden=!(p&&p.balanceMinor!=null);if(m.hidden)return;
  const full=Math.max(p.limitMinor||0,p.balanceMinor,1),pct=Math.max(0,Math.min(100,Math.round(p.balanceMinor/full*100)));
  m.querySelector('[data-credit]').textContent='Credit · '+usd(p.balanceMinor)+' left of '+usd(full)+' · '+usd(p.usedMinor)+' spent this period';
  m.querySelector('b').style.setProperty('--v',pct+'%');
}
function details(s){
  const v=s.verification||{},facts=[['Status',s.status||'unknown'],['Key checked by Tinfoil',s.credentialVerified?'yes':'not yet'],['Agent model',s.chatIntegration||''],['Enclave check',v.mode||''],['SDK',v.sdk||''],['Last verified',v.lastVerifiedAt?new Date(v.lastVerifiedAt).toLocaleString():''],['Models',(s.models||[]).join(', ')],['Contract',s.contract||'']].filter(([,x])=>x);
  el('details').replaceChildren(...facts.flatMap(([a,b])=>{const t=document.createElement('dt'),d=document.createElement('dd');t.textContent=a;d.textContent=b;return[t,d];}));
}
// Apps the owner let use Tinfoil from their own page (e.g. Search AI overviews). Remove revokes that app's token.
const APP_NAMES={'wizard-search':['Search','AI overviews on search results']};
function apps(s){
  const list=s.apps||[];el('apps-sec').hidden=!list.length;el('apps-count').textContent=String(list.length);
  el('apps').replaceChildren(...list.map(id=>{
    const [name,use]=APP_NAMES[id]||[id,'Uses your private models'],li=document.createElement('li');li.className='app-li';
    const r=document.createElement('div');r.className='wz-row app-row';const tile=document.createElement('span');tile.className='wz-tile';tile.setAttribute('aria-hidden','true');tile.textContent=name.slice(0,1);
    const m=document.createElement('span');m.className='wz-main';const b=document.createElement('b');b.textContent=name;const sm=document.createElement('small');sm.textContent=use;m.append(b,sm);
    const x=document.createElement('button');x.type='button';x.className='wz-button secondary';x.textContent='Remove';x.disabled=busy;
    x.onclick=()=>{if(x.dataset.armed!=='1'){x.dataset.armed='1';x.textContent='Tap again to remove';setTimeout(()=>{x.dataset.armed='';x.textContent='Remove';},4000);return;}action('api/app-tokens/remove',{app:id});};
    r.append(tile,m,x);li.append(r);return li;}));
}
function render(s){
  last=s;apps(s);view('api',s);view('admin',s);credit(s);details(s);
  const [kind,word]=s.status==='connected'&&s.billing!=='rejected'?['ok','Connected']:s.status==='error'||s.billing==='rejected'||(s.status==='connected'&&s.error)?['warn','Needs attention']:['off','Not connected'];
  el('pill').className='wz-pill '+kind;el('pill').textContent=word;
  el('count').textContent=String((s.credentialStored?1:0)+(s.adminKeyStored?1:0));
  el('connect').hidden=!!s.credentialStored;
  for(const b of document.querySelectorAll('button:not(.wz-sheet-x):not([data-open])'))b.disabled=busy;
}
function say(text){el('status').textContent=text;for(const k of ['api','admin'])q(k,'[data-msg]').textContent=K[k].box.open?text:'';}
async function request(path,body){const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Request':'1'},body:JSON.stringify(body)});const s=await r.json();if(!r.ok)throw Error(s.error||'Connection unavailable.');return s;}
async function action(path,body,after){if(busy)return;busy=true;if(last)render(last);say('');try{await request(path,body);after&&after();}catch(e){say(e.message);}finally{busy=false;request('api/status').then(render).catch(()=>{say('Status unavailable.');});}}
function openKey(k){say('');openSheet(K[k].box);const i=q(k,'input');if(!q(k,'[data-form]').hidden)i.focus();}
for(const k of ['api','admin']){
  q(k,'[data-form]').onsubmit=e=>{e.preventDefault();const i=q(k,'input'),v=i.value;i.value='';action(K[k].save,{[K[k].field]:v},()=>{editing[k]=false;});};
  q(k,'[data-replace]').onclick=()=>{editing[k]=true;render(last);q(k,'input').focus();};
  q(k,'[data-cancel]').onclick=()=>{editing[k]=false;q(k,'input').value='';render(last);};
  q(k,'[data-remove]').onclick=e=>{const b=e.currentTarget;if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent='Tap again to remove';setTimeout(()=>{b.dataset.armed='';if(last)render(last);},4000);return;}b.dataset.armed='';action(K[k].remove,{});};
  // Closing the sheet abandons an unsaved edit (same as Cancel); a typed key is never kept.
  K[k].box.addEventListener('close',()=>{q(k,'input').value='';q(k,'[data-msg]').textContent='';if(editing[k]){editing[k]=false;if(last)render(last);}});
  row(k,'[data-open]').onclick=()=>openKey(k);
}
el('connect').onclick=()=>openKey('api');
el('test').onclick=()=>action('api/test',{});
// ?connect=1 (the Wizard Welcome, same as the Claude/ChatGPT apps): with no key saved yet, open straight to the
// API key paste box (Miguel: keep onboarding to a minimum). A saved key just shows the page.
const CONNECT=new URLSearchParams(location.search).get('connect')==='1';
request('api/status').then(s=>{render(s);if(CONNECT&&!s.credentialStored)openKey('api');}).catch(e=>{say(e.message);});
