"use strict";
const $ = id => document.getElementById(id);
let snapshot, active, busy=false, timer;
const terminal = new Set(['succeeded','failed','cancelled','expired','needs_review']);
const el = (tag, text, cls) => {const node=document.createElement(tag); node.textContent=text || ''; if(cls) node.className=cls; return node;};
async function api(path, body) {
  const r=await fetch(path, {cache:'no-store', ...(body ? {method:'POST',headers:{'Content-Type':'application/json','X-Wizard-Account-Action':'1'},body:JSON.stringify(body)} : {})});
  if(!r.ok) {const error=new Error('Request failed'); error.status=r.status; throw error;} return r.json();
}
function display(job) {
  if(active?.id===job.id && terminal.has(active.status) && !terminal.has(job.status)) return;
  clearTimeout(timer);
  active=job; $('instructions').textContent=`${job.action}: ${job.status}. ${job.status==='succeeded' && job.action==='reconnect' ? 'Fresh sign-in saved. Existing grants were retained; verify the account before removing an old grant.' : ''}`;
  $('command').replaceChildren();
  if(job.url) {const a=el('a','Open provider sign-in'); a.href=job.url; a.target='_blank'; a.rel='noopener noreferrer'; $('command').append(a);}
  if(job.userCode) {const field=el('input'); field.readOnly=true; field.value=job.userCode; field.setAttribute('aria-label','Device sign-in code'); $('command').append(field);}
  $('code').hidden=!job.inputRequired; $('submit-code').hidden=!job.inputRequired;
  $('cancel').hidden=terminal.has(job.status); $('close').disabled=!terminal.has(job.status);
  if(!terminal.has(job.status)) {sessionStorage.setItem('account-operation',job.id); clearTimeout(timer); timer=setTimeout(poll,1000);}
  else {sessionStorage.removeItem('account-operation'); busy=false; $('add').disabled=false; refresh();}
}
async function poll() {
  const id=active.id;
  try {const job=await api('api/operations/'+id); if(active.id===id) display(job);}
  catch (error) {if(active.id!==id || terminal.has(active.status)) return; if(error.status===404) {display({...active,action:'Login',status:'needs_review'}); $('instructions').textContent='Broker restarted or operation expired from history. Refresh inventory; do not assume the login was cancelled.';} else {$('instructions').textContent='Status unavailable. Do not start another login; retrying this same operation status.'; timer=setTimeout(poll,3000);}}
}
async function manage(action, account, credential) {
  if(busy) return;
  const warning=action==='remove' ? `Remove only grant ${credential.id} (${account.name})? Other grants remain. This can stop chats using this grant.` : `${action==='reconnect' ? `Sign in again for ${account.name}, grant ${credential.id}? Old grants will NOT be removed automatically.` : 'Add a subscription?'} Use a different OpenAI account to add quota. Same-account sign-in may invalidate older grants.`;
  if(!confirm(warning)) return;
  const label=action==='add' ? prompt('Nickname for this subscription (optional):','') : '';
  if(label===null) return;
  busy=true; clearTimeout(timer); active={id:null,status:'starting'}; $('command').replaceChildren(); $('code').value=''; $('code').hidden=true; $('submit-code').hidden=true; $('cancel').hidden=true; $('add').disabled=true; $('close').disabled=true; $('manage').showModal(); $('instructions').textContent='Starting…';
  try {display(await api('api/operations',{action,target:credential?.id,label,confirmed:true}));}
  catch {$('instructions').textContent='Start result unknown. Refresh inventory and wait for the login timeout before retrying; no automatic retry was sent.'; $('close').disabled=false; busy=false; $('add').disabled=false;}
}
function render(data) {
  snapshot=data; $('title').textContent=data.name; document.title=data.name;
  $('summary').textContent=`${data.accounts.length} subscription source${data.accounts.length===1?'':'s'}`;
  const rows=data.accounts.map(a=>{
    const row=el('li','','account'); row.dataset.accountId=a.id;
    const head=el('header'); head.append(el('strong',a.name),el('span',a.status)); row.append(head);
    row.append(el('p',[a.email,a.plan || 'Plan not reported'].filter(Boolean).join(' · '),'meta'));
    if(a.source==='legacy-claude-code') row.append(el('p','Existing Claude Code login — unchanged, not in the Hermes pool. Add a Hermes subscription separately.','meta'));
    for(const limit of a.usage?.limits || []) {
      const meter=el('meter'); meter.min=0; meter.max=100; meter.value=limit.remainingPercent; meter.setAttribute('aria-label',a.name+' '+limit.label+' remaining');
      row.append(el('p',`${limit.label}: ${limit.remainingPercent}% left`),meter,el('small',limit.resetsAt ? 'Resets '+new Date(limit.resetsAt).toLocaleString() : 'Reset time not reported'));
    }
    if(!a.usage?.limits?.length) row.append(el('p','Usage unavailable — not zero.','meta'));
    for(const c of a.credentials || []) {
      const actions=el('div','','actions'); actions.append(el('small',`${c.name} · grant ${c.id}`));
      if(c.managed) for(const action of ['reconnect','remove']) {const b=el('button',action==='reconnect'?'Reconnect…':'Remove…'); b.disabled=busy; b.addEventListener('click',()=>manage(action,a,c)); actions.append(b);}
      else actions.append(el('small','External source — managed separately'));
      row.append(actions);
    }
    return row;
  });
  $('accounts').replaceChildren(...rows);
  if(!rows.length) $('accounts').append(el('li','No Hermes subscriptions found.','meta'));
  if(data.legacyStatus==='unavailable') $('accounts').append(el('li','Legacy Claude Code source status unavailable; its login is unchanged.','meta'));
}
async function refresh() {
  $('refresh').disabled=true;
  try {const data=await api('api/accounts'); render(data); $('message').textContent=data.error || ''; }
  catch {$('message').textContent='Hermes inventory unavailable. Any displayed rows are the last reading.';}
  finally {$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',refresh);
$('add').addEventListener('click',()=>{if(snapshot) manage('add');});
$('close').addEventListener('click',()=> $('manage').close());
$('manage').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
$('cancel').addEventListener('click',async()=>{
  try {display(await api('api/operations',{action:'cancel',operation:active.id}));}
  catch {$('instructions').textContent='Cancellation not confirmed. Keep this window open; checking status.';}
});
$('submit-code').addEventListener('click',async()=>{
  const code=$('code').value; $('code').value=''; $('submit-code').disabled=true;
  try {display(await api('api/operations',{action:'submit',operation:active.id,code}));}
  catch {$('instructions').textContent='Submission result unknown; checking the same login. Do not paste again.';}
  finally {$('submit-code').disabled=false;}
});
setInterval(()=>{if(!document.hidden && !$('manage').open)refresh();},60000);
refresh();
const saved=sessionStorage.getItem('account-operation');
if(saved && /^[A-Za-z0-9_-]{20,64}$/.test(saved)) {active={id:saved}; busy=true; $('add').disabled=true; $('manage').showModal(); poll();}
