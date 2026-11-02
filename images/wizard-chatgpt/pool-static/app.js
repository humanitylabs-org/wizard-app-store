"use strict";
const $ = id => document.getElementById(id);
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired', 'needs_review']);
const STATUS = {ready: 'Active', connected: 'Active', ok: 'Active', renewing: 'Renewing', expired: 'Sign in again', cooldown: 'Cooling down', exhausted: 'Limit reached', error: 'Problem'};
const OK = new Set(['ready', 'connected', 'ok']);
let snapshot = null, active = null, busy = false, timer = null, intent = null, before = 0, adopting = false;
let dialogHidden = false, lastRootBack = 0, openAccount = null;
// Every pop-up is a kit sheet (wizard-sheet.js): ×, Esc, tap outside, Back and swipe down all close it.
const openSheet = d => { if (window.WzSheet) WzSheet.open(d); else if (!d.open) d.showModal(); };
const manageable = () => snapshot?.management?.contract === 'wizard.account-management/1' && snapshot.management.status === 'available';
const allowed = (action, account, credential) => manageable() && (action === 'add' ? snapshot.actions?.add === true
  : action === 'prefer' ? account?.actions?.prefer === true && account.preferred !== true && Boolean(credential?.id)
  // The original Claude Code sign-in always follows added ones in Hermes; signing that same account in here once
  // makes it an added account the agent can put first (the Claude Code sign-in itself stays as it is).
  : action === 'adopt' ? account?.source === 'legacy-claude-code' && account.actions?.prefer === false && snapshot.actions?.add === true
  : account?.actions?.[action] === true && credential?.managed === true);

const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const provider = () => snapshot?.provider || (location.pathname.includes('claude') ? 'claude' : 'chatgpt');
const brand = () => provider() === 'claude' ? 'Claude' : 'ChatGPT';
const hermesAccounts = () => (snapshot?.accounts || []).filter(a => a.source !== 'legacy-claude-code');
// One line: what the agent can do with this connection.
const WHAT = {claude: 'Your agent thinks and works with your Claude plans.', chatgpt: 'Your agent thinks and works with your ChatGPT plans.'};

// Browser boundary (draft, default-off): inside Wizard's opaque frame (origin null) this page has no route to its own
// api/. Reads and steps go through Wizard's typed operations; account changes are queued for the owner to confirm in
// Wizard's own dialog (never confirm() or an app-side "confirmed"); the sign-in page is opened by Wizard only.
// Same-origin and standalone: unchanged.
const OPAQUE = (() => { try { return parent !== window && globalThis.origin === 'null'; } catch { return true; } })();
const store = (() => { try { const s = window.sessionStorage; s.getItem('x'); return s; } catch { return {getItem: () => null, setItem() {}, removeItem() {}}; } })();
const coded = (code, status) => Object.assign(new Error('Request failed'), {code, status, detail: ''});
const STATUS_OF = {conflict: 409, not_found: 404, busy: 409, not_allowed: 403, confirmation_required: 403, rate_limited: 429};
const ready = () => new Promise(resolve => {
  if (window.WizBoundaryClient?.ready) return resolve(true);
  addEventListener('wizard:boundary:connected', () => resolve(true), {once: true});
  setTimeout(() => resolve(!!window.WizBoundaryClient?.ready), 8000);
});
async function boundary(path, body) {
  if (!(await ready())) throw coded('unavailable', 503);
  for (let i = 0; i < 40 && !window.WizardApp?.intent; i++) await new Promise(r => setTimeout(r, 50));
  if (!window.WizardApp?.intent) throw coded('unavailable', 503);
  const key = () => crypto.randomUUID();
  try {
    if (!body) {
      const m = /^api\/operations\/([A-Za-z0-9_-]{20,64})$/.exec(path);
      if (m) return await WizardApp.data.call({operation: 'ai_accounts.progress', args: {operation: m[1]}});
      if (path === 'api/accounts') return await WizardApp.data.call({operation: 'ai_accounts.inventory', args: {}});
      throw coded('not_found', 404);
    }
    if (body.action === 'submit') return await WizardApp.data.call({operation: 'ai_accounts.step', args: {action: 'submit', operation: body.operation, code: body.code}, operationKey: key()});
    if (body.action === 'cancel') return await WizardApp.data.call({operation: 'ai_accounts.step', args: {action: 'cancel', operation: body.operation}, operationKey: key()});
    // add / reconnect / remove / prefer: the owner confirms in Wizard; the review names exactly these arguments.
    return await WizardApp.intent.confirm({operation: 'ai_accounts.change', args: {action: body.action, target: body.target ?? null}, operationKey: key()});
  } catch (e) {
    if (e.status) throw e;
    const err = coded(e.code || 'failed', STATUS_OF[e.code] || (e.code === 'cancelled' ? 499 : 503));
    err.detail = e.code === 'rate_limited' ? 'Too many requests. Wait a minute.' : e.code === 'outcome_unknown' ? 'Unclear. Check the list first.' : '';
    throw err;
  }
}
// The sign-in page of a running operation: Wizard checks it against what this app may open, then opens it.
async function openSignin(job) {
  if (!job?.signin || !job.id) return;
  try { await WizardApp.intent.open({target: job.signin, ref: 'ai:' + job.id}); }
  catch (e) { if (e.code !== 'cancelled' && active?.id === job.id) setStatus(e.code === 'rate_limited' ? 'Too many requests. Wait a minute.' : 'Could not open the sign-in page.', 'err'); }
}

