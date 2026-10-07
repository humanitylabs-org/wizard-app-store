#!/bin/sh
# Build the image, then prove it starts read-only, unprivileged, with only the expected files.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TAG=${SECRET_DROP_IMAGE:-wizard-secret-drop:test}
[ -n "${SKIP_BUILD:-}" ] || docker build -t "$TAG" "$ROOT"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 128m --pids-limit 32 --tmpfs /data:rw,nosuid,size=8m,uid=1000,gid=1000 \
  --entrypoint python3 "$TAG" -c '
import os, json, pathlib, subprocess, sys, time, urllib.request
assert os.getuid() == 1000 and os.getgid() == 1000, "must run as 1000:1000"
files = sorted(str(p.relative_to("/app")) for p in pathlib.Path("/app").rglob("*") if p.is_file())
assert files == ["LICENSE", "SKILL.md", "client.py", "server.py", "static/app.css", "static/app.js", "static/hpke.js", "static/index.html", "static/noble-crypto.js"], files
for f in files: assert not os.access("/app/" + f, os.W_OK), f
p = subprocess.Popen([sys.executable, "/app/server.py"])
t0, h = time.monotonic(), None
while h is None and time.monotonic() - t0 < 10:
    try:
        h = json.load(urllib.request.urlopen("http://127.0.0.1:8792/health", timeout=1))
    except OSError: time.sleep(0.1)
assert h and h["status"] == "ok", h
startup = round(time.monotonic() - t0, 2)
assert startup < 3, startup
assert urllib.request.urlopen("http://127.0.0.1:8792/client.py").read() == open("/app/client.py", "rb").read()
p.terminate(); rc = p.wait(10)
assert rc == 0, rc
print(json.dumps({"uid": os.getuid(), "files": len(files), "health": h, "startup_s": startup, "sigterm_exit": rc}))'
docker image inspect "$TAG" --format 'image size bytes: {{.Size}}'
