"""Provider UI and narrow authenticated proxy to the Hermes lifecycle broker."""
import re
import base64
import hashlib
import hmac
import json
import math
import os
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from pool_client import Hermes, BridgeError, REASONS, alongside, agent_address, adopt_as_agent_default, CHATGPT_PROVIDER
import server as owner

PROVIDER = os.environ.get('WIZARD_POOL_PROVIDER', 'chatgpt')
assert PROVIDER in ('chatgpt', 'claude')
PREFIX = 'WIZARD_' + PROVIDER.upper()
ROOT = Path(__file__).parent / 'pool-static'
PASSWORD = os.environ.get(PREFIX + '_PASSWORD', '')
LEGACY_PREFIX = '/claude-code'
LEGACY = None
LEGACY_RENEW = None
if PROVIDER == 'claude':
    import server as claude_owner
    LEGACY = claude_owner.CONNECTION
    LEGACY_RENEW = claude_owner.renew_if_expired
    # Fresh mode: the Claude Code sign-in on this page is the agent's model; give the agent it when it has none.
    claude_owner.State.after_sign_in = lambda: adopt_as_agent_default(PROVIDER)


def is_mirror(row):
    """Hermes' pool copy of the host Claude Code login. Current plugins flag it; older plugins (before the
    flag) list it as an unmanaged grant labelled claude_code, which must not count as a second subscription."""
    if row.get('mirror') == 'claude-code':
        return True
    creds = row.get('credentials') or []
    return bool(creds) and all(c.get('managed') is not True and c.get('name') == 'claude_code' for c in creds)


def same_origin(headers):
    """Browser-only request guard used when no page password is set (a Tailscale-only box): the owner's own
    page may change accounts; a cross-site page may not. Non-browser callers on the app network have no
    Origin and still need the custom action header, which a cross-site form cannot send."""
    origin = headers.get('Origin')
    if origin and urlsplit(origin).netloc != headers.get('Host'):
        return False
    return headers.get('Sec-Fetch-Site') in (None, 'same-origin', 'none')


def masked(email):
    """The plugin's display mask for an email (first letter of each part), so the original Claude Code sign-in can be
    matched against an agent row that only carries the masked form."""
    email = str(email or '')
    if '@' not in email:
        return None
    local, domain = email.rsplit('@', 1)
    return (local[:1] + '***@' + domain[:1] + '***') if local and domain else None


def email_hash(email):
    email = str(email or '').strip().lower()
    return hashlib.sha256(email.encode()).hexdigest()[:16] if '@' in email else None


def reports_hashes(result):
    """Whether the agent's plugin reports `emailHash` (Agent Service #196 and later). It says so in `identity`
    (#203); a plugin between those two shows it by hashing at least one row."""
    return bool((result.get('identity') or {}).get('emailHash')) or any(a.get('emailHash') for a in result.get('accounts') or [])


def same_account(row, email, exact=False):
    """Whether an agent pool row is the same Claude account as the original sign-in. Exact when the plugin reports an
    email hash. Only an older plugin, which never reports one (`exact` False), falls back to the masked email, and only
    on an alongside box (where that original sign-in is not what the agent uses). With a current plugin a row without a
    hash is an unattested account: it stays its own row, since `h***@e***` is both heidi@ and hank@."""
    if not email:
        return False
    if row.get('emailHash'):
        return hmac.compare_digest(str(row['emailHash']), email_hash(email) or '')
    if exact:
        return False
    return alongside(PROVIDER) and bool(masked(email)) and row.get('email') == masked(email)


GENERIC_NAME = re.compile(r'^(?:openai-codex|anthropic|claude|chatgpt)-oauth(?:-\d+)?$|^(?:device_code|claude_code)$')


def friendly_names(accounts, brand):
    """Hermes names a sign-in without an email claim `openai-codex-oauth-1`; Home shows the account name whenever the
    email is masked, so it read that label. Such rows become 'ChatGPT', 'ChatGPT 2', ... by position; an owner's own
    nickname is kept."""
    for n, account in enumerate(accounts, 1):
        name = str(account.get('name') or '')
        if not name or GENERIC_NAME.match(name):
            account['name'] = brand if n == 1 else '%s %d' % (brand, n)
    return accounts


