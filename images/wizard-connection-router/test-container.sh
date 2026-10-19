#!/bin/sh
# GitHub-hosted release runner only; no owner state or credentials.
set -eu
cd "$(dirname "$0")"
IMAGE=${WIZARD_ROUTER_IMAGE:-wizard-connection-router-test}
if [ "${SKIP_BUILD:-0}" != 1 ]; then docker build -t "$IMAGE" .; fi
name="wizard-router-smoke-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
# No host ports or mounts; all fixture data lives in this disposable container.
docker run -d --name "$name" --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /data:uid=1000,gid=1000,mode=0700 --env WIZARD_APPS_JSON=/data/apps.json \
  --env WIZARD_GRANTS_FILE=/data/grants.json "$IMAGE"
docker exec -i "$name" python3 - <<'PY'
import json, time, urllib.request, urllib.error
from pathlib import Path
Path('/data/apps.json').write_text('{"apps": []}')
Path('/data/grants.json').write_text('{"enforce": true, "incoming": [], "outgoing": {}}')
base = 'http://127.0.0.1:8802'
for attempt in range(30):
    try:
        with urllib.request.urlopen(base + '/health', timeout=2) as r:
            assert json.load(r) == {'ok': True, 'version': '0.1.1'}
        break
    except OSError:
        if attempt == 29:
            raise
        time.sleep(.2)
with urllib.request.urlopen(base + '/') as r:
    assert b'Connection Router' in r.read()
for asset in ('appearance.js', 'appearance.css'):
    with urllib.request.urlopen(base + '/' + asset) as r:
        assert r.status == 200 and r.read()
with urllib.request.urlopen(base + '/v1/owner/routes') as r:
    routes = json.load(r)
    assert routes['routes'] == []
request = urllib.request.Request(base + '/v1/owner/routes', headers={'Origin': 'https://untrusted.example'})
try:
    urllib.request.urlopen(request)
    raise AssertionError('owner route accepted browser origin')
except urllib.error.HTTPError as e:
    assert e.code == 403
print('Router container health, page, empty routes, owner boundary: PASS')
PY
