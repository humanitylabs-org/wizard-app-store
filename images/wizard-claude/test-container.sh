#!/bin/sh
# Build the image, then prove the logged-out paths of the real official CLI inside it:
# pinned version, not-connected status, a real claude sign-in URL from `claude auth login` in a pty,
# a wrong code failing cleanly, logout and test on a logged-out dir, and no credential surface.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TAG=${WIZARD_CLAUDE_IMAGE:-wizard-claude:test}
[ -n "${SKIP_BUILD:-}" ] || docker buildx build --load -t "$TAG" "$ROOT"
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --memory 512m --pids-limit 128 \
  --tmpfs /claude:rw,nosuid,size=8m,uid=1000,gid=1000,mode=0700 --tmpfs /tmp:rw,nosuid,size=64m,uid=1000,gid=1000 \
  -e WIZARD_CLAUDE_PORT=8799 -e WIZARD_CLAUDE_USAGE_URL=http://127.0.0.1:9/api/oauth/usage --entrypoint python3 "$TAG" -c '
import json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error
from urllib.parse import urlsplit, parse_qs
assert os.getuid() == 1000 and os.getgid() == 1000, "must run as 1000:1000"
files = sorted(str(p.relative_to("/app")) for p in pathlib.Path("/app").rglob("*") if p.is_file())
assert files == sorted(["LICENSE", "SKILL.md", "inference.py", "models.json", "server.py", "static/app.css", "static/app.js", "static/appearance.css", "static/appearance.js", "static/index.html", "usage.py", "warm_spare.py", "pool_server.py", "pool_client.py", *["pool-static/" + n for n in ("app.css", "app.js", "boot.js", "index.html", "logo-chatgpt.svg", "logo-claude.svg", "theme-client.js", "wizard-layout.css", "wizard-sheet.js", "wizard-tokens.css", "wizard-ui.css")]]), files
v = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
assert v.startswith(os.environ["CLAUDE_CODE_VERSION"] + " "), v
assert os.environ["DISABLE_AUTOUPDATER"] == "1"
p = subprocess.Popen([sys.executable, "/app/server.py"])
B = "http://127.0.0.1:8799"
def req(path, body=None, headers=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    r = urllib.request.Request(B + path, data=None if body is None else json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(r, timeout=150) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
t0 = time.monotonic()
while time.monotonic() - t0 < 10:
    try:
        code, body = req("/health"); break
    except OSError: time.sleep(0.1)
health = json.loads(body); assert health["status"] == "ok" and health["claude_code"] == os.environ["CLAUDE_CODE_VERSION"], health
code, body = req("/"); assert code == 200 and b"<title>Claude</title>" in body
h = urllib.request.urlopen(B + "/", timeout=30).headers
assert h["Content-Security-Policy"].split("frame-ancestors ")[1].startswith(chr(39) + "self" + chr(39) + ";") and h["X-Frame-Options"] == "SAMEORIGIN", dict(h)
for f in ("/app.js", "/app.css", "/appearance.js", "/appearance.css", "/SKILL.md"): assert req(f)[0] == 200, f
code, body = req("/.well-known/mcp/server-cards.json"); cardj = json.loads(body)
assert cardj["x-wizard"]["kind"] == "system-agent-app" and cardj["x-wizard"]["provides"] == ["ai-connection", "claude-subscription"], cardj
assert cardj["name"] == "wizard-claude" and cardj["x-wizard"]["contract"] == "wizard.ai-connection/2", cardj
accounts = json.loads(req("/api/accounts")[1])["accounts"]
assert [a["id"] for a in accounts] == ["claude-subscription"], accounts
assert accounts[0]["status"] == "not_connected", accounts[0]
# wizard.ai-connection/2, logged out: exactly the contract keys, no usage, signed_out.
code, body = req("/api/connection"); conn = json.loads(body)
assert code == 200 and conn == {"contract": "wizard.ai-connection/2", "provider": "claude", "name": "Claude",
    "status": "not_connected", "plan": None, "account": None, "usage": None,
    "error": {"code": "signed_out", "message": conn["error"]["message"]}, "models": json.loads(pathlib.Path("/app/models.json").read_text())["models"]}, conn
# Box-only: anything that came through Serve, a tunnel or a proxy is refused.
for h in ({"Tailscale-User-Login": "x@y"}, {"X-Forwarded-For": "1.2.3.4"}, {"Forwarded": "for=1.2.3.4"},
          {"X-Real-IP": "1.2.3.4"}, {"CF-Connecting-IP": "1.2.3.4"}, {"cf-ray": "abc"}):
    code, body = req("/api/connection", None, h)
    assert code == 403 and b"box-only" in body and b"status" not in body, (h, code, body)
# The Connect page itself behaves as in AI Accounts (no proxy refusal).
assert req("/", None, {"Tailscale-User-Login": "x@y"})[0] == 200
# No credential surface: traversal and credential paths are 404.
for path in ("/.credentials.json", "/claude/.credentials.json", "/../claude/.credentials.json", "/static/../server.py",
             "/api/claude/credentials", "/usage.py", "/api/connection/../../claude/.credentials.json", "/.claude.json"):
    assert req(path)[0] == 404, path
# Cross-site and non-JSON posts refused.
assert req("/api/claude/test", {}, {"Origin": "http://evil.example"})[0] == 403
r = urllib.request.Request(B + "/api/claude/cancel", data=b"x", headers={"Content-Type": "text/plain"})
try: urllib.request.urlopen(r, timeout=5); raise AssertionError("non-JSON post accepted")
except urllib.error.HTTPError as e: assert e.code == 415, e.code
# Test on a logged-out dir: clean "not logged in" message.
code, body = req("/api/claude/test", {}); t = json.loads(body)
assert code == 502 and not t["ok"] and "not logged in" in t["message"].lower(), t
# Logout on a logged-out dir: stays not connected.
code, body = req("/api/claude/logout", {}); lo = json.loads(body)
assert lo["claude"]["status"] == "not_connected", lo
# Connect: the official CLI shows a real Claude sign-in URL and waits in the pty.
code, body = req("/api/claude/connect", {}); c = json.loads(body)
assert code == 200 and c["ok"], c
u = urlsplit(c["url"]); q = parse_qs(u.query)
assert u.scheme == "https" and u.hostname in ("claude.com", "claude.ai") and "oauth/authorize" in u.path, u._replace(query="")
assert {"client_id", "code_challenge", "state", "redirect_uri"} <= set(q), sorted(q)
assert json.loads(req("/api/accounts")[1])["accounts"][0]["signing_in"] is True
# Malformed and stale codes are refused before reaching the CLI.
assert req("/api/claude/code", {"login_id": c["login_id"], "code": "bad code with spaces"})[0] == 400
assert req("/api/claude/code", {"login_id": "stale", "code": "abc"})[0] == 409
# A wrong code goes to the waiting CLI and fails cleanly.
code, body = req("/api/claude/code", {"login_id": c["login_id"], "code": "wrong-code-123#" + q["state"][0]}); w = json.loads(body)
assert code == 400 and not w["ok"] and w["claude"]["status"] == "not_connected", w
assert "wrong-code" not in w["message"], w
assert json.loads(req("/api/accounts")[1])["accounts"][0]["signing_in"] is False
# Cancel path leaves no login process behind.
c2 = json.loads(req("/api/claude/connect", {})[1]); assert c2["ok"]
assert json.loads(req("/api/claude/cancel", {})[1])["ok"]
time.sleep(0.5)
procs = [pathlib.Path(f"/proc/{d}/cmdline").read_bytes() for d in os.listdir("/proc") if d.isdigit() and os.path.exists(f"/proc/{d}/cmdline")]
assert not any(b"auth\x00login" in x for x in procs), "login process left running"
# A fake sign-in (usage URL points at a closed loopback port): the token never reaches any response.
fake = "sk-ant-oat01-CONTAINER-TEST-TOKEN"
pathlib.Path("/claude/.credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": fake,
    "refreshToken": fake + "-r", "expiresAt": int(time.time() * 1000) + 3600000, "subscriptionType": "max",
    "rateLimitTier": "default_claude_max_5x"}}))
code, body = req("/api/connection"); conn = json.loads(body)
assert conn["status"] == "error" and conn["plan"] == "Max 5x" and conn["error"]["code"] == "unreachable" and conn["usage"] is None, conn
everything = b"".join(req(x)[1] for x in ("/api/connection", "/api/accounts", "/", "/app.js", "/SKILL.md", "/health",
                                          "/.well-known/mcp/server-cards.json"))
assert fake.encode() not in everything and b"Bearer" not in everything, "token surfaced"
assert json.loads(pathlib.Path("/claude/.credentials.json").read_text())["claudeAiOauth"]["refreshToken"] == fake + "-r"
pathlib.Path("/claude/.credentials.json").unlink()
p.terminate(); rc = p.wait(10)
print(json.dumps({"uid": os.getuid(), "claude": v, "fake_signin_status": conn["status"], "wrong_code": w["message"], "test_logged_out": t["message"],
                  "signin_host": u.hostname, "signin_path": u.path, "sigterm_exit": rc}))
assert rc == 0, rc'
docker image inspect "$TAG" --format 'image size bytes: {{.Size}}'
python3 "$ROOT/../../tests/pool-container-smoke.py" claude "$TAG"
