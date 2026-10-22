"use strict";
const el=id=>document.getElementById(id);
let busy=false,last=null;const editing={api:false,admin:false};
const usd=m=>m==null?'—':'$'+(m/100).toFixed(m%100?2:0);
const K={api:{box:el('k-api'),save:'api/connect',field:'apiKey',remove:'api/disconnect'},admin:{box:el('k-admin'),save:'api/admin-key',field:'adminKey',remove:'api/admin-key/remove'}};
const q=(k,sel)=>K[k].box.querySelector(sel);
function view(k,s){
  const stored=k==='api'?s.credentialStored:s.adminKeyStored,h=k==='api'?s.apiKeyHint:s.adminKeyHint;let state='Not added',sub=k==='api'?'Needed for private models in chat.':'Optional: shows your Tinfoil credit on Home.';
  if(stored&&k==='api'){state='Saved '+(h||'');sub=s.status==='connected'?'Connected · private models available':'Saved · connects on first private chat';}
  if(stored&&k==='admin'){const p=s.usage&&s.usage.paid;state='Saved '+(h||'');sub=s.billing==='rejected'?'Tinfoil rejected this key. Replace it with an unscoped admin key.':p?(p.balanceMinor!=null?usd(p.balanceMinor)+' credit left · '+usd(p.usedMinor)+' spent this period':usd(p.usedMinor)+' spent this period'):s.billing==='unavailable'?'Billing unavailable right now':'Reading billing…';}
  q(k,'[data-state]').textContent=state;q(k,'[data-sub]').textContent=sub;
  const open=!stored||editing[k];q(k,'[data-form]').hidden=!open;q(k,'[data-saved]').hidden=open;q(k,'[data-cancel]').hidden=!stored;
  if(stored&&q(k,'[data-remove]').dataset.armed!=='1')q(k,'[data-remove]').textContent='Remove';
}
function render(s){last=s;view('api',s);view('admin',s);for(const b of document.querySelectorAll('button'))b.disabled=busy;}
async function request(path,body){const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Request':'1'},body:JSON.stringify(body)});const s=await r.json();if(!r.ok)throw Error(s.error||'Connection unavailable.');return s;}
async function action(path,body,after){if(busy)return;busy=true;if(last)render(last);el('status').textContent='';try{await request(path,body);after&&after();}catch(e){el('status').textContent=e.message;}finally{busy=false;request('api/status').then(render).catch(()=>{el('status').textContent='Status unavailable.';});}}
for(const k of ['api','admin']){
  q(k,'[data-form]').onsubmit=e=>{e.preventDefault();const i=q(k,'input'),v=i.value;i.value='';action(K[k].save,{[K[k].field]:v},()=>{editing[k]=false;});};
  q(k,'[data-replace]').onclick=()=>{editing[k]=true;render(last);q(k,'input').focus();};
  q(k,'[data-cancel]').onclick=()=>{editing[k]=false;q(k,'input').value='';render(last);};
  q(k,'[data-remove]').onclick=e=>{const b=e.currentTarget;if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent='Tap again to remove';setTimeout(()=>{b.dataset.armed='';if(last)render(last);},4000);return;}b.dataset.armed='';action(K[k].remove,{});};
}
el('test').onclick=()=>action('api/test',{});
window.__wizardCloseOverlay=()=>false;
request('api/status').then(render).catch(e=>{el('status').textContent=e.message;});
