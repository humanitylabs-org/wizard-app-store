#!/usr/bin/env python3
"""Exercise the pinned recipe with disposable state; never call a model."""
import http.cookies
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = 'wizard-hermes-smoke-' + secrets.token_hex(4)
VOLUME = NAME + '-data'
env = dict(os.environ)
env.update(APP_DATA_DIR='/unused-smoke-path',
           HERMES_DASHBOARD_BASIC_AUTH_USERNAME='smoke-user',
           HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=secrets.token_urlsafe(32),
           HERMES_DASHBOARD_BASIC_AUTH_SECRET=secrets.token_hex(32))


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=kwargs.pop('timeout', 90), **kwargs).strip()


recipe = json.loads(run('docker', 'compose', '-f', str(ROOT / 'apps/hermes-agent/docker-compose.yml'), 'config', '--format', 'json', env=env))
service = recipe['services']['hermes-agent']
assert service['volumes'][0]['target'] == '/opt/data'
sidecar = recipe['services']['wizard-apps']
assert sidecar['image'] == service['image'] and sidecar['user'] == '1000:1000' and sidecar['read_only'] is True
SIDECAR = NAME + '-wizard-apps'
base = ''


def request(path, payload=None, cookie=None):
    headers = {'Accept': 'application/json', 'Origin': base}
    if cookie:
        headers['Cookie'] = cookie
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        res = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        res = e
    return res.status, res.headers, res.read()


def ready():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            status, _, body = request('/api/status')
            if status == 200 and json.loads(body).get('auth_required') is True:
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError('Authenticated dashboard did not become ready within 180 seconds')


run('docker', 'pull', service['image'], timeout=600)
try:
    run('docker', 'volume', 'create', VOLUME)
    args = ['docker', 'run', '-d', '--name', NAME, '--memory', '2g', '--cpus', '1',
            '-p', '127.0.0.1::9119', '-v', VOLUME + ':/opt/data']
    child_env = dict(env)
    for key, value in service['environment'].items():
        child_env[key] = str(value)
        args += ['-e', key]
    args += [service['image'], *service['command']]
    run(*args, env=child_env)
    port = run('docker', 'port', NAME, '9119/tcp').rsplit(':', 1)[1]
    base = 'http://127.0.0.1:' + port
    ready()
    assert request('/api/auth/me')[0] == 401, 'Unauthenticated API must reject access'
    login = {'provider': 'basic', 'username': env['HERMES_DASHBOARD_BASIC_AUTH_USERNAME'], 'password': 'invalid-password'}
    assert request('/auth/password-login', login)[0] == 401, 'Wrong password must fail'
    login['password'] = env['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD']
    status, headers, body = request('/auth/password-login', login)
    assert status == 200, f'Native login failed: HTTP {status}'
    jar = http.cookies.SimpleCookie()
    for value in headers.get_all('Set-Cookie', []):
        jar.load(value)
    cookie = '; '.join(f'{k}={v.value}' for k, v in jar.items())
    assert cookie, 'Login must issue cookies'
    assert request('/api/auth/me', cookie=cookie)[0] == 200, 'Authenticated API must work'
    assert request('/api/sessions', cookie=cookie)[0] == 200, 'Native sessions API must work'
    run('docker', 'exec', '-u', '1000:1000', NAME, 'sh', '-c', 'printf smoke-persistence > /opt/data/wizard-smoke-marker')
    run('docker', 'restart', '-t', '30', NAME)
    port = run('docker', 'port', NAME, '9119/tcp').rsplit(':', 1)[1]
    base = 'http://127.0.0.1:' + port
    ready()
    assert run('docker', 'exec', NAME, 'cat', '/opt/data/wizard-smoke-marker') == 'smoke-persistence'
    assert request('/api/auth/me', cookie=cookie)[0] == 200, 'Signed login must survive restart'
    # Wizard apps sync sidecar, run exactly as the recipe defines it, on the same data, no Wizard apps around.
    side = ['docker', 'run', '-d', '--name', SIDECAR, '--user', sidecar['user'], '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
            '-v', VOLUME + ':/opt/data', '--entrypoint', sidecar['entrypoint'][0]]
    for key, value in {**sidecar['environment'], 'WIZARD_APPS_INTERVAL_S': '5'}.items():
        side += ['-e', f'{key}={value}']
    run(*side, service['image'], *sidecar['entrypoint'][1:], *sidecar['command'])
    deadline = time.monotonic() + 120
    while 'no Wizard apps found' not in run('docker', 'logs', SIDECAR, stderr=subprocess.STDOUT):
        assert time.monotonic() < deadline, 'wizard-apps sync did not report its first cycle'
        time.sleep(2)
    time.sleep(6)
    side_logs = run('docker', 'logs', SIDECAR, stderr=subprocess.STDOUT)
    assert 'cycle failed' not in side_logs and len(side_logs.splitlines()) < 10, side_logs
    assert 'managed-by: wizard-apps-sync' in run('docker', 'exec', SIDECAR, 'cat', '/opt/data/skills/wizard-apps/SKILL.md')
    assert json.loads(run('docker', 'exec', SIDECAR, 'cat', '/opt/data/wizard-apps/apps.json'))['apps'] == []
    assert run('docker', 'exec', SIDECAR, '/opt/hermes/.venv/bin/python3', '-c',
               "import yaml; print((yaml.safe_load(open('/opt/data/config.yaml')) or {}).get('mcp_servers') or {})") == '{}'
    assert json.loads(run('docker', 'inspect', SIDECAR))[0]['RestartCount'] == 0
    assert request('/api/auth/me', cookie=cookie)[0] == 200, 'Hermes must keep running beside the sidecar'
    info = json.loads(run('docker', 'inspect', NAME))[0]
    assert not info['HostConfig']['Privileged']
    assert len(info['Mounts']) == 1 and info['Mounts'][0]['Destination'] == '/opt/data'
    print('PASS: wizard-apps sync sidecar (first cycle, own skill, empty apps.json, no config edits), fresh startup, auth required, wrong-password rejection, native login, sessions API, writable UID-1000 data, restart persistence, stable session signing, isolated volume.')
    print('No model calls or real provider credentials used. Runtipi host installation is a separate check.')
except Exception:
    # Do not dump container environment or generated credentials into logs.
    print('Smoke failed. Container state:', run('docker', 'inspect', '--format', '{{.State.Status}}', NAME))
    raise
finally:
    subprocess.run(['docker', 'rm', '-f', SIDECAR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
    subprocess.run(['docker', 'rm', '-f', NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
    subprocess.run(['docker', 'volume', 'rm', VOLUME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