def legacy_signin(result):
    """Whether Sign in may fall back to the original Claude Code page. Only where that login is the agent's own (the
    fresh-mode Hermes Agent app shares its volume) and the agent has no account broker. On an alongside box the agent
    is the host Hermes: a login on that page would not reach it, so the page shows why instead."""
    if PROVIDER != 'claude' or alongside(PROVIDER):
        return False
    management = result.get('management') or {}
    if management.get('contract') == 'wizard.account-management/1' and management.get('status') == 'available':
        return False
    return True


def unavailable(error):
    code = getattr(error, 'code', 'unreachable')
    message = REASONS.get(code, REASONS['unreachable'])
    return {'provider': PROVIDER, 'name': 'Claude' if PROVIDER == 'claude' else 'ChatGPT', 'owner': 'hermes',
            'accounts': [], 'inventoryStatus': 'unavailable', 'actions': {'add': False},
            'management': {'status': 'unavailable'}, 'agent': agent_address(PROVIDER),
            'error': {'code': code, 'message': message}}


def fold_same_email(accounts):
    """Claude only: agent rows with the same exact email hash are one account. An older agent plugin lists every
    grant as its own row, so a second sign-in to an already-added account (a browser still signed in to it) showed
    up as a duplicate row. ChatGPT never folds by email: one email can own several workspaces with separate quota."""
    if PROVIDER != 'claude':
        return accounts
    groups, order = {}, []
    for a in accounts:
        h = a.get('emailHash')
        if not h or is_mirror(a):
            order.append([a])
        elif h in groups:
            groups[h].append(a)
        else:
            groups[h] = [a]
            order.append(groups[h])
    big = 1 << 30
    rank = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else big
    out = []
    for rows in order:
        if len(rows) == 1:
            out.append(rows[0])
            continue
        lead = sorted(rows, key=lambda a: (a.get('status') not in ('ready', 'connected'), not a.get('usage'), rank(a.get('priority'))))[0]
        merged = dict(lead)
        merged['credentials'] = sorted((c for a in rows for c in a.get('credentials') or []),
                                       key=lambda c: (c.get('managed') is not True, rank(c.get('priority'))))
        merged['credentialCount'] = len(merged['credentials'])
        ranks = [a['priority'] for a in rows if rank(a.get('priority')) < big]
        merged['priority'] = min(ranks) if ranks else None
        merged['preferred'] = any(a.get('preferred') is True for a in rows)
        merged['actions'] = {k: any((a.get('actions') or {}).get(k) is True for a in rows)
                             for a2 in rows for k in (a2.get('actions') or {})}
        out.append(merged)
    return out


def with_legacy(result):
    result['alongside'] = alongside(PROVIDER)
    if isinstance(result.get('accounts'), list):
        result['accounts'] = fold_same_email(result['accounts'])
    if LEGACY is not None:
        try:
            old = LEGACY.read()
            if LEGACY_RENEW is not None:
                old = LEGACY_RENEW(old, reader=LEGACY)
            if os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'):
                old = {**old, 'status': 'connected', 'error': None}
            duplicate = False
            if old.get('status') != 'not_connected':
                # Hermes mirrors this same Claude Code login into its pool; show one row, not two.
                mirrors = [a for a in result['accounts'] if is_mirror(a)]
                result['accounts'] = [a for a in result['accounts'] if not is_mirror(a)]
                # The same account signed in to the agent too (for example with `hermes auth add anthropic`): the
                # agent's row is the one it uses, so it stands for both instead of a second row with the same email.
                exact = reports_hashes(result)
                duplicate = any(same_account(a, old.get('account'), exact) for a in result['accounts'])
            if old.get('status') != 'not_connected' and not duplicate:
                # The original sign-in is the first account; added subscriptions follow it.
                result['accounts'].insert(0, {'id': 'legacy-claude-code', 'name': old.get('account') or 'Claude',
                    'source': 'legacy-claude-code', 'email': old.get('account'), 'plan': old.get('plan'),
                    'status': old['status'], 'usage': old.get('usage'), 'error': old.get('error'),
                    'credentials': [c for m in mirrors for c in m.get('credentials') or []],
                    # Its Hermes mirror carries the agent's try-first order; reordering never touches the login.
                    'priority': min((m['priority'] for m in mirrors if isinstance(m.get('priority'), int)), default=None),
                    'preferred': any(m.get('preferred') is True for m in mirrors),
                    'actions': {'reconnect': False, 'remove': False,
                                'prefer': any((m.get('actions') or {}).get('prefer') is True for m in mirrors)}})
            result['legacyStatus'] = old.get('status', 'unknown')
            if duplicate:
                result['legacyStatus'] = 'same-as-agent'
        except Exception:
            result['legacyStatus'] = 'unavailable'
        result['accountCount'] = len(result['accounts'])
    result['legacySignin'] = legacy_signin(result)
    return result

