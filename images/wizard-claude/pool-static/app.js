"use strict";
const $ = id => document.getElementById(id);
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired', 'needs_review']);
const STATUS = {ready: 'Ready', connected: 'Ready', expired: 'Sign in again', cooldown: 'Cooling down', exhausted: 'Limit reached', error: 'Problem'};
let snapshot = null, active = null, busy = false, timer = null, intent = null, before = 0;
const openManage = new Set();

const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const provider = () => snapshot?.provider || (location.pathname.includes('claude') ? 'claude' : 'chatgpt');
const brand = () => provider() === 'claude' ? 'Claude' : 'ChatGPT';
const hermesAccounts = () => (snapshot?.accounts || []).filter(a => a.source !== 'legacy-claude-code');

async function api(path, body) {
  const r = await fetch(path, {cache: 'no-store', ...(body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Wizard-Account-Action': '1'}, body: JSON.stringify(body)} : {})});
  if (!r.ok) { const e = new Error('Request failed'); e.status = r.status; throw e; }
  return r.json();
}

function usedOf(l) {
  if (typeof l.usedPercent === 'number') return Math.round(l.usedPercent);
  if (typeof l.remainingPercent === 'number') return Math.round(100 - l.remainingPercent);
  return null;
}
function resetText(ts) {
  const ms = new Date(ts) - Date.now();
  if (!Number.isFinite(ms)) return '';
  if (ms <= 0) return 'Resets now';
  const m = Math.round(ms / 60000);
  if (m < 60) return `Resets in ${m} min`;
  const h = Math.round(m / 60);
  if (h < 36) return `Resets in ${h} h`;
  return `Resets in ${Math.round(h / 24)} days`;
}
function grantName(c) {
  const generic = !c.name || /^(openai-codex-oauth|anthropic-oauth|claude-oauth)(-\d+)?$|^device_code$|^claude_code$/.test(c.name);
  return generic ? 'Sign-in ' + String(c.id).slice(0, 4) : c.name;
}

function renderAccount(a) {
  const legacy = a.source === 'legacy-claude-code';
  const li = el('li', 'acct'); li.dataset.accountId = a.id;
  const head = el('div', 'wz-row acct-head');
  const title = legacy ? 'Claude Code sign-in' : (a.name || a.email || 'Subscription');
  const main = el('span', 'wz-main');
  main.append(el('b', null, title), el('small', null, [a.plan, a.email].filter(Boolean).join(' · ') || 'Plan not reported'));
  const ok = ['ready', 'connected'].includes(a.status);
  head.append(el('span', 'wz-tile', title.trim().charAt(0).toUpperCase() || '?'), main, el('span', 'pill ' + (ok ? 'ok' : 'warn'), STATUS[a.status] || a.status || 'Unknown'));
  li.append(head);

  const limits = a.usage?.limits || [];
  if (limits.length) {
    const box = el('div', 'meters');
    for (const l of limits) {
      const u = usedOf(l), row = el('div', 'meter'), top = el('div', 'meter-top');
      top.append(el('span', null, l.label), el('span', 'meter-val', u == null ? '—' : `${u}% used`));
      const bar = el('div', 'bar'), fill = el('i');
      fill.style.width = Math.max(0, Math.min(100, u || 0)) + '%';
      if (u >= 90) bar.classList.add('hot');
      bar.setAttribute('role', 'meter'); bar.setAttribute('aria-label', `${title} ${l.label}`);
      bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100'); bar.setAttribute('aria-valuenow', String(u ?? 0));
      bar.append(fill); row.append(top, bar);
      if (l.resetsAt) row.append(el('small', 'meter-reset', resetText(l.resetsAt)));
      box.append(row);
    }
    li.append(box);
  } else li.append(el('p', 'muted', 'Usage not available yet'));

  if (legacy) {
    li.append(el('p', 'muted', 'Existing sign-in, left as is. Use Add subscription to manage Claude accounts here.'));
    return li;
  }
  const creds = a.credentials || [];
  if (creds.length) {
    const det = el('details', 'manage');
    det.open = openManage.has(a.id);
    det.addEventListener('toggle', () => det.open ? openManage.add(a.id) : openManage.delete(a.id));
    det.append(el('summary', null, creds.length === 1 ? 'Manage' : `Manage · ${creds.length} sign-ins`));
    for (const c of creds) {
      const r = el('div', 'grant');
      r.append(el('span', 'grant-name', grantName(c)));
      if (c.managed && snapshot?.management?.status !== 'off') {
        for (const action of ['reconnect', 'remove']) {
          const b = el('button', 'link' + (action === 'remove' ? ' danger' : ''), action === 'reconnect' ? 'Reconnect' : 'Remove');
          b.type = 'button'; b.disabled = busy;
          b.addEventListener('click', () => ask(action, a, c));
          r.append(b);
        }
      } else r.append(el('small', null, 'Managed outside Wizard'));
      det.append(r);
    }
    li.append(det);
  }
  return li;
}

function render(data) {
  snapshot = data;
  $('title').textContent = data.name || brand();
  document.title = data.name || brand();
  const n = data.accounts.length;
  $('count').textContent = String(n); $('count').hidden = !n;
  $('accounts').replaceChildren(...data.accounts.map(renderAccount));
  $('empty').hidden = n > 0;
  $('add').hidden = data.management?.status === 'off';
  $('add').disabled = busy || data.management?.status === 'blocked' || data.actions?.add === false;
  $('updated').textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
}

async function refresh() {
  $('refresh').classList.add('spin');
  try {
    const data = await api('api/accounts');
    render(data);
    $('message').textContent = ['blocked', 'off'].includes(data.management?.status) ? data.management.message : (data.error || '');
  } catch {
    $('message').textContent = 'Could not reach Hermes. Showing the last reading.';
  } finally { $('refresh').classList.remove('spin'); }
}

/* ---------- dialog ---------- */
function setStatus(text, kind) { const s = $('dlg-status'); s.textContent = text || ''; s.className = 'dlg-status' + (kind ? ' ' + kind : ''); }
function showButtons({go = false, goLabel = 'Continue', danger = false, cancel = true, cancelLabel = 'Cancel', close = false}) {
  $('go').hidden = !go; $('go').textContent = goLabel; $('go').classList.toggle('danger', danger); $('go').disabled = false;
  $('cancel').hidden = !cancel; $('cancel').textContent = cancelLabel; $('cancel').disabled = false;
  $('close').hidden = !close;
}

function ask(action, account, credential) {
  if (busy) return;
  intent = {action, account, credential}; active = null;
  const b = brand();
  $('steps').hidden = true; $('nick').value = ''; setStatus('');
  $('nick-wrap').hidden = action !== 'add';
  if (action === 'add') {
    $('dlg-title').textContent = `Add a ${b} subscription`;
    $('dlg-text').textContent = provider() === 'chatgpt'
      ? 'Use a ChatGPT account that is not listed yet. If your browser is already signed in to ChatGPT, sign out first or open the link in a private window, otherwise the same account is added again.'
      : 'Sign in with the Claude account you want to add. You will paste a code back here.';
    showButtons({go: true, goLabel: 'Start sign-in'});
  } else if (action === 'reconnect') {
    $('dlg-title').textContent = `Reconnect ${account.name}`;
    $('dlg-text').textContent = 'Sign in again with this same account. The current sign-in stays until you remove it.';
    showButtons({go: true, goLabel: 'Start sign-in'});
  } else {
    $('dlg-title').textContent = 'Remove this sign-in?';
    $('dlg-text').textContent = `${grantName(credential)} on ${account.name}. Your agent stops using it. Other sign-ins stay.`;
    showButtons({go: true, goLabel: 'Remove', danger: true});
  }
  if (!$('manage').open) $('manage').showModal();
}

async function start() {
  const {action, credential} = intent;
  busy = true; $('add').disabled = true; $('go').disabled = true; $('cancel').disabled = true;
  before = hermesAccounts().length;
  setStatus(action === 'remove' ? 'Removing…' : 'Starting sign-in…');
  try {
    display(await api('api/operations', {action, target: credential?.id, label: action === 'add' ? $('nick').value.trim() : '', confirmed: true}));
  } catch (e) {
    busy = false; $('add').disabled = false;
    setStatus(e.status === 409 ? 'Another sign-in is already running. Finish or cancel it first.' : 'Could not start. Nothing was changed; try again in a moment.', 'err');
    showButtons({cancel: true, cancelLabel: 'Close'});
  }
}

function display(job) {
  if (active?.id === job.id && TERMINAL.has(active.status) && !TERMINAL.has(job.status)) return;
  clearTimeout(timer); active = job;
  if (!$('manage').open) $('manage').showModal();
  $('nick-wrap').hidden = true;
  if (!TERMINAL.has(job.status)) {
    $('dlg-text').textContent = '';
    $('steps').hidden = !(job.url || job.userCode || job.inputRequired);
    $('signin').href = job.url || '#'; $('signin-step').hidden = !job.url;
    $('signin').textContent = `Open ${brand()} sign-in`;
    $('code-step').hidden = !job.userCode; $('user-code').textContent = job.userCode || '';
    $('paste-step').hidden = !job.inputRequired;
    setStatus(job.url ? 'Waiting for you to finish signing in…' : 'Starting sign-in…', 'wait');
    showButtons({cancel: true, cancelLabel: 'Cancel sign-in'});
    sessionStorage.setItem('account-operation', job.id);
    timer = setTimeout(poll, 1500);
    return;
  }
  sessionStorage.removeItem('account-operation');
  busy = false; $('steps').hidden = true;
  showButtons({cancel: false, close: true});
  const done = {
    succeeded: job.action === 'remove' ? 'Sign-in removed.' : 'Connected.',
    cancelled: 'Sign-in cancelled. Nothing changed.',
    expired: 'The sign-in timed out. Nothing changed; start again when ready.',
    failed: 'The sign-in did not finish. Nothing changed; try again.',
    needs_review: 'Not sure whether this finished. Check the list before trying again.'
  }[job.status];
  setStatus(done, job.status === 'succeeded' ? 'ok' : (job.status === 'cancelled' ? '' : 'err'));
  refresh().then(() => {
    if (job.status === 'succeeded' && job.action === 'add' && before > 0 && hermesAccounts().length <= before) {
      $('dlg-title').textContent = 'That account is already here';
      setStatus(`You signed in to an account that is already listed, so no new subscription was added. Sign out of ${brand()} in your browser (or use a private window), then add again with the other account.`, 'err');
    }
  });
}

async function poll() {
  const id = active.id;
  try { const job = await api('api/operations/' + id); if (active?.id === id) display(job); }
  catch (e) {
    if (active?.id !== id || TERMINAL.has(active.status)) return;
    if (e.status === 404) display({...active, status: 'needs_review'});
    else { setStatus('Checking status…'); timer = setTimeout(poll, 3000); }
  }
}

$('go').addEventListener('click', start);
$('cancel').addEventListener('click', async () => {
  if (!busy || !active?.id) { $('manage').close(); return; }
  $('cancel').disabled = true; setStatus('Cancelling…');
  try { display(await api('api/operations', {action: 'cancel', operation: active.id})); }
  catch { setStatus('Cancel not confirmed yet; checking…'); $('cancel').disabled = false; }
});
$('close').addEventListener('click', () => $('manage').close());
$('manage').addEventListener('cancel', e => { if (busy) e.preventDefault(); });
$('copy').addEventListener('click', async () => {
  const code = $('user-code').textContent;
  try { await navigator.clipboard.writeText(code); $('copy').textContent = 'Copied'; }
  catch { const r = document.createRange(); r.selectNodeContents($('user-code')); getSelection().removeAllRanges(); getSelection().addRange(r); $('copy').textContent = 'Selected'; }
  setTimeout(() => { $('copy').textContent = 'Copy'; }, 1800);
});
$('submit-code').addEventListener('click', async () => {
  const code = $('code').value.trim(); if (!code) return;
  $('code').value = ''; $('submit-code').disabled = true; setStatus('Checking code…');
  try { display(await api('api/operations', {action: 'submit', operation: active.id, code})); }
  catch { setStatus('Not sure the code went through; checking. Do not paste it again.'); }
  finally { $('submit-code').disabled = false; }
});
$('refresh').addEventListener('click', refresh);
$('add').addEventListener('click', () => { if (snapshot) ask('add'); });
setInterval(() => { if (!document.hidden && !$('manage').open) refresh(); }, 60000);

refresh();
const saved = sessionStorage.getItem('account-operation');
if (saved && /^[A-Za-z0-9_-]{20,64}$/.test(saved)) {
  busy = true; $('add').disabled = true; active = {id: saved};
  $('dlg-title').textContent = 'Sign-in in progress'; $('dlg-text').textContent = ''; $('nick-wrap').hidden = true;
  showButtons({cancel: true, cancelLabel: 'Cancel sign-in'}); $('manage').showModal(); poll();
}
