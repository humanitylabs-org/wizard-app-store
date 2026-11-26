"""Owner feature switches for the Claude app (wizard.app-switches/1, wizard-os docs/APP_SWITCHES.md).

Claude only: pool_server installs it on its handler when WIZARD_POOL_PROVIDER is claude. The block below is the shared
stdlib block from wizard-app-manager templates/hello-wizard (unchanged apart from SWITCHES). State lives on the box in
the app's only volume (the shared Claude login folder), in its own subfolder, so it survives updates and restarts.
"""
import os
from pathlib import Path

DATA = Path(os.environ.get('WIZARD_CLAUDE_CLAUDE_DIR', '/claude')) / '.wizard-claude-app'


# ---- wizard.app-switches/1 ------------------------------------------------------------------------------------------
# Owner feature switches for the Tracker's Try it (wizard-os docs/APP_SWITCHES.md). Shared block: the same text ships in
# every Wizard app; `wam new` starts every app with it (wizard-os AGENTS.md: a new app repo ships it in its first PR). Every new feature ships behind a switch, off by
# default: append it to SWITCHES with the issue it delivers, e.g.
#   {'id': 'compact-header', 'name': 'Compact top bar', 'description': '...', 'default': False,
#    'issues': ['humanitylabs-org/<repo>#20']}
# and gate the feature on switch_on('compact-header'). State lives on the box (DATA_DIR/switches.json), so the app's
# page, the Tracker (through the App Manager) and the agent see one state. Each switch also lists `tried` (true once it
# was turned on, never reset) and `vote` ('up', 'down' or None) for the Try new features section (POST {id, vote}). GET/POST /api/switches, owner only, with
# X-Wizard-Switch: 1 and never a bearer or agent grant. An app with a platform owner-proof key (owner_proof in wizard.md,
# wizard-os spec/OWNER_PROOF.md) accepts only a valid signed proof: any process on the box can set the other headers.
# An app without one accepts the box's Tailscale Serve owner login, never a box-local host.
import hashlib as _sw_hashlib
import hmac as _sw_hmac
import json as _sw_json
import os as _sw_os
import re as _sw_re
import threading as _sw_threading
import time as _sw_time
from pathlib import Path as _SwPath
from urllib.parse import urlsplit as _sw_urlsplit

SWITCHES = [
    {'id': 'one-year-signin', 'name': 'One-year Claude sign-in',
     'description': 'Connect signs Claude in for one year (Claude Code setup-token) instead of about four weeks. '
                    'Usage meters are not available for that sign-in.',
     'default': False, 'issues': ['humanitylabs-org/claude-connection#27']},
]
_SW_CONTRACT = 'wizard.app-switches/1'
_SW_ROUTE = _sw_re.compile(r'(?:/[a-z0-9][a-z0-9-]{0,62})?/api/switches/?')
_SW_LOCAL = {'localhost', '127.0.0.1', '::1', '[::1]', '0.0.0.0'}
_sw_lock = _sw_threading.Lock()
_sw_nonces = {}
_SW_PROOF = _sw_re.compile(r'(\d{1,12})\.([0-9a-f]{48})\.([0-9a-f]{64})')


def _sw_file():
    return _SwPath(_sw_os.environ.get('WIZARD_SWITCHES_DIR') or DATA) / 'switches.json'


def _sw_saved():
    try:
        saved = _sw_json.loads(_sw_file().read_text())
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _sw_map(saved, key):
    m = saved.get(key)
    return m if isinstance(m, dict) else {}


def switches_doc():
    saved = _sw_saved()
    tried, votes = _sw_map(saved, '_tried'), _sw_map(saved, '_votes')

    def row(s):
        on = saved[s['id']] if isinstance(saved.get(s['id']), bool) else bool(s.get('default'))
        vote = votes.get(s['id'])
        return dict(s, on=on, tried=tried.get(s['id']) is True or (on and not s.get('default')),
                    vote=vote if vote in ('up', 'down') else None)
    return {'contract': _SW_CONTRACT, 'switches': [row(s) for s in SWITCHES]}


def switch_on(switch_id):
    return next((s['on'] for s in switches_doc()['switches'] if s['id'] == switch_id), False)


def _sw_set(switch_id, on=None, vote=False):
    """Save a flip (`on`) or a vote (`vote`: 'up', 'down' or None; False leaves it alone)."""
    with _sw_lock:
        ids = {s['id'] for s in SWITCHES}
        old = _sw_saved()
        saved = {k: v for k, v in old.items() if k in ids and isinstance(v, bool)}
        tried = {k: True for k, v in _sw_map(old, '_tried').items() if k in ids and v is True}
        votes = {k: v for k, v in _sw_map(old, '_votes').items() if k in ids and v in ('up', 'down')}
        if isinstance(on, bool):
            saved[switch_id] = on
            if on:
                tried[switch_id] = True
        if vote is None:
            votes.pop(switch_id, None)
        elif vote in ('up', 'down'):
            votes[switch_id] = vote
        if tried:
            saved['_tried'] = tried
        if votes:
            saved['_votes'] = votes
        f = _sw_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text(_sw_json.dumps(saved))
        _sw_os.replace(tmp, f)
    return switches_doc()


