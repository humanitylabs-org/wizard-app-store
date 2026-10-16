"use strict";
const $ = id => document.getElementById(id);
let snapshot;
const el = (tag, text, cls) => {const node = document.createElement(tag); node.textContent = text || ''; if(cls) node.className = cls; return node;};
function manage(action, account) {
  if(action === 'remove' && !confirm(`Remove ${account.name} from Hermes? This may stop chats using this subscription.`)) return;
  $('instructions').textContent = action === 'add' ? snapshot.management.message : `${action === 'remove' ? 'Removal' : 'Reconnection'} must target the exact credential in Hermes. This preview cannot change it; no subscription has been changed.`;
  $('command').textContent = action === 'add' ? snapshot.management.addCommand : 'hermes auth list ' + (snapshot.provider === 'claude' ? 'anthropic' : 'openai-codex');
  $('manage').showModal();
}
function render(data) {
  snapshot = data;
  $('title').textContent = data.name;
  document.title = data.name;
  $('summary').textContent = `${data.accounts.length} subscription${data.accounts.length === 1 ? '' : 's'} in Hermes`;
  const rows = data.accounts.map(a => {
    const row = el('li', '', 'account'); row.dataset.accountId = a.id;
    const head = el('header'); head.append(el('strong', a.name), el('span', a.status)); row.append(head);
    row.append(el('p', [a.email, a.plan || 'Plan not reported'].filter(Boolean).join(' · '), 'meta'));
    for(const limit of a.usage?.limits || []) {
      const meter = el('meter'); meter.min=0; meter.max=100; meter.value=limit.remainingPercent; meter.setAttribute('aria-label', a.name + ' ' + limit.label + ' remaining');
      row.append(el('p', `${limit.label}: ${limit.remainingPercent}% left`), meter,
        el('small', limit.resetsAt ? 'Resets ' + new Date(limit.resetsAt).toLocaleString() : 'Reset time not reported'));
    }
    if(!a.usage?.limits?.length) row.append(el('p', 'Usage unavailable — not zero.', 'meta'));
    const actions = el('div', '', 'actions');
    for(const action of ['reconnect', 'remove']) {const b = el('button', action === 'reconnect' ? 'Reconnect…' : 'Remove…'); b.addEventListener('click', () => manage(action, a)); actions.append(b);}
    row.append(actions); return row;
  });
  $('accounts').replaceChildren(...rows);
  if(!rows.length) $('accounts').append(el('li', 'No Hermes subscriptions found. A separate Claude Code login is not a Hermes subscription.', 'meta'));
}
async function refresh() {
  $('refresh').disabled=true;
  try {const r=await fetch('api/accounts', {cache:'no-store'}); if(!r.ok) throw new Error(); const data=await r.json(); render(data); $('message').textContent='';}
  catch { $('message').textContent='Hermes inventory unavailable. Any displayed rows are the last reading.'; }
  finally {$('refresh').disabled=false;}
}
$('refresh').addEventListener('click', refresh);
$('add').addEventListener('click', () => {if(snapshot) manage('add');});
$('close').addEventListener('click', () => $('manage').close());
setInterval(() => {if(!document.hidden && !$('manage').open) refresh();}, 60000);
refresh();