async function api(path, body) {
  if (OPAQUE) return boundary(path, body);
  const r = await fetch(path, {cache: 'no-store', ...(body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Wizard-Account-Action': '1'}, body: JSON.stringify(body)} : {})});
  if (!r.ok) {
    const e = new Error('Request failed'); e.status = r.status;
    try { const d = await r.json(); e.detail = typeof d.error === 'string' ? d.error : ''; } catch { e.detail = ''; }
    throw e;
  }
  return r.json();
}
// ChatGPT refuses Codex device codes until the owner turns this on once; say so before the code, not after.
const DEVICE_HINT = 'First, in ChatGPT open Settings → Security and turn on “Device code sign-in for Codex”.';

function usedOf(l) {
  if (typeof l.usedPercent === 'number') return Math.round(l.usedPercent);
  if (typeof l.remainingPercent === 'number') return Math.round(100 - l.remainingPercent);
  return null;
}
// A clock time reads better than "in 31 h": today/tomorrow by time, later by weekday.
function whenText(ts) {
  const d = new Date(ts), ms = d - Date.now();
  if (!Number.isFinite(ms)) return '';
  if (ms <= 60000) return 'now';
  const time = d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  const day = n => new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
  const days = Math.round((day(d) - day(new Date())) / 86400000);
  if (days === 0) return ms < 3600000 ? `in ${Math.max(1, Math.round(ms / 60000))} min` : `today ${time}`;
  if (days === 1) return `tomorrow ${time}`;
  return `${d.toLocaleDateString([], {weekday: 'short'})} ${time}`;
}
function resetText(ts) { const w = whenText(ts); return w ? (w === 'now' ? 'Resets now' : `Resets ${w}`) : ''; }
// A full shared meter (session or all-models weekly) stops the account until it resets. A model-scoped
// weekly meter (e.g. one model's own allowance) does not, so it never marks the whole account as stopped.
function blockingLimits(a) {
  return (a.usage?.limits || []).filter(l => !/^weekly_scoped:/.test(String(l.id || '')) && (usedOf(l) ?? 0) >= 100
    && (!l.resetsAt || new Date(l.resetsAt) > Date.now()));
}
function availability(a) {
  if (!OK.has(a.status)) return {ok: false, word: STATUS[a.status] || a.status || 'Unknown'};
  const full = blockingLimits(a);
  if (!full.length) return {ok: true, word: 'Available'};
  const until = full.map(l => l.resetsAt).filter(Boolean).sort().pop() || null;
  const weekly = full.some(l => /week/i.test(String(l.id) + ' ' + String(l.label)));
  return {ok: false, word: weekly ? 'Weekly limit' : 'Session limit', until};
}
const PLAN_NOTE = {claude: {pro: 'Pro has the smallest Claude limits.', 'max 5x': 'Max 5x has about 5× Pro usage.', 'max 20x': 'Max 20x has about 20× Pro usage.'}};
const planNote = plan => PLAN_NOTE[provider()]?.[String(plan || '').trim().toLowerCase()] || '';
const ordered = list => [...list].sort((x, y) => (x.priority ?? 1e9) - (y.priority ?? 1e9));
// The agent orders accounts by itself: the one whose weekly limit resets soonest (and still has room) goes first,
// so no quota expires unused. A seeded Claude Code login can't lead until it is signed in to the agent once.
const autoOn = () => snapshot?.autoOrder?.enabled === true;
const needsLead = a => autoOn() && snapshot.autoOrder.needsSignIn === true && snapshot.autoOrder.wanted === a?.id && allowed('adopt', a);
const AUTO_NOTE = 'Order is automatic: the account that resets soonest is used first.';
function limitLabel(l) {
  const id = String(l.id || '');
  if (id.startsWith('session:')) return 'Session (5 h)';
  if (id.startsWith('weekly_all:')) return 'Weekly · all models';
  return l.label || 'Limit';
}
function grantName(c) {
  const generic = !c.name || /^(openai-codex-oauth|anthropic-oauth|claude-oauth)(-\d+)?$|^device_code$|^claude_code$/.test(c.name);
  return generic ? 'Sign-in ' + String(c.id).slice(0, 4) : c.name;
}

function accountTitle(a) {
  const legacy = a.source === 'legacy-claude-code';
  // A masked email (o***@g***) says nothing; the owner's nickname for that sign-in is the readable title.
  if (a.email && a.email.includes('*') && a.name && a.name !== a.email && !/^Subscription( \d+)?$/.test(a.name)) return {title: a.name, domain: a.email};
  const at = a.email ? a.email.lastIndexOf('@') : -1;
  // Readable on a phone: the name before @ is the title, the domain joins the plan line.
  return {title: at > 0 ? a.email.slice(0, at) : (a.email || a.name || (legacy ? 'Claude Code sign-in' : 'Subscription')), domain: at > 0 ? a.email.slice(at + 1) : ''};
}

function renderAccount(a, i, all) {
  const legacy = a.source === 'legacy-claude-code';
  const li = el('li', 'acct'); li.dataset.accountId = a.id;
  // Every row opens its sheet: plan, limits, use first, and sign-in actions.
  const head = el('button', 'wz-row');
  head.type = 'button'; head.setAttribute('aria-haspopup', 'dialog'); head.addEventListener('click', () => openAccountSheet(a.id));
  // Label each subscription by its signed-in email; the nickname (if different) moves to the second line.
  const {title, domain} = accountTitle(a);
  const nick = a.name && a.name !== a.email && a.name !== title && !legacy && !/^Subscription( \d+)?$/.test(a.name) ? a.name : '';
  const main = el('span', 'wz-main');
  const line = el('b'), tb = el('span', 'name', title); tb.title = a.email || title;
  line.append(tb);
  if (a.plan) line.append(el('span', 'plan', a.plan));
  // Where it sits in the agent's order: the one tried first, then the backups.
  const order = a.preferred ? 'Used first' : (all.length > 1 && a.priority != null ? 'Backup' : '');
  main.append(line, el('small', null, [order, needsLead(a) ? 'Resets soonest' : '', domain, nick].filter(Boolean).join(' · ')));
  // Usage lives inside the row: under the name when narrow, beside it when the window is wide.
  const use = el('span', 'use');
  const state = availability(a);
  const pill = el('span', 'wz-pill ' + (state.ok ? 'ok' : 'warn'), state.word);
  head.append(el('span', 'wz-tile', title.trim().charAt(0).toUpperCase() || '?'), main, use, pill);
  const chev = el('span', 'chev', '›'); chev.setAttribute('aria-hidden', 'true'); head.append(chev);
  li.append(head);
  if (state.until) use.append(el('span', 'back', `Back ${whenText(state.until)}`));

  const limits = a.usage?.limits || [];
  for (const l of limits) {
    const u = usedOf(l), pct = Math.max(0, Math.min(100, u || 0));
    const meter = el('span', 'wz-meter' + (u >= 90 ? ' hot' : '')), label = el('span');
    label.append(el('span', null, limitLabel(l)), el('span', 'meter-val', u == null ? '—' : `${u}% used`));
    if (l.resetsAt) label.append(el('span', 'meter-reset', resetText(l.resetsAt)));
    const bar = el('i'), fill = el('b');
    fill.style.setProperty('--v', pct + '%');
    bar.setAttribute('role', 'meter'); bar.setAttribute('aria-label', `${title} ${l.label}`);
    bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100'); bar.setAttribute('aria-valuenow', String(u ?? 0));
    bar.append(fill); meter.append(label, bar); use.append(meter);
  }
  if (!limits.length) use.append(el('span', 'muted', a.usageStatus === 'unavailable' ? 'Usage unavailable right now' : 'No usage yet'));

  const fix = needsReconnect(a);
  if (fix) {
    // A sign-in that stopped working is fixed in one tap, right on its row.
    const again = el('button', 'link', 'Reconnect'); again.type = 'button'; again.disabled = busy;
    again.dataset.reconnect = a.id;
    again.addEventListener('click', () => ask('reconnect', a, fix));
    li.append(again);
  }
  if (needsLead(a)) {
    // It resets soonest, but the agent can only put it first once it is signed in there too: one tap starts that.
    const lead = el('button', 'link', 'Sign in to use it first'); lead.type = 'button'; lead.disabled = busy;
    lead.dataset.lead = a.id;
    lead.addEventListener('click', () => ask('adopt', a));
    li.append(lead);
  }
  if (legacy && !['ready', 'connected', 'renewing'].includes(a.status)) {
    // The original Claude Code sign-in (the one the agent's Claude Code provider uses) renews on its own page.
    const again = el('a', 'link', 'Sign in again'); again.href = 'claude-code/'; again.dataset.legacySignin = '1';
    li.append(again);
  }
  return li;
}

/* ---------- account sheet: the rare per-account actions ---------- */
function fillAccountSheet() {
  const a = (snapshot?.accounts || []).find(x => x.id === openAccount);
  if (!a) { if ($('account').open) $('account').close(); return; }
  const legacy = a.source === 'legacy-claude-code';
  const {title, domain} = accountTitle(a);
  const state = availability(a);
  $('acct-title').textContent = a.email && !a.email.includes('*') ? a.email : title;
  $('acct-text').textContent = [a.plan ? `${a.plan} plan` : '', state.word + (state.until ? ` until ${whenText(state.until)}` : '')].filter(Boolean).join(' · ') || domain;
  $('acct-plan').textContent = [planNote(a.plan),
    a.preferred ? 'Your agent uses this account first and moves to the next when it hits a limit.'
      : legacy && a.actions?.prefer === false ? 'Your agent switches to this account on its own when the others hit a limit.'
      : (a.priority != null ? 'Your agent uses this account when the ones above it hit a limit.' : ''),
    needsLead(a) ? 'It resets soonest, so it should go first: sign in to it once with Use first.' : ''].filter(Boolean).join(' ');
  const prefer = (a.credentials || [])[0];
  const how = allowed('prefer', a, prefer) ? 'prefer' : allowed('adopt', a) ? 'adopt' : '';
  $('acct-auto').hidden = !autoOn() || !how;
  $('acct-auto').textContent = 'The order is automatic (soonest reset first), so a choice made here may change at the next reorder.';
  $('prefer').hidden = !how; $('prefer').disabled = busy;
  $('prefer').onclick = () => { $('account').close(); ask(how, a, prefer); };
  // The original Claude Code sign-in signs in and out on its own page.
  $('legacy-manage').hidden = !legacy;
  const rows = (legacy ? [] : (a.credentials || [])).map(c => {
    const r = el('div', 'grant');
    r.append(el('span', 'grant-name', grantName(c)));
    if (manageable() && c.managed === true) {
      for (const action of ['reconnect', 'remove']) {
        if (!allowed(action, a, c)) continue;
        const b = el('button', 'link' + (action === 'remove' ? ' danger' : ''), action === 'reconnect' ? 'Reconnect' : 'Remove');
        b.type = 'button'; b.disabled = busy;
        b.addEventListener('click', () => { $('account').close(); ask(action, a, c); });
        r.append(b);
      }
    }
    return r;
  });
  $('grants').replaceChildren(...rows);
}
function openAccountSheet(id) { openAccount = id; fillAccountSheet(); openSheet($('account')); }
$('account').addEventListener('close', () => { openAccount = null; });

// One sentence on what the agent can do right now, so a limit is never hidden behind "Active".
function summary(accounts) {
  if (!accounts.length) return '';
  const list = ordered(accounts), open = list.find(a => availability(a).ok);
  const name = a => accountTitle(a).title + (a.plan ? ` (${a.plan})` : '');
  if (open) return list.length > 1 ? `Using ${name(open)} now.` : '';
  const back = list.map(a => availability(a).until).filter(Boolean).sort()[0];
  return `Every account is at its limit${back ? `; the first is back ${whenText(back)}` : ''}.`;
}

function renderDetails(data) {
  const facts = [
    ['Service', data.name || brand()],
    ['Accounts', String(data.accounts.length)],
    ['Agent sign-ins', data.management?.status || 'unknown'],
    ['Note', data.management?.message || ''],
    ['Agent', data.agent || ''],
    ['Contract', data.management?.contract || ''],
    ...data.accounts.map(a => ['Account ' + String(a.id).slice(0, 12), [a.source || 'agent', a.status, (a.credentials || []).length + ' sign-in(s)'].filter(Boolean).join(' · ')])
  ].filter(([, v]) => v);
  $('details').replaceChildren(...facts.flatMap(([k, v]) => [el('dt', null, k), el('dd', null, v)]));
}

function render(data) {
  snapshot = data;
  $('title').textContent = data.name || brand();
  document.title = data.name || brand();
  $('conn-name').textContent = data.name || brand();
  if (!$('sigil').getAttribute('src')) $('sigil').src = `logo-${provider() === 'claude' ? 'claude' : 'chatgpt'}.svg`;
  const n = data.accounts.length;
  $('count').textContent = String(n); $('count').hidden = !n;
  $('accounts').replaceChildren(...ordered(data.accounts).map(renderAccount));
  $('conn-line').textContent = summary(data.accounts) || WHAT[provider()] || '';
  const lead = data.accounts.find(needsLead);
  $('order-note').hidden = !autoOn() || n < 2;
  $('order-note').textContent = AUTO_NOTE + (lead ? ` ${accountTitle(lead).title} resets soonest: sign in to it once so your agent can use it first.` : '');
  // One status for the whole connection: Connected when any account works.
  // A fresh Wizard has no account broker, so the inventory is "unavailable" by design: its Claude Code sign-in is the
  // agent's own, so a working one is simply Connected (it said Needs attention while chats worked).
  const legacyOk = data.legacySignin === true && data.accounts.some(a => a.source === 'legacy-claude-code' && OK.has(a.status));
  const [kind, word] = legacyOk ? ['ok', 'Connected'] : data.inventoryStatus === 'unavailable' ? ['warn', 'Needs attention']
    : data.accounts.some(a => OK.has(a.status)) ? ['ok', 'Connected'] : n ? ['warn', 'Needs attention'] : ['off', 'Not connected'];
  $('conn-pill').className = 'wz-pill ' + kind; $('conn-pill').textContent = word;
  renderDetails(data);
  if (openAccount) fillAccountSheet();
  // The agent could not be asked (or cannot take sign-ins from here): say why with a Retry, never a dead Sign in.
  const problem = data.inventoryStatus === 'unavailable' ? (data.error?.message || 'Can’t reach your agent right now.')
    : (data.management?.status === 'off' && !n ? (data.management.message || 'Signing in from this app is switched off on your agent.') : '');
  $('problem').hidden = !problem || data.legacySignin === true;
  $('problem-text').textContent = problem;
  $('empty').hidden = n > 0 || !$('problem').hidden;
  const resume = dialogHidden && busy;
  const fallback = legacyFallback();
  $('add').hidden = !resume && !allowed('add') && !fallback;
  $('add').disabled = !resume && !fallback && (busy || !allowed('add'));
  $('add').textContent = resume ? 'Resume sign-in' : (n && !fallback ? 'Add account' : 'Connect');
}

// Without the agent's account broker (the fresh-mode Hermes Agent app or an older plugin) Claude still signs in the
// original way: the official Claude Code login on its own page, which that agent shares. The server decides
// (`legacySignin`): on an alongside box that login would not reach the agent, so the page says why instead.
function legacyFallback() {
  if (provider() !== 'claude' || allowed('add') || snapshot?.legacySignin !== true) return false;
  return !(snapshot?.accounts || []).some(a => ['ready', 'connected', 'renewing'].includes(a.status));
}

// The managed sign-in to reconnect when an account stopped working (expired, a problem, or no usage reading).
function needsReconnect(a) {
  if (a.source === 'legacy-claude-code') return null;
  if (OK.has(a.status) && a.usageStatus !== 'unavailable') return null;
  return (a.credentials || []).find(c => allowed('reconnect', a, c)) || null;
}

const PARAMS = new URLSearchParams(location.search);
const CONNECT = PARAMS.get('connect') === '1';
// `?reconnect=<account id>` (or `?reconnect=1`: the first account that needs it) opens Reconnect directly, so
// Home, the model picker or a notification can send the owner straight to the fix.
const RECONNECT = PARAMS.get('reconnect');
let reconnectTried = false;
function autoReconnect() {
  if (!RECONNECT || reconnectTried || busy || !snapshot) return;
  reconnectTried = true;
  const list = snapshot.accounts || [];
  const a = RECONNECT === '1' ? list.find(needsReconnect) : list.find(x => x.id === RECONNECT);
  if (!a) return;
  const c = needsReconnect(a) || (a.credentials || []).find(x => allowed('reconnect', a, x));
  if (c) { ask('reconnect', a, c); return; }
  if (a.source === 'legacy-claude-code') location.replace('claude-code/?connect=1');
}
let connectTried = false;
function autoConnect() {
  if (!CONNECT || connectTried || busy || !snapshot) return;
  connectTried = true;
  // Fresh Wizard (no account broker): the sign-in is the plain Claude Code page; open it straight at its link and code.
  if (legacyFallback()) { location.replace('claude-code/?connect=1'); return; }
  if (hermesAccounts().length || !allowed('add')) return; // already signed in, or sign-in unavailable: show the app as is
  ask('add'); start();
}

async function refresh() {
  $('refresh').classList.add('spin');
  try {
    const data = await api('api/accounts');
    render(data);
    autoConnect();
    autoReconnect();
    $('message').textContent = data.error && data.inventoryStatus !== 'unavailable' ? 'Problem reading accounts.' : '';
  } catch (e) {
    if (snapshot) render({...snapshot, management: {status: 'unavailable'}});
    else { $('conn-name').textContent = $('title').textContent = brand(); if (!$('sigil').getAttribute('src')) $('sigil').src = `logo-${provider() === 'claude' ? 'claude' : 'chatgpt'}.svg`; }
    $('add').hidden = true;
    // Browser boundary on: this page's own api/ answers only Wizard's adapter, so a plain tab gets 403.
    $('message').textContent = e?.status === 403 && !OPAQUE ? 'Open this app from Wizard to see and change your accounts.' : 'Offline. Showing last reading.';
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
  if (busy || !allowed(action, account, credential)) return;
  intent = {action, account, credential}; active = null;
  dialogHidden = false;
  const b = brand();
  $('steps').hidden = true; setStatus('');
  if (action === 'add') {
    $('dlg-title').textContent = `Sign in to ${b}`;
    $('dlg-text').textContent = provider() === 'chatgpt'
      ? DEVICE_HINT + (hermesAccounts().length ? ' Use an account not listed yet.' : '')
      : '';
    showButtons({go: true, goLabel: 'Continue'});
  } else if (action === 'adopt') {
    $('dlg-title').textContent = `Use ${accountTitle(account).title} first?`;
    $('dlg-text').textContent = `Sign in to ${account.email || 'this account'} once more so your agent can put it first. Nothing signs out. If your browser is signed in to another Claude account, use a private window.`;
    showButtons({go: true, goLabel: 'Continue'});
  } else if (action === 'prefer') {
    $('dlg-title').textContent = `Use ${accountTitle(account).title} first?`;
    $('dlg-text').textContent = 'Your agent will try this account first and move to the others when it hits a limit. Nothing signs out.';
    showButtons({go: true, goLabel: 'Use first'});
  } else if (action === 'reconnect') {
    $('dlg-title').textContent = `Reconnect ${account.name}`;
    $('dlg-text').textContent = '';
    showButtons({go: true, goLabel: 'Continue'});
  } else {
    $('dlg-title').textContent = 'Remove this sign-in?';
    $('dlg-text').textContent = `${grantName(credential)} · ${account.name}`;
    showButtons({go: true, goLabel: 'Remove', danger: true});
  }
  openSheet($('manage'));
}

async function start() {
  const {action, account, credential} = intent;
  if (!allowed(action, account, credential)) return;
  busy = true; $('add').disabled = true; $('go').disabled = true; $('cancel').disabled = true;
  before = hermesAccounts().length;
  setStatus(action === 'remove' ? 'Removing…' : action === 'prefer' ? 'Updating…' : 'Starting…');
  adopting = action === 'adopt';
  try {
    display(await api('api/operations', adopting ? {action: 'add', label: '', confirmed: true}
      : {action, target: credential?.id, label: '', confirmed: true}));
  } catch (e) {
    busy = false; $('add').disabled = false;
    if (e.code === 'cancelled') { setStatus('Nothing changed.'); showButtons({go: true, goLabel: $('go').textContent, cancel: true}); return; }
    setStatus(e.status === 409 ? 'Another sign-in is running.' : (e.detail || 'Could not start. Try again.'), 'err');
    showButtons({cancel: true, cancelLabel: 'Close'});
  }
}

function display(job) {
  if (active?.id === job.id && TERMINAL.has(active.status) && !TERMINAL.has(job.status)) return;
  clearTimeout(timer); active = job;
  if (!$('manage').open && !dialogHidden) openSheet($('manage'));
  if (!TERMINAL.has(job.status)) {
    // ChatGPT: copy the code first, then open the sign-in page and paste it there.
    $('dlg-text').textContent = job.userCode ? DEVICE_HINT : '';
    $('steps').hidden = !(job.url || job.signin || job.userCode || job.inputRequired);
    $('signin').href = job.url || '#'; $('signin-step').hidden = !(job.url || job.signin);
    $('signin').textContent = job.userCode ? 'Open sign-in and paste the code' : 'Open sign-in';
    $('code-step').hidden = !job.userCode; $('user-code').textContent = job.userCode || '';
    $('paste-step').hidden = !job.inputRequired;
    setStatus(job.url || job.signin ? 'Waiting…' : 'Starting…', 'wait');
    showButtons({cancel: true, cancelLabel: 'Cancel'});
    store.setItem('account-operation', job.id);
    timer = setTimeout(poll, 1500);
    return;
  }
  store.removeItem('account-operation');
  busy = false; $('steps').hidden = true;
  showButtons({cancel: false, close: true});
  const done = {
    succeeded: job.action === 'remove' ? 'Removed.' : job.action === 'prefer' ? 'Done. Your agent uses this account first.' : 'Connected.',
    cancelled: 'Cancelled.',
    expired: 'Timed out. Try again.',
    failed: 'Did not finish. Try again.',
    needs_review: 'Unclear. Check the list first.'
  }[job.status];
  setStatus(done, job.status === 'succeeded' ? 'ok' : (job.status === 'cancelled' ? '' : 'err'));
  $('dlg-text').textContent = provider() === 'chatgpt' && ['failed', 'expired'].includes(job.status)
    ? 'If ChatGPT refused the code: ' + DEVICE_HINT.replace(/^First, in/, 'in') + ' Then try again.' : '';
  const adopted = adopting && job.action === 'add' && job.status === 'succeeded';
  const adoptFor = adopting ? intent?.account : null;
  adopting = false;
  refresh().then(async () => {
    if (adopted) return finishAdopt(job, adoptFor);
    // Success means the agent itself now lists the sign-in; if it does not, say so rather than “Connected”.
    if (job.status === 'succeeded' && job.action !== 'remove' && snapshot?.inventoryStatus === 'unavailable') {
      setStatus('Signed in, but your agent can’t be reached to confirm it. Retry in a moment.', 'err');
    }
    if (job.status === 'succeeded' && job.action === 'add' && (job.duplicateOf || (before > 0 && hermesAccounts().length <= before))) {
      const same = findByCredential([job.duplicateOf, ...(job.credentialIds || [])]);
      $('dlg-title').textContent = 'Already added';
      setStatus(`${same ? `You signed in as ${accountTitle(same).title}, which` : 'That account'} is already listed. Sign out of ${provider() === 'claude' ? 'claude.ai' : brand()} in that browser or use a private window, then try again.`, 'err');
    }
  });
}

// After signing the original Claude Code account in once more: when the agent now lists it as an added
// account (the original row folds into it), put it first in the same step; otherwise say what happened.
const findByCredential = ids => (snapshot?.accounts || []).find(a => (a.credentials || []).some(c => ids.includes(c.id)));
async function finishAdopt(job, account) {
  const stillSeparate = (snapshot?.accounts || []).some(a => a.source === 'legacy-claude-code');
  const id = (job.credentialIds || [])[0];
  if (job.duplicateOf || stillSeparate || !id) {
    // The browser was signed in to another Claude account. A second sign-in to an account the agent already has is
    // removed again by the agent (when the older one still works), so nothing is left over; a new account is kept.
    const other = findByCredential([job.duplicateOf, id].filter(Boolean).filter(x => !(account?.credentials || []).some(c => c.id === x)));
    const me = account ? (account.email && !account.email.includes('*') ? account.email : accountTitle(account).title) : 'this one';
    $('dlg-title').textContent = 'Signed in to a different account';
    setStatus(`You signed in as ${other ? accountTitle(other).title : 'another account'}, not ${me}. Sign out of claude.ai in that browser or use a private window, then try again.`
      + (!job.duplicateOf && other ? ' That account was kept as an extra account.' : ''), 'err');
    return;
  }
  busy = true; setStatus('Putting it first…', 'wait');
  try { display(await api('api/operations', {action: 'prefer', target: id, label: '', confirmed: true})); }
  catch { busy = false; setStatus('Signed in. Open it and choose Use first.', 'err'); }
}

async function poll() {
  const id = active.id;
  try { const job = await api('api/operations/' + id); if (active?.id === id) display(job); }
  catch (e) {
    if (active?.id !== id || TERMINAL.has(active.status)) return;
    if (e.status === 404) display({...active, status: 'needs_review'});
    else { setStatus('Checking…'); timer = setTimeout(poll, 3000); }
  }
}

$('go').addEventListener('click', start);
// Opaque frame: the link has no URL; Wizard opens the reviewed sign-in page after the owner confirms it there.
$('signin').addEventListener('click', e => { if (!OPAQUE) return; e.preventDefault(); openSignin(active); });
$('cancel').addEventListener('click', async () => {
  if (!busy || !active?.id) { $('manage').close(); return; }
  $('cancel').disabled = true; setStatus('Cancelling…');
  try { display(await api('api/operations', {action: 'cancel', operation: active.id})); }
  catch { setStatus('Checking…'); $('cancel').disabled = false; }
});
$('close').addEventListener('click', () => $('manage').close());
// Closing the sheet any way (×, Esc, outside, Back, swipe) while a sign-in runs only hides it: the sign-in keeps
// going and the main button offers "Resume sign-in". Cancel is the one control that stops it.
$('manage').addEventListener('close', () => { if (busy) { dialogHidden = true; if (snapshot) render(snapshot); } });
$('copy').addEventListener('click', async () => {
  const code = $('user-code').textContent;
  try { await navigator.clipboard.writeText(code); $('copy').textContent = 'Copied'; }
  catch { const r = document.createRange(); r.selectNodeContents($('user-code')); getSelection().removeAllRanges(); getSelection().addRange(r); $('copy').textContent = 'Selected'; }
  setTimeout(() => { $('copy').textContent = 'Copy'; }, 1800);
});
$('submit-code').addEventListener('click', async () => {
  const code = $('code').value.trim(); if (!code) return;
  $('code').value = ''; $('submit-code').disabled = true; setStatus('Checking…');
  try { display(await api('api/operations', {action: 'submit', operation: active.id, code})); }
  catch { setStatus('Checking… do not paste again.'); }
  finally { $('submit-code').disabled = false; }
});
$('refresh').addEventListener('click', refresh);
$('retry').addEventListener('click', refresh);
$('add').addEventListener('click', () => {
  if (dialogHidden && busy && active) { dialogHidden = false; display(active); render(snapshot); }
  else if (legacyFallback()) location.href = 'claude-code/';
  else if (snapshot) ask('add');
});

// Back closes local UI without cancelling provider work or leaving the app.
// A plain tab allows exit only on a second root Back within two seconds.
if (OPAQUE) {
  // Wizard's Back reaches an opaque page through WizardApp.back: close the open sheet first, then leave.
  ready().then(() => window.WizardApp?.back?.register({canGoBack: () => $('manage').open || $('account').open,
    back: () => { if ($('manage').open) { dialogHidden = busy; $('manage').close(); if (snapshot) render(snapshot); } else $('account').close(); return true; }}));
} else {
history.replaceState({...history.state, wizardSubscriptions: 'root'}, '');
history.pushState({...history.state, wizardSubscriptions: 'guard'}, '');
}
if (!OPAQUE) addEventListener('popstate', () => {
  if ($('manage').open) {
    dialogHidden = busy;
    $('manage').close();
    if (snapshot) render(snapshot);
    lastRootBack = 0;
  } else if ($('account').open) {
    $('account').close();
    lastRootBack = 0;
  } else {
    const now = Date.now();
    if (parent === window && lastRootBack && now - lastRootBack < 2000) { history.back(); return; }
    lastRootBack = now;
    $('message').textContent = parent === window ? 'Press back again to exit' : 'Subscriptions home.';
  }
  history.pushState({...history.state, wizardSubscriptions: 'guard'}, '');
});
setInterval(() => { if (!document.hidden && !$('manage').open) refresh(); }, 60000);

refresh();
const saved = store.getItem('account-operation');
if (saved && /^[A-Za-z0-9_-]{20,64}$/.test(saved)) {
  busy = true; $('add').disabled = true; active = {id: saved};
  $('dlg-title').textContent = 'Signing in'; $('dlg-text').textContent = '';
  showButtons({cancel: true, cancelLabel: 'Cancel'}); openSheet($('manage')); poll();
}
