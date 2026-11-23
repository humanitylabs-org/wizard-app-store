"use strict";
const el=id=>document.getElementById(id);
let busy=false,last=null;const editing={api:false,admin:false};
const usd=m=>m==null?'—':'$'+(m/100).toFixed(m%100?2:0);
const K={api:{box:el('k-api'),save:'api/connect',field:'apiKey',remove:'api/disconnect',name:'API key'},admin:{box:el('k-admin'),save:'api/admin-key',field:'adminKey',remove:'api/admin-key/remove',name:'Admin key'}};
const q=(k,sel)=>K[k].box.querySelector(sel);
const row=(k,sel)=>document.querySelector(`[data-row="${k}"] ${sel}`);
// Every pop-up is a kit sheet (wizard-sheet.js): ×, Esc, tap outside, Back and swipe down all close it.
const openSheet=d=>{if(window.WzSheet)WzSheet.open(d);else if(!d.open)d.showModal();};
// Connected = Tinfoil checked the key (attestation) and the agent has it; a key whose agent set-up failed says so
// (wizard-tinfoil#30), never "Not connected" next to "Saved".
const ready=s=>s.status==='connected'||!!s.agentReady;
const stuck=s=>!!s.credentialStored&&!!s.keyVerified&&!s.agentReady&&s.status!=='connected';
// Model ids as people say them: kimi-k3-1-pro → Kimi K3.1 Pro, glm-5-3 → GLM 5.3.
const NAMES={kimi:'Kimi',glm:'GLM',deepseek:'DeepSeek',llama:'Llama',gpt:'GPT',oss:'OSS',pro:'Pro',flash:'Flash'};
function modelName(id){
  const out=[];
  for(const w of String(id).split('-')){
    let m;
    if(/^\d+$/.test(w)&&out.length&&/\d$/.test(out[out.length-1]))out[out.length-1]+='.'+w;
    else if(NAMES[w])out.push(NAMES[w]);
    else if((m=w.match(/^([a-z]{2,})(\d+)$/))&&NAMES[m[1]])out.push(NAMES[m[1]]+' '+m[2]);
    else if(/^[a-z]\d+$/.test(w)||/^\d+[a-z]$/.test(w))out.push(w.toUpperCase());
    else out.push(w.charAt(0).toUpperCase()+w.slice(1));
  }
  return out.join(' ');
}
const list=a=>a.length<2?a.join(''):a.slice(0,-1).join(', ')+' and '+a[a.length-1];
function result(s){
  if(ready(s)){const m=list((s.privateModels||[]).map(modelName));
    return['ok',`Connected: ${m?m+' ready for your ':'private models ready for your '}${s.chatIntegration==='private_agent'?'private agent':'agent'}.`];}
  if(s.error)return['',s.error];
  return['','Your key is saved, but your agent isn\u2019t set up yet. Try again in a minute or open Troubleshoot.'];
}
function pill(k,s,stored){
  if(!stored)return['off','Not added'];
  if(k==='api')return ready(s)?['ok','Active']:stuck(s)?['warn','Key OK']:['off','Saved'];
  return s.billing==='rejected'?['warn','Rejected']:s.billing==='unavailable'?['warn','Unavailable']:['ok','Active'];
}
function view(k,s){
  const stored=k==='api'?s.credentialStored:s.adminKeyStored,h=k==='api'?s.apiKeyHint:s.adminKeyHint;let state='Not added',sub=k==='api'?'Needed for private models in chat.':'Optional: shows your Tinfoil credit on Home.';
  if(stored&&k==='api'){state='Saved '+(h||'');sub=ready(s)?'Connected · private models available':stuck(s)?'Key OK · private agent not set up':'Saved · not checked yet';}
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
  const [kind,word]=stuck(s)?['warn','Key OK']:ready(s)&&!s.error&&s.billing!=='rejected'?['ok','Connected']:s.status==='error'||s.billing==='rejected'||(ready(s)&&s.error)?['warn','Needs attention']:['off','Not connected'];
  el('pill').className='wz-pill '+kind;el('pill').textContent=word;
  el('count').textContent=String((s.credentialStored?1:0)+(s.adminKeyStored?1:0));
  el('connect').hidden=!!s.credentialStored;el('retry').hidden=!stuck(s);
  for(const b of document.querySelectorAll('button:not(.wz-sheet-x):not([data-open])'))b.disabled=busy;
  watch(s);
}
// A saved key whose private agent isn't set up yet is retried by the app on its own (the agent runtime can arrive
// later, wizard-tinfoil#35): keep reading the status while the page is open, so it turns Connected with no tap.
let watching=0;
function watch(s){
  if(watching||!stuck(s))return;
  watching=setTimeout(()=>{watching=0;if(busy||document.hidden){if(last)watch(last);return;}
    request('api/status').then(n=>{render(n);if(ready(n)){const [kind,text]=result(n);say(text,kind);}}).catch(()=>{if(last)watch(last);});},WATCH_MS);
}
const WATCH_MS=window.WZ_STATUS_WATCH_MS||10000;
// kind: '' an error (red), 'note' progress, 'ok' a result.
function say(text,kind=''){const c='wz-status'+(kind?' '+kind:'');el('status').textContent=text;el('status').className=c;
  for(const k of ['api','admin']){const m=q(k,'[data-msg]');m.textContent=K[k].box.open?text:'';m.className=c;}}