def _sw_proof(h):
    """None when this app has no platform owner-proof key, else whether the request carries a valid, unused proof."""
    key_file = _sw_os.environ.get('WIZARD_OWNER_PROOF_KEY_FILE')
    if not key_file:
        return None
    try:
        with open(key_file, 'rb') as f:
            key = f.read(33)
    except OSError:
        return False                    # a key is named but unreadable: refuse, never fall back to headers
    app = _sw_os.environ.get('WIZARD_OWNER_PROOF_APP') or ''
    values = h.headers.get_all('X-Wizard-App-Owner-Proof') or []
    m = _SW_PROOF.fullmatch(values[0].strip()) if len(values) == 1 else None
    if len(key) != 32 or not app or not m or abs(_sw_time.time() - int(m.group(1))) > 30:
        return False
    msg = '\n'.join(('wizard-app-owner-v1', app, m.group(1), m.group(2), h.command, h.path)).encode()
    if not _sw_hmac.compare_digest(_sw_hmac.new(key, msg, _sw_hashlib.sha256).hexdigest(), m.group(3)):
        return False
    now = _sw_time.monotonic()
    with _sw_lock:
        for n in [n for n, until in _sw_nonces.items() if until < now]:
            del _sw_nonces[n]
        if m.group(2) in _sw_nonces:
            return False
        _sw_nonces[m.group(2)] = now + 60
    return True


def _sw_owner(h, write):
    hd = h.headers
    # A read from the app's own page (the shared Try new features section) may leave out X-Wizard-Switch: the browser's
    # Sec-Fetch-Site proves it is same-origin. Every write needs the header.
    page_read = not write and (hd.get('Sec-Fetch-Site') or '').lower() == 'same-origin'
    if hd.get('Authorization') or (hd.get('X-Wizard-Switch') != '1' and not page_read):
        return False
    proof = _sw_proof(h)
    if proof is not None:
        return proof
    if (hd.get('Sec-Fetch-Site') or 'same-origin').lower() not in ('same-origin', 'none'):
        return False
    host = (hd.get('Host') or '').strip().lower()
    name = host.split(']')[0] + ']' if host.startswith('[') else host.rsplit(':', 1)[0]
    if not name or name in _SW_LOCAL or '.' not in name:      # box-local and container hosts never prove the owner
        return False
    origin = hd.get('Origin')
    trusted = {o.strip() for o in (_sw_os.environ.get('WIZARD_TRUSTED_ORIGINS') or '').split(',') if o.strip()}
    if origin and _sw_urlsplit(origin).netloc.lower() != host and origin not in trusted:
        return False
    if write and not origin:
        return False
    logins = [x.strip() for x in (hd.get_all('Tailscale-User-Login') or [])]
    owners = {x.strip().lower() for x in (_sw_os.environ.get('WIZARD_OWNER_LOGINS') or '').split(',') if x.strip()}
    return len(logins) == 1 and '@' in logins[0] and (not owners or logins[0].lower() in owners)


def _sw_send(h, code, doc):
    body = _sw_json.dumps(doc).encode()
    h.send_response(code)
    h.send_header('Content-Type', 'application/json')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Content-Length', str(len(body)))
    h.end_headers()
    if h.command != 'HEAD':
        h.wfile.write(body)


def _sw_handle(h):
    """Serve /api/switches (or /<app>/api/switches) and return True; False for every other request."""
    if not _SW_ROUTE.fullmatch(_sw_urlsplit(h.path).path):
        return False
    if h.command in ('GET', 'HEAD'):
        if not _sw_owner(h, False):
            _sw_send(h, 403, {'error': "Only this Wizard's owner can see these switches.", 'code': 'owner_only'})
        else:
            _sw_send(h, 200, switches_doc())
        return True
    if not _sw_owner(h, True):
        _sw_send(h, 403, {'error': "Only this Wizard's owner can change these switches.", 'code': 'owner_only'})
        return True
    try:
        if (h.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json':
            raise ValueError
        size = int(h.headers.get('Content-Length') or '0')
        if size <= 0 or size > 4096:
            raise ValueError
        body = _sw_json.loads(h.rfile.read(size))
        if not isinstance(body, dict) or not isinstance(body.get('id'), str) or set(body) not in ({'id', 'on'}, {'id', 'vote'}) \
                or ('on' in body and not isinstance(body['on'], bool)) or ('vote' in body and body['vote'] not in ('up', 'down', None)):
            raise ValueError
    except (ValueError, TypeError):
        _sw_send(h, 400, {'error': 'Send JSON {"id": "...", "on": true|false} or {"id": "...", "vote": "up"|"down"|null}',
                          'code': 'invalid_input'})
        return True
    if body['id'] not in {s['id'] for s in SWITCHES}:
        _sw_send(h, 404, {'error': 'No such switch', 'code': 'unknown_switch'})
        return True
    try:
        _sw_send(h, 200, _sw_set(body['id'], on=body.get('on'), vote=body['vote'] if 'vote' in body else False))
    except OSError:
        _sw_send(h, 500, {'error': 'storage_failure'})
    return True


def wizard_switches_install(handler_cls):
    """Route the switch endpoint ahead of the app's own GET/HEAD/POST handlers."""
    for method in ('do_GET', 'do_HEAD', 'do_POST'):
        orig = getattr(handler_cls, method, None)
        if getattr(orig, '_wizard_switches', False):
            continue

        def wrapped(self, _orig=orig):
            if _sw_handle(self):
                return None
            if _orig is None:
                return self.send_error(501)
            return _orig(self)
        wrapped._wizard_switches = True
        setattr(handler_cls, method, wrapped)
    return handler_cls
# ---- end wizard.app-switches/1 ---------------------------------------------------------------------------------------
