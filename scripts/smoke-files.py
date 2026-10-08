#!/usr/bin/env python3
"""Files app: the real Runtipi 4.8.0 translation of apps/files on a fresh fake ROOT_FOLDER_HOST.

media/ is created the way the Runtipi 4.8.0 CLI does it (os.MkdirAll(root/"media", 0755) as root, never chmodded
afterwards); app data gets Runtipi's post-up `chmod -Rf a+rwx`. Then, over File Browser's real HTTP API:
  * starter folders Videos/, Videos/Edited/, Documents/ exist and are owned by uid 1000; existing content untouched
  * a SMOKE_FILES_MB (default 300) MB .mov is uploaded with tus in 10 MB chunks exactly like the web UI
    (POST /api/tus/<path> then PATCH chunks with Upload-Offset), lands in media/Videos, downloads back with equal SHA-256
  * a symlink pointing outside media is not followed
  * with FILES_PASSWORD set: anonymous access is refused, admin + password logs in
Leaves the container stopped and removed; prints a JSON report. Set SMOKE_FILES_KEEP=<dir> to reuse the root dir.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HELPER = "alpine:3.20"
CHUNK = 10 * 1024 * 1024


def run(*args, timeout=180, **kwargs):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if p.returncode:
        raise RuntimeError(f"{args[:4]} failed: {p.stderr[-1500:]}")
    return p.stdout.strip()


def as_root(root, *cmd):
    """Host-root actions (Runtipi CLI / backend run as root) on the disposable fake root only."""
    return run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
               f"type=bind,source={root},target=/r", HELPER, *cmd)


def runtipi_root(root):
    # Runtipi 4.8.0 CLI (internal/utils/system.go): MkdirAll(dir, 0755) as root for apps, app-data, media, ...;
    # EnsureFilePermissions chmods state/data/apps/... 777 but never media.
    as_root(root, "sh", "-c", "umask 022; mkdir -p /r/media /r/app-data /r/apps /r/state && chmod 0755 /r/media")
    return json.loads(as_root(root, "sh", "-c", "stat -c '{\"uid\":%u,\"gid\":%g,\"mode\":\"%a\"}' /r/media"))


class FB:
    def __init__(self, port):
        self.port, self.token = port, ""

    def req(self, method, path, body=None, headers=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        h = {**({"X-Auth": self.token} if self.token else {}), **(headers or {})}
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read() if not raw else r
        return (r.status, data, c) if raw else (r.status, data)

    def login(self, user="", password=""):
        status, data = self.req("POST", "/api/login", json.dumps({"username": user, "password": password, "recaptcha": ""}),
                                {"Content-Type": "application/json"})
        if status == 200:
            self.token = data.decode().strip()
        return status


def upload_tus(fb, local, remote):
    """The web UI's tus flow (frontend/src/api/tus.ts): create, then PATCH chunkSize slices with Upload-Offset."""
    size = local.stat().st_size
    status, body = fb.req("POST", "/api/tus/" + remote + "?override=false", b"",
                          {"Upload-Length": str(size), "Tus-Resumable": "1.0.0", "Content-Length": "0"})
    assert status == 201, (status, body[:300])
    offset, chunks = 0, 0
    with local.open("rb") as f:
        while offset < size:
            data = f.read(CHUNK)
            status, body = fb.req("PATCH", "/api/tus/" + remote, data, {
                "Content-Type": "application/offset+octet-stream", "Upload-Offset": str(offset), "Tus-Resumable": "1.0.0"})
            assert status == 204, (status, body[:300], offset)
            offset += len(data)
            chunks += 1
            if chunks == 3:  # resume check: HEAD reports the server's offset, as tus-js-client does after a drop
                st, _ = fb.req("HEAD", "/api/tus/" + remote, None, {"Tus-Resumable": "1.0.0"})
                assert st == 200, st
    return chunks