async function request(path,body){const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Request':'1'},body:JSON.stringify(body)});const s=await r.json();if(!r.ok)throw Error(s.error||'Connection unavailable.');return s;}
// Connect and Test take up to a minute (enclave check, then the agent hand-off): the page says which step is running.
const STEPS={verifying:'Checking your key with Tinfoil…',agent:'Adding Tinfoil to your agent…',private_agent:'Setting up your private agent…'};
async function action(path,body,after,opts={}){
  if(busy)return;busy=true;const btn=opts.button,label=btn&&btn.textContent;if(last)render(last);
  if(btn)btn.textContent=opts.busyLabel||label;say(opts.first||'',opts.first?'note':'');
  let tick=0;if(opts.first)tick=setInterval(()=>{request('api/status').then(s=>{if(busy&&STEPS[s.progress])say(STEPS[s.progress],'note');}).catch(()=>{});},1000);
  let done=null;
  try{const s=await request(path,body);after&&after(s);if(opts.result)done=result(s);}catch(e){say(e.message);}
  finally{clearInterval(tick);busy=false;if(btn)btn.textContent=label;
    request('api/status').then(s=>{render(s);if(done){const [kind,text]=result(s);say(text,kind);}}).catch(()=>{say('Status unavailable.');});}
}
function openKey(k){say('');openSheet(K[k].box);const i=q(k,'input');if(!q(k,'[data-form]').hidden)i.focus();}
for(const k of ['api','admin']){
  q(k,'[data-form]').onsubmit=e=>{e.preventDefault();const i=q(k,'input'),v=i.value;i.value='';
    // In the Welcome (?connect=1) saving the key is the whole step: the sheet closes and the page shows Connected or
    // what went wrong, never the Replace / Remove / Test sheet (wizard-tinfoil#30).
    action(K[k].save,{[K[k].field]:v},()=>{editing[k]=false;if(CONNECT&&k==='api'&&window.WzSheet)WzSheet.close(K[k].box);else if(CONNECT&&k==='api'&&K[k].box.open)K[k].box.close();},
      k==='api'?{button:q(k,'button[type=submit]'),busyLabel:'Connecting…',first:STEPS.verifying,result:true}:{button:q(k,'button[type=submit]'),busyLabel:'Saving…'});};
  q(k,'[data-replace]').onclick=()=>{editing[k]=true;render(last);q(k,'input').focus();};
  q(k,'[data-cancel]').onclick=()=>{editing[k]=false;q(k,'input').value='';render(last);};
  q(k,'[data-remove]').onclick=e=>{const b=e.currentTarget;if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent='Tap again to remove';setTimeout(()=>{b.dataset.armed='';if(last)render(last);},4000);return;}b.dataset.armed='';action(K[k].remove,{});};
  // Closing the sheet abandons an unsaved edit (same as Cancel); a typed key is never kept.
  K[k].box.addEventListener('close',()=>{q(k,'input').value='';q(k,'[data-msg]').textContent='';if(editing[k]){editing[k]=false;if(last)render(last);}});
  row(k,'[data-open]').onclick=()=>openKey(k);
}
el('connect').onclick=()=>openKey('api');
const test=b=>action('api/test',{},null,{button:b,busyLabel:'Testing…',first:STEPS.verifying,result:true});
el('test').onclick=e=>test(e.currentTarget);
el('retry').onclick=e=>test(e.currentTarget);
// ?connect=1 (the Wizard Welcome, same as the Claude/ChatGPT apps): with no key saved yet, open straight to the
// API key paste box (Miguel: keep onboarding to a minimum). A saved key just shows the page.
const CONNECT=new URLSearchParams(location.search).get('connect')==='1';
request('api/status').then(s=>{render(s);if(CONNECT&&!s.credentialStored)openKey('api');}).catch(e=>{say(e.message);});