def connection(result):
    """An inventory row is not evidence of a usable subscription."""
    rows = result['accounts']
    selected = next((row for status in ('connected', 'ready', 'renewing', 'expired', 'cooldown', 'exhausted', 'error', 'not_connected')
                     for row in rows if row.get('status') == status), {})
    status = selected.get('status', 'error' if rows or result.get('inventoryStatus') == 'unavailable' else 'not_connected')
    if status == 'ready':
        status = 'connected'
    error = selected.get('error') or result.get('error')
    if status in ('cooldown', 'exhausted'):
        status = 'error'
        error = {'code': 'limit', 'message': 'Subscription limit reached; wait for its reset.'}
    elif status == 'error' and not isinstance(error, dict):
        error = {'code': 'provider_error', 'message': 'Subscription state is unavailable.'}
    elif status == 'expired' and not isinstance(error, dict):
        error = {'code': 'expired', 'message': 'Subscription sign-in expired; reconnect it in the app.'}
    if isinstance(rows, list):
        rows = friendly_names([dict(a) for a in rows], 'Claude' if PROVIDER == 'claude' else 'ChatGPT')
        result = {**result, 'accounts': rows}
    answer = {**result, 'contract': 'wizard.ai-connection/2', 'status': status,
              'plan': selected.get('plan'), 'usage': selected.get('usage'),
              'account': selected.get('email') or selected.get('account'), 'error': error}
    if result.get('inventoryStatus') == 'unavailable' and not (rows and selected.get('status') in ('connected', 'ready') and not result.get('alongside')):
        # The agent could not be asked. An empty list here would read as "signed out" on Home; say the agent is
        # unreachable instead, so Home keeps its last reading and shows why.
        answer.pop('accounts', None)
        answer['accountCount'] = None
        answer.update(status='error', plan=None, usage=None, account=None,
                      error={'code': 'unreachable', 'message': (result.get('error') or {}).get('message') or REASONS['unreachable']})
    try:
        answer['models'] = owner.inference.models(owner.Hermes) if PROVIDER == 'chatgpt' else owner.inference.models()
    except (owner.inference.Fault, getattr(owner, 'HermesError', owner.inference.Fault)) as error:
        answer['models'] = []
        answer['models_error'] = {'code': error.code, 'message': str(error)}
    return answer


# ---------- automatic order: the Claude account that resets soonest is used first ----------
# Quota that is not used before its weekly reset is lost, so the agent should spend the account whose all-models
# weekly meter resets soonest first, while it still has room. Accounts stopped by a full shared meter (session or
# all-models weekly) go last. Reordering uses only the agent's own `prefer` action (stock `hermes auth priority`),
# runs only when the order really changes, and does nothing on missing or stale usage. Off: WIZARD_CLAUDE_AUTO_ORDER=0.
AUTO_ORDER = PROVIDER == 'claude' and os.environ.get('WIZARD_CLAUDE_AUTO_ORDER', '1').strip().lower() not in ('0', 'off', 'false', 'no')
AUTO_FRESH = 900          # usage older than this (seconds) is stale: change nothing
AUTO_MIN_GAP = 60         # at most one reorder attempt a minute
AUTO_EVERY = 600          # background check interval (seconds), sooner right after a reset
AUTO_STATE = {'lastRun': 0.0, 'changedAt': None, 'lastChange': None}
AUTO_LOCK = threading.Lock()
OK_STATES = ('ready', 'connected', 'ok')