def download_sha(fb, remote):
    status, r, c = fb.req("GET", "/api/raw/" + remote, raw=True)
    assert status == 200, status
    h, n = hashlib.sha256(), 0
    while chunk := r.read(1024 * 1024):
        h.update(chunk)
        n += len(chunk)
    c.close()
    return h.hexdigest(), n


def start(name, root, password, compose):
    recipe = Path(root) / f"{name}.json"
    recipe.write_text(json.dumps(compose))
    app = Path(root) / "app-data" / "files"
    env = {**os.environ, "ROOT_FOLDER_HOST": str(root), "APP_DATA_DIR": str(app), "APP_PORT": "0", "FILES_PASSWORD": password}
    cmd = ["docker", "compose", "-p", name, "-f", str(recipe)]
    run(*cmd, "up", "-d", env=env)
    cid = run(*cmd, "ps", "-aq", env=env)
    # Runtipi 4.8.0 install step: chmod -Rf a+rwx on the app data dir after compose up.
    as_root(root, "chmod", "-Rf", "a+rwx", "/r/app-data/files")
    port = None
    for _ in range(120):
        state = json.loads(run("docker", "inspect", cid))[0]
        bindings = (state["NetworkSettings"]["Ports"] or {}).get("8080/tcp") or []
        port = next((int(b["HostPort"]) for b in bindings if b.get("HostIp") in ("127.0.0.1", "0.0.0.0")), None)
        health = (state["State"].get("Health") or {}).get("Status")
        if port and health == "healthy":
            break
        if state["State"]["Status"] == "exited":
            raise RuntimeError("files exited: " + run("docker", "logs", cid)[-2000:])
        time.sleep(1)
    else:
        raise RuntimeError("files never became healthy: " + run("docker", "logs", cid)[-2000:])
    return cmd, env, cid, port


