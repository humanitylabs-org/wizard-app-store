"use strict";
const el=id=>document.getElementById(id);
let busy=false;
const usd=m=>m==null?'—':'$'+(m/100).toFixed(m%100?2:0);
function renderBilling(s){el('billing-sec').hidden=!s.credentialStored;el('admin-form').hidden=!!s.adminKeyStored;el('admin-saved').hidden=!s.adminKeyStored;el('admin-remove').disabled=busy;const p=s.usage&&s.usage.paid;let line='Not set up',sub='';if(s.adminKeyStored){if(s.billing==='rejected'){line='Billing key rejected';sub='Remove it and paste an unscoped admin key.';}else if(p){line=p.balanceMinor!=null?usd(p.balanceMinor)+' credit left':usd(p.usedMinor)+' spent this period';sub=p.balanceMinor!=null?usd(p.usedMinor)+' spent this period':'No credit top-ups found, so only spend is shown.';}else{line=s.billing==='unavailable'?'Billing unavailable':'Reading billing…';}}el('billing-line').textContent=line;el('billing-sub').textContent=sub;}
function render(s){renderBilling(s);el('connection').textContent=s.status==='connected'?'Connected':s.credentialStored?'Key saved':'Not connected';el('connect-form').hidden=!!s.credentialStored;el('saved').hidden=!s.credentialStored;el('test').disabled=el('disconnect').disabled=busy||!s.credentialStored;}
async function request(path,body){const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Request':'1'},body:JSON.stringify(body)});const s=await r.json();if(!r.ok)throw Error(s.error||'Connection unavailable.');return s;}
async function action(path,body){if(busy)return;busy=true;for(const b of document.querySelectorAll('button'))b.disabled=true;el('status').textContent='';el('connection').textContent='Checking…';try{await request(path,body);}catch(e){el('status').textContent=e.message;}finally{busy=false;el('connect').disabled=false;request('api/status').then(render).catch(()=>{el('status').textContent='Status unavailable.';});}}
el('connect-form').onsubmit=e=>{e.preventDefault();const key=el('api-key').value;el('api-key').value='';action('api/connect',{apiKey:key});};
el('admin-form').onsubmit=e=>{e.preventDefault();const key=el('admin-key').value;el('admin-key').value='';action('api/admin-key',{adminKey:key});};
el('admin-remove').onclick=()=>action('api/admin-key/remove',{});
el('test').onclick=()=>action('api/test',{});el('disconnect').onclick=()=>action('api/disconnect',{});
window.__wizardCloseOverlay=()=>false;
request('api/status').then(render).catch(e=>{el('status').textContent=e.message;});