def _epoch(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return when.timestamp()


def _meter_kind(limit):
    """'session' / 'weekly' for the shared meters that stop a whole account; None for model-scoped ones."""
    lid = str(limit.get('id') or '')
    if lid.startswith('session:') or lid == 'five_hour':
        return 'session'
    if lid.startswith('weekly_all:') or lid == 'seven_day':
        return 'weekly'
    return None


def _used(limit):
    used = limit.get('usedPercent')
    if isinstance(used, (int, float)) and not isinstance(used, bool) and math.isfinite(used):
        return used
    left = limit.get('remainingPercent')
    if isinstance(left, (int, float)) and not isinstance(left, bool) and math.isfinite(left):
        return 100 - left
    return None


def order_plan(result, now=None):
    """Pure decision over an /api/accounts result (after with_legacy). Never changes anything.

    Returns {status, order (row ids, wanted order), wanted, needsSignIn, moves (credential ids to `prefer`, in this
    order), reason}. status: 'ok' (nothing to do), 'reorder', 'blocked' (the soonest account can't lead through the
    agent: a seeded Claude Code login) or 'waiting' (missing/stale usage, unavailable inventory)."""
    now = time.time() if now is None else now
    base = {'enabled': AUTO_ORDER, 'rule': 'soonest-reset-first', 'order': [], 'wanted': None, 'needsSignIn': False, 'moves': []}
    management = result.get('management') or {}
    if result.get('inventoryStatus') == 'unavailable' or management.get('contract') != 'wizard.account-management/1' \
            or management.get('status') != 'available':
        return {**base, 'status': 'waiting', 'reason': 'agent-unavailable'}
    rows = [a for a in result.get('accounts') or [] if a.get('credentials')]
    if len(rows) < 2:
        return {**base, 'status': 'ok', 'reason': 'single-account'}
    big = float('inf')
    facts = []
    for a in rows:
        prio = a.get('priority') if isinstance(a.get('priority'), int) and not isinstance(a.get('priority'), bool) else 1 << 30
        if a.get('status') not in OK_STATES:
            facts.append((2, big, prio, a))      # signed out / broken: last, never decides the leader
            continue
        usage = a.get('usage') or {}
        limits = [l for l in usage.get('limits') or [] if isinstance(l, dict)]
        fetched = _epoch(usage.get('fetchedAt'))
        if not limits or fetched is None or now - fetched > AUTO_FRESH:
            return {**base, 'status': 'waiting', 'reason': 'usage-missing-or-stale'}
        shared = [(l, _meter_kind(l), _epoch(l.get('resetsAt')), _used(l)) for l in limits if _meter_kind(l)]
        if not shared or any(used is None for _, _, _, used in shared):
            return {**base, 'status': 'waiting', 'reason': 'usage-missing-or-stale'}
        if any(reset is not None and reset <= now - 120 for _, _, reset, _ in shared):
            return {**base, 'status': 'waiting', 'reason': 'usage-missing-or-stale'}   # a reset passed: wait for a fresh reading
        full = [reset for _, _, reset, used in shared if used >= 100 and (reset is None or reset > now)]
        if full:
            back = max((r for r in full if r is not None), default=big) if None not in full else big
            facts.append((1, back // 60, prio, a))
            continue
        weekly = [reset for _, kind, reset, used in shared if kind == 'weekly' and reset is not None and reset > now]
        binding = [reset for _, _, reset, used in shared if used < 100 and reset is not None and reset > now]
        key = min(weekly) if weekly else (min(binding) if binding else big)
        facts.append((0, key // 60, prio, a))   # whole minutes: reset times jitter by milliseconds between reads
    facts.sort(key=lambda f: (f[0], f[1], f[2]))
    order = [f[3] for f in facts]
    wanted = order[0]
    leadable = [a for a in order if (a.get('actions') or {}).get('prefer') is True]
    current = sorted(leadable, key=lambda a: a['priority'] if isinstance(a.get('priority'), int) else 1 << 30)
    # Fewest `prefer` calls: keep the longest tail of the wanted order that already runs in the agent's order, then
    # move the others to the front from last to first (each `prefer` puts one sign-in at priority 0).
    pos = {a['id']: i for i, a in enumerate(current)}
    t = len(leadable) - 1
    while t > 0 and pos[leadable[t - 1]['id']] < pos[leadable[t]['id']]:
        t -= 1
    moves = [leadable[i]['credentials'][0]['id'] for i in range(t - 1, -1, -1)] if t > 0 else []
    needs = (wanted.get('actions') or {}).get('prefer') is not True and wanted.get('preferred') is not True
    status = 'reorder' if moves else ('blocked' if needs else 'ok')
    return {**base, 'status': status, 'order': [a['id'] for a in order], 'wanted': wanted['id'], 'needsSignIn': needs,
            'moves': moves, 'reason': 'seeded-login-cannot-lead' if needs else None}


def _log(text):
    print('auto-order: ' + text, flush=True)


def _prefer(credential):
    """One stock `hermes auth priority <id> 0` through the agent's broker; waits for it to finish."""
    job = Hermes.request(PROVIDER, '/operations', {'action': 'prefer', 'target': credential, 'label': '', 'confirmed': True})
    deadline = time.time() + 45
    while job.get('status') not in ('succeeded', 'failed', 'cancelled', 'expired', 'needs_review') and time.time() < deadline:
        time.sleep(1)
        job = Hermes.request(PROVIDER, '/operations/' + str(job.get('id')))
    return job.get('status')


def auto_order(result=None, force=False):
    """Apply order_plan once. Single-flight, rate-limited, fail-safe (any error changes nothing more)."""
    if not AUTO_ORDER or not AUTO_LOCK.acquire(blocking=False):
        return None
    try:
        if not force and time.monotonic() - AUTO_STATE['lastRun'] < AUTO_MIN_GAP:
            return None
        AUTO_STATE['lastRun'] = time.monotonic()
        if result is None:
            result = with_legacy(Hermes.accounts(PROVIDER))
        plan = order_plan(result)
        if plan['status'] != 'reorder':
            return plan
        names = {a['id']: (a.get('name') or a['id']) for a in result.get('accounts') or []}
        before = [a['id'] for a in sorted(result.get('accounts') or [], key=lambda a: a['priority'] if isinstance(a.get('priority'), int) else 1 << 30)]
        for credential in plan['moves']:
            status = _prefer(credential)
            if status != 'succeeded':
                _log('stopped: prefer %s -> %s' % (credential, status))
                return plan
        change = {'at': datetime.now().astimezone().isoformat(timespec='seconds'), 'from': before, 'to': plan['order'],
                  'moved': plan['moves'], 'blocked': plan['wanted'] if plan['needsSignIn'] else None}
        AUTO_STATE.update(changedAt=change['at'], lastChange=change)
        _log('order %s -> %s (moved %s)%s' % (' > '.join(names.get(i, i) for i in before), ' > '.join(names.get(i, i) for i in plan['order']),
             ', '.join(plan['moves']), ('; %s resets soonest but needs one agent sign-in to lead' % names.get(plan['wanted'])) if plan['needsSignIn'] else ''))
        return plan
    except BridgeError as error:
        _log('skipped: agent busy or unavailable (%s %s)' % (getattr(error, 'status', ''), getattr(error, 'code', 'error')))
    except Exception as error:
        _log('skipped: %s' % type(error).__name__)
    finally:
        AUTO_LOCK.release()
    return None


def auto_order_view(result):
    """Secret-free summary for the page: whether the order is automatic and who should lead."""
    plan = order_plan(result)
    return {'enabled': AUTO_ORDER, 'rule': 'soonest-reset-first', 'status': plan['status'], 'wanted': plan['wanted'],
            'needsSignIn': plan['needsSignIn'] and plan['status'] in ('blocked', 'reorder'), 'order': plan['order'],
            'changedAt': AUTO_STATE['changedAt']}


def _next_wait(result, now=None):
    now = time.time() if now is None else now
    resets = [_epoch(l.get('resetsAt')) for a in result.get('accounts') or [] for l in ((a.get('usage') or {}).get('limits') or [])
              if isinstance(l, dict) and _meter_kind(l)]
    soon = [r - now + 90 for r in resets if r is not None and r > now]
    return max(60, min([AUTO_EVERY] + soon))


def auto_order_loop():
    """Background check: every AUTO_EVERY seconds and ~90 s after the next shared reset."""
    time.sleep(30)
    while True:
        wait = AUTO_EVERY
        try:
            result = with_legacy(Hermes.accounts(PROVIDER))
            auto_order(result, force=True)
            wait = _next_wait(result)
        except Exception as error:
            _log('check failed: %s' % type(error).__name__)
        time.sleep(wait)


class Handler(owner.Handler):
    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, *args):
        pass

    def send(self, status, data, ctype='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        origins = ["'self'"]
        for origin in os.environ.get('WIZARD_TRUSTED_ORIGINS', '').split(','):
            origin = origin.strip().rstrip('/')
            parsed = urlsplit(origin)
            if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.path and not parsed.query and not parsed.fragment and not parsed.username:
                origins.append(origin)
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors " + ' '.join(origins) + "; base-uri 'none'; form-action 'none'")
        if origins == ["'self'"]:
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def authorized(self, path=None):
        if urlsplit(self.path).path == '/api/connection' and self.headers.get('X-Wizard-Grant'):
            return super().authorized('/api/connection')
        if not PASSWORD:
            return True
        try:
            scheme, value = self.headers.get('Authorization', '').split(' ', 1)
            given = base64.b64decode(value).decode().partition(':')[2]
            if scheme == 'Basic' and hmac.compare_digest(given.encode(), PASSWORD.encode()):
                return True
        except (ValueError, UnicodeError):
            pass
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Subscriptions"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def legacy(self, method):
        """The original Claude Code sign-in page (Connect, code, Test, Sign out) under claude-code/: the login
        the host agent's Claude Code provider uses. Kept so that login can always be renewed from this app."""
        if PROVIDER != 'claude':
            return self.send(404, {'error': 'not found'})
        path = urlsplit(self.path).path
        if path == LEGACY_PREFIX:
            self.send_response(308)
            self.send_header('Location', 'claude-code/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        rest = self.path[len(LEGACY_PREFIX):] or '/'
        self.path = rest
        return method(self)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == LEGACY_PREFIX or path.startswith(LEGACY_PREFIX + '/'):
            return self.legacy(owner.Handler.do_GET)
        if path == '/health':
            return self.send(200, {'status': 'ok', 'version': owner.VERSION})
        if not self.authorized():
            return
        if path == '/.well-known/mcp/server-cards.json':
            card = owner.card(self.headers.get('Host', ''))
            card['x-wizard']['credential_owner'] = 'hermes (legacy Claude Code volume read-only inventory)'
            return self.send(200, card)
        if path == '/SKILL.md':
            return self.send(200, (ROOT.parent / 'SKILL.md').read_bytes(), 'text/markdown; charset=utf-8')
        if re.fullmatch(r'/api/operations/[A-Za-z0-9_-]{20,64}', path):
            if not PASSWORD and not same_origin(self.headers):
                return self.send(403, {'error': 'Cross-site request rejected'})
            try:
                result = Hermes.request(PROVIDER, '/operations/' + path.rsplit('/', 1)[1])
                if PROVIDER == 'chatgpt' and isinstance(result, dict) and result.get('status') == 'succeeded' \
                        and result.get('action') in ('add', 'reconnect'):
                    # Fresh mode: a ChatGPT sign-in becomes the agent's model while it has none (as Claude's does);
                    # a model the owner chose is never changed, and alongside boxes are skipped.
                    result = {**result, 'agentDefault': adopt_as_agent_default(PROVIDER, CHATGPT_PROVIDER)}
                return self.send(200, result)
            except BridgeError as error:
                return self.send(error.status, {'error': 'Operation status unavailable; check inventory'})
            except Exception:
                return self.send(503, {'error': 'Operation status unavailable; do not restart the operation'})
        if path == '/api/model-cooldowns':
            if PROVIDER != 'claude':
                return self.send(404, {'error': 'not found'})
            if any(k.lower() in ('tailscale-user-login', 'x-forwarded-for', 'forwarded', 'x-real-ip') or k.lower().startswith('cf-') for k in self.headers):
                return self.send(403, {'error': 'box-only'})
            try:
                evidence = Hermes.request(PROVIDER, '/model-cooldowns')
                if not isinstance(evidence, dict) or evidence.get('contract') != 'wizard.model-cooldowns/1':
                    return self.send(503, {'error': 'Cooldown inventory unavailable'})
                return self.send(200, {'provider': 'claude', 'owner': 'hermes', 'modelCooldowns': evidence})
            except Exception:
                return self.send(503, {'error': 'Cooldown inventory unavailable'})
        if path in ('/api/accounts', '/api/connection'):
            if path == '/api/connection' and any(k.lower() in ('tailscale-user-login', 'x-forwarded-for', 'forwarded', 'x-real-ip') or k.lower().startswith('cf-') for k in self.headers):
                return self.send(403, {'error': 'box-only'})
            try:
                result = with_legacy(Hermes.accounts(PROVIDER))
            except BridgeError as error:
                # Existing subscriptions are unchanged; the page says why and offers Retry, never a sign-in that
                # would not reach the agent.
                result = with_legacy(unavailable(error))
            except Exception:
                result = with_legacy(unavailable(BridgeError()))
            if AUTO_ORDER and path == '/api/accounts':
                try:
                    result['autoOrder'] = auto_order_view(result)
                    if result['autoOrder']['status'] == 'reorder':
                        # A fresh usage reading changed who should lead: reorder in the background (rate-limited).
                        threading.Thread(target=auto_order, args=(json.loads(json.dumps(result)),), daemon=True).start()
                except Exception:
                    result.pop('autoOrder', None)
            if path == '/api/connection':
                result = connection(result)
            return self.send(200, result)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8'), '/boot.js': ('boot.js', 'text/javascript; charset=utf-8'), '/theme-client.js': ('theme-client.js', 'text/javascript; charset=utf-8'), '/wizard-ui.css': ('wizard-ui.css', 'text/css; charset=utf-8'),
                  '/wizard-tokens.css': ('wizard-tokens.css', 'text/css; charset=utf-8'), '/wizard-layout.css': ('wizard-layout.css', 'text/css; charset=utf-8'), '/wizard-sheet.js': ('wizard-sheet.js', 'text/javascript; charset=utf-8'),
                  '/logo-claude.svg': ('logo-claude.svg', 'image/svg+xml'), '/logo-chatgpt.svg': ('logo-chatgpt.svg', 'image/svg+xml')}
        if path in assets:
            name, ctype = assets[path]
            return self.send(200, (ROOT / name).read_bytes(), ctype)
        return self.send(404, {'error': 'not found'})

    def do_POST(self):
        if urlsplit(self.path).path == '/api/infer':
            # Preserve main's router grants, isolated providers and SSE contract.
            return owner.Handler.do_POST(self)
        path = urlsplit(self.path).path
        if path.startswith(LEGACY_PREFIX + '/'):
            return self.legacy(owner.Handler.do_POST)
        if not self.authorized():
            return
        if not PASSWORD and not same_origin(self.headers):
            # No page password (Tailscale-only box, like the original Connect): same-origin browser requests only.
            return self.send(403, {'error': 'Cross-site action rejected'})
        if urlsplit(self.path).path != '/api/operations':
            return self.send(404, {'error': 'not found'})
        if self.headers.get('X-Wizard-Account-Action') != '1' or self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': 'Cross-site action rejected'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                return self.send(413, {'error': 'Request too large'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or set(body) - {'action', 'target', 'label', 'confirmed', 'operation', 'code'}:
                return self.send(400, {'error': 'Invalid request'})
            inventory = Hermes.accounts(PROVIDER)
            management = inventory.get('management') or {}
            if management.get('contract') != 'wizard.account-management/1' or management.get('status') != 'available':
                return self.send(403, {'error': 'Account changes unavailable; subscriptions are unchanged'})
            action = body.get('action')
            if action == 'add':
                permitted = (inventory.get('actions') or {}).get('add') is True
            elif action in ('reconnect', 'remove'):
                permitted = any((row.get('actions') or {}).get(action) is True and
                    any(c.get('id') == body.get('target') and c.get('managed') is True for c in row.get('credentials', []))
                    for row in inventory.get('accounts', []))
            elif action == 'prefer':
                # Reordering is not destructive: any sign-in the agent lists may be tried first, mirrors included.
                permitted = any((row.get('actions') or {}).get('prefer') is True and
                    any(c.get('id') == body.get('target') for c in row.get('credentials', []))
                    for row in inventory.get('accounts', []))
            else:
                permitted = action in ('submit', 'cancel')
            if not permitted:
                return self.send(403, {'error': 'Account action unsupported'})
            return self.send(200, Hermes.request(PROVIDER, '/operations', body))
        except BridgeError as error:
            if error.status == 409:
                return self.send(409, {'error': 'Another sign-in is running, or the request was refused; refresh first'})
            return self.send(503, {'error': REASONS.get(error.code, REASONS['unreachable']), 'code': error.code})
        except Exception:
            return self.send(503, {'error': 'Operation unavailable; refresh inventory before retrying'})

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def server_bind(self):
        # HTTPServer's reverse-DNS lookup can stall an isolated container startup.
        from socketserver import TCPServer
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


if __name__ == '__main__':
    import signal
    import threading
    http = Server((os.environ.get('WIZARD_POOL_BIND', owner.BIND), int(os.environ.get('WIZARD_POOL_PORT', owner.PORT))), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=http.shutdown, daemon=True).start())
    if AUTO_ORDER:
        threading.Thread(target=auto_order_loop, daemon=True).start()
    try:
        http.serve_forever()
    finally:
        http.server_close()
        if PROVIDER == 'claude':
            owner.inference.FAST_SPARE.close()