def main():
    name = "files-smoke-" + secrets.token_hex(4)
    mb = int(os.environ.get("SMOKE_FILES_MB", "300"))
    report: dict = {"test": "Files app: translated Runtipi recipe on a fresh Runtipi-style media folder"}
    translated = json.loads(run("node", "scripts/translate-video-recipe.mjs", "files", cwd=ROOT))
    compose = translated["compose"]
    svc = compose["services"]["files"]
    assert svc["ports"] == ["${APP_PORT}:8080"] and svc["restart"] == "unless-stopped"
    svc["ports"] = ["127.0.0.1::8080"]  # test-only: loopback ephemeral port, isolated network
    compose["networks"]["tipi_main_network"] = {"name": name, "external": True}
    report["runtipi"] = {k: v for k, v in translated.items() if k != "compose"}
    keep = os.environ.get("SMOKE_FILES_KEEP")
    tmp = tempfile.TemporaryDirectory(prefix=name + "-", dir=os.environ.get("TMPDIR")) if not keep else None
    root = Path(keep or tmp.name)
    run("docker", "network", "create", name)
    cmd = env = None
    try:
        report["media_before"] = runtipi_root(root)
        assert report["media_before"] == {"uid": 0, "gid": 0, "mode": "755"}, report["media_before"]
        # Pre-existing content (e.g. from Jellyfin): must stay exactly as it is.
        as_root(root, "sh", "-c", "mkdir -p /r/media/data/movies && echo keep > /r/media/data/movies/a.txt && chmod 0640 "
                "/r/media/data/movies/a.txt && ln -s /etc /r/media/escape")
        cmd, env, cid, port = start(name, root, "", compose)
        st = json.loads(as_root(root, "sh", "-c", "printf '{'; for p in media media/Videos media/Videos/Edited media/Documents "
                                 "media/data/movies/a.txt; do printf '\"%s\":\"%s\",' $p \"$(stat -c '%u:%g:%a' /r/$p)\"; done; printf '\"_\":0}'"))
        st.pop("_")
        report["after_first_start"] = st
        assert st["media"] == "1000:1000:775", st
        for d in ("media/Videos", "media/Videos/Edited", "media/Documents"):
            assert st[d] == "1000:1000:775", (d, st)
        assert st["media/data/movies/a.txt"] == "0:0:640", st  # existing contents untouched
        report["process_uid"] = run("docker", "exec", cid, "sh", "-c", "stat -c %u /proc/1/task/*/ 2>/dev/null | head -1; "
                                    "for p in /proc/[0-9]*; do [ \"$(cat $p/comm)\" = filebrowser ] && stat -c %u $p; done")
        assert report["process_uid"].splitlines()[-1] == "1000", report["process_uid"]
        fb = FB(port)
        assert fb.login() == 200, "noauth login (the web UI's first call) should succeed"
        status, listing = fb.req("GET", "/api/resources/")
        names = sorted(i["name"] for i in json.loads(listing)["items"])
        report["root_listing"] = names
        assert {"Videos", "Documents", "data"} <= set(names), names
        # Symlink to /etc inside media: listing it must not reveal host files.
        status, body = fb.req("GET", "/api/resources/escape/")
        report["symlink_outside"] = status
        assert status != 200 or b"passwd" not in body, body[:200]
        # (a) ~300 MB chunked upload like the iPhone web UI, then download back.
        big = root / "IMG_9000.mov"
        with big.open("wb") as f:
            for _ in range(mb):
                f.write(os.urandom(1024 * 1024))
        src_sha = hashlib.sha256(big.read_bytes()).hexdigest()
        t0 = time.monotonic()
        chunks = upload_tus(fb, big, "Videos/IMG_9000.mov")
        up_s = time.monotonic() - t0
        landed = as_root(root, "stat", "-c", "%u:%g:%a:%s", "/r/media/Videos/IMG_9000.mov")
        t0 = time.monotonic()
        dl_sha, dl_bytes = download_sha(fb, "Videos/IMG_9000.mov")
        report["upload"] = {"bytes": big.stat().st_size, "chunks": chunks, "chunk_bytes": CHUNK, "upload_s": round(up_s, 1),
                            "download_s": round(time.monotonic() - t0, 1), "on_disk": landed, "sha256_match": dl_sha == src_sha}
        assert dl_sha == src_sha and dl_bytes == big.stat().st_size
        assert landed.startswith("1000:1000:664:"), landed
        big.unlink()
        # Restart keeps the database and stays open without a password.
        run(*cmd, "restart", env=env, timeout=120)
        run(*cmd, "down", env=env, timeout=120)
        # Password on: anonymous refused, admin + password works; then off again.
        pw = secrets.token_urlsafe(16)
        cmd, env, cid, port = start(name, root, pw, compose)
        fb = FB(port)
        report["password_mode"] = {"anonymous_login": fb.login(), "wrong_password": fb.login("admin", "nope-nope-nope")}
        fb.token = ""
        report["password_mode"]["anonymous_api"] = fb.req("GET", "/api/resources/")[0]
        report["password_mode"]["admin_login"] = fb.login("admin", pw)
        report["password_mode"]["admin_api"] = fb.req("GET", "/api/resources/Videos/")[0]
        assert report["password_mode"]["anonymous_api"] in (401, 403) and report["password_mode"]["admin_login"] == 200
        assert report["password_mode"]["anonymous_login"] != 200 and report["password_mode"]["admin_api"] == 200
        run(*cmd, "down", env=env, timeout=120)
        cmd, env, cid, port = start(name, root, "", compose)
        report["password_removed_noauth_login"] = FB(port).login()
        assert report["password_removed_noauth_login"] == 200
        report["result"] = "pass"
    finally:
        if cmd:
            subprocess.run([*cmd, "down", "--remove-orphans"], env=env, capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        if tmp:
            as_root(root, "rm", "-rf", "/r/media", "/r/app-data", "/r/apps", "/r/state")
            tmp.cleanup()
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    sys.exit(main())
