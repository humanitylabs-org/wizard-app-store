"""Real separate-container smoke; no provider credentials or paid model calls."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.request
from playwright.sync_api import sync_playwright

D = shutil.which('docker')
assert D, 'Docker is required'
NAME = 'wizard-frontend-test-' + secrets.token_hex(4)
BACKEND = NAME + '-backend'
VOLUME = NAME + '-data'
IMAGE = os.environ.get('FRONTEND_IMAGE', 'wizard-hermes-frontend-3:test')
HERMES = 'nousresearch/hermes-agent@sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7'
OUT = Path(os.environ.get('SMOKE_OUTPUT', os.environ.get('TMPDIR', '.'))) / NAME
OUT.mkdir(parents=True)
AUTH = dict(HERMES_UID='1000', HERMES_GID='1000', HERMES_DASHBOARD='1', HERMES_DASHBOARD_HOST='0.0.0.0', HERMES_DASHBOARD_PORT='9119', HERMES_DASHBOARD_BASIC_AUTH_USERNAME='smoke-user', HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=secrets.token_urlsafe(32), HERMES_DASHBOARD_BASIC_AUTH_SECRET=secrets.token_hex(32))

def docker(*args, env=None):
    return subprocess.check_output([D, *args], env=env, text=True, timeout=180).strip()

report = {}
try:
    docker('network', 'create', NAME)
    docker('volume', 'create', VOLUME)
    args = ['run', '-d', '--name', BACKEND, '--network', NAME, '--network-alias', 'hermes-backend', '--memory', '2g', '--cpus', '1', '-v', VOLUME + ':/opt/data']
    for key in AUTH:
        args += ['-e', key]
    docker(*args, HERMES, 'gateway', 'run', env={**os.environ, **AUTH})
    docker('run', '-d', '--name', NAME, '--network', NAME, '--memory', '256m', '--cpus', '1', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '-p', '127.0.0.1::8080', '-e', 'HERMES_BACKEND_URL=http://hermes-backend:9119', IMAGE)
    base = 'http://127.0.0.1:' + docker('port', NAME, '8080/tcp').rsplit(':', 1)[1]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + '/api/status', timeout=3) as r:
                if json.load(r).get('auth_required'):
                    break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('Proxied Hermes backend not ready')
    with sync_playwright() as p:
        chrome = os.environ.get('CHROME_PATH', shutil.which('google-chrome'))
        browser = p.chromium.launch(**({'executable_path': chrome} if chrome else {}), headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
        report['unauthenticated_api'] = ctx.request.get(base + '/api/auth/me').status
        assert report['unauthenticated_api'] == 401
        report['native_login_page'] = ctx.request.get(base + '/login').status
        assert report['native_login_page'] == 200
        unauth_page = ctx.new_page()
        unauth_page.goto(base, wait_until='networkidle', timeout=45000)
        unauth_page.wait_for_url('**/login**', timeout=15000)
        report['browser_redirects_to_native_login'] = True
        unauth_page.close()
        login = ctx.request.post(base + '/auth/password-login', data={'provider': 'basic', 'username': AUTH['HERMES_DASHBOARD_BASIC_AUTH_USERNAME'], 'password': AUTH['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD']}, headers={'Origin': base})
        report['login_status'] = login.status
        assert login.status == 200
        report['authenticated_sessions'] = ctx.request.get(base + '/api/sessions').status
        assert report['authenticated_sessions'] == 200
        page = ctx.new_page()
        errors, failures, sockets, received = [], [], [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('response', lambda r: failures.append({'status': r.status, 'url': r.url.split('?')[0]}) if r.status >= 400 else None)
        def on_socket(w):
            sockets.append(w.url.split('?')[0])
            w.on('framereceived', lambda _: received.append(True))
        page.on('websocket', on_socket)
        page.goto(base, wait_until='networkidle', timeout=45000)
        page.wait_for_timeout(35000)
        later = page.get_by_text("I'll choose a provider later", exact=True)
        if later.count():
            later.click()
            page.wait_for_timeout(1500)
        text = page.locator('body').inner_text()
        report['desktop_navigation'] = all(label in text.lower() for label in ['sessions', 'capabilities', 'messaging'])
        assert report['desktop_navigation'], text[:1500]
        page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(1000)
        report['mobile_overflow'] = page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        report.update(page_errors=errors, http_failures=failures, websocket_connected=bool(sockets), websocket_received=bool(received))
        assert not errors and not failures, report
        assert sockets and received, report
        browser.close()
    inspect = json.loads(docker('inspect', NAME))[0]
    report['frontend_nonroot'] = inspect['Config']['User'] == '101:101'
    report['frontend_no_mounts'] = not inspect['Mounts']
    assert report['frontend_nonroot'] and report['frontend_no_mounts']
    report['paid_model_turn_tested'] = False
    report['passed'] = True
finally:
    for target in [NAME, BACKEND]:
        subprocess.run([D, 'rm', '-f', target], capture_output=True, timeout=45)
    subprocess.run([D, 'volume', 'rm', VOLUME], capture_output=True, timeout=45)
    subprocess.run([D, 'network', 'rm', NAME], capture_output=True, timeout=45)
    report['cleanup_complete'] = all(subprocess.run([D, *args], capture_output=True).returncode != 0 for args in [('inspect', NAME), ('inspect', BACKEND), ('volume', 'inspect', VOLUME), ('network', 'inspect', NAME)])
    (OUT / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print('Evidence:', OUT)
