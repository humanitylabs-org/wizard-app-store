"""Claude: the owner connects his Claude subscription once; agent apps on the same server reuse it.

A Wizard AI connection app (contract wizard.ai-connection/2, decisions #61 and #65).
Login, test and logout run the unmodified official CLI. usage.py reads the app-owned
access credential for usage; inference.py passes it only in the isolated
CLI child environment for router-authorized inference. No route serves or logs credentials;
refresh remains owned by the official CLI login/test flow.
"""
from __future__ import annotations

import base64
import fcntl
import hmac
import json
import os
import re
import secrets
import select
import signal
import socketserver
import struct
import subprocess
import sys
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

# Also supports the existing isolated (-I) launch used by the test harness.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import inference

import usage

VERSION = "0.2.14"
APP = Path(__file__).resolve().parent
CLAUDE = os.environ.get("WIZARD_CLAUDE_CLAUDE", "/usr/local/bin/claude")
CLAUDE_DIR = os.environ.get("WIZARD_CLAUDE_CLAUDE_DIR", "/claude")
WORK = Path(os.environ.get("WIZARD_CLAUDE_WORK_DIR", "/tmp/wizard-claude"))
BIND = os.environ.get("WIZARD_CLAUDE_BIND", "0.0.0.0")
PORT = int(os.environ.get("WIZARD_CLAUDE_PORT", "8799"))
PASSWORD = os.environ.get("WIZARD_CLAUDE_PASSWORD", "")
LOGIN_TTL = 15 * 60
SIGN_IN_HOSTS = {"claude.com", "claude.ai", "console.anthropic.com", "platform.claude.com"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")
URL = re.compile(r"https://[^\s\"'<>]+")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/appearance.js": ("appearance.js", "text/javascript; charset=utf-8"),
          "/appearance.css": ("appearance.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"), "/SKILL.md": ("SKILL.md", "text/markdown; charset=utf-8")}
# Owner-data routes are box-only: the same port is published on the tailnet (Serve, tunnels and
# proxies add these headers), while agents and the Agent Service call the app on the app network.
PROXY_HEADERS = ("tailscale-user-login", "x-forwarded-for", "forwarded", "x-real-ip")
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$")
FRAME_ANCESTORS = " ".join(["'self'"] + [o for o in (x.strip().rstrip("/") for x in
                                         os.environ.get("WIZARD_TRUSTED_ORIGINS", "").split(","))
                                         if _ORIGIN.match(o)])


class Renew:
    """Auto-renew: an expired sign-in is renewed by the official Claude Code itself (a one-word Haiku turn, the same
    as the page's Test button). This app never refreshes a token. At most one attempt per RENEW_GAP_S."""
    lock = threading.Lock()
    at = 0.0
    thread: threading.Thread | None = None


RENEW_GAP_S = 600


def renew_if_expired(answer: dict, reader=None) -> dict:
    if answer.get("status") != "expired" or os.environ.get("WIZARD_CLAUDE_AUTO_RENEW", "1") == "0":
        return answer
    with Renew.lock:
        if Renew.thread is not None and Renew.thread.is_alive():
            return {**answer, "status": "renewing"}
        if time.monotonic() - Renew.at < RENEW_GAP_S and Renew.at:
            return answer
        # Only scheduling happens on the HTTP thread. The official CLI may take
        # 120 seconds; never hold a GET (or this lock) through its execution.
        Renew.thread = threading.Thread(target=_renew, args=(reader or CONNECTION,), daemon=True)
        Renew.thread.start()
    return {**answer, "status": "renewing"}


def _renew(reader):
    try:
        code, _ = run_test()
        if code == 200:
            reader.read()  # same credential owner; the next GET reads fresh state
    except Exception:
        pass  # Never expose CLI/challenge output; expired state remains readable.
    finally:
        with Renew.lock:
            Renew.at = time.monotonic()  # completion-based cooldown, including failure


CONNECTION = usage.ConnectionReader(CLAUDE_DIR, os.environ.get("WIZARD_CLAUDE_USAGE_URL", usage.USAGE_URL))


def claude_env() -> dict:
    """A clean environment: never inherit API keys or alternate backends into the official CLI."""
    WORK.mkdir(parents=True, exist_ok=True)
    home = WORK / "home"
    home.mkdir(exist_ok=True)
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": CLAUDE_DIR,
            "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "BROWSER": "/bin/true", "TERM": "xterm-256color",
            "COLUMNS": "1000", "LANG": "C.UTF-8", "TMPDIR": str(WORK)}


def clean(text: str) -> str:
    return ANSI.sub("", text).replace("\r", "\n")


def plan_label(raw) -> str:
    raw = str(raw or "").strip()
    if not raw:
        return "Claude"
    return raw if raw.lower().startswith("claude") else "Claude " + raw.replace("_", " ").title()


def claude_version() -> str:
    try:
        out = subprocess.run([CLAUDE, "--version"], env=claude_env(), capture_output=True, text=True, timeout=20)
        return out.stdout.strip().split(" ")[0]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def claude_status() -> dict:
    """Plan and account label only, from the CLI's own `auth status`."""
    if not os.access(CLAUDE, os.X_OK):
        return {"status": "error", "detail": "Claude Code is missing from this app."}
    if not os.access(CLAUDE_DIR, os.W_OK):
        return {"status": "error", "detail": "The shared Claude login folder is not writable."}
    try:
        out = subprocess.run([CLAUDE, "auth", "status", "--json"], env=claude_env(), cwd=WORK,
                             capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"status": "error", "detail": "Could not read the sign-in status from Claude Code."}
    if not data.get("loggedIn"):
        return {"status": "not_connected"}
    if data.get("authMethod") != "claude.ai":
        return {"status": "connected", "plan": "Not a Claude subscription", "account": "",
                "detail": "Claude Code is signed in another way. Disconnect, then connect your Claude subscription."}
    account = data.get("email") or data.get("orgName") or ""
    return {"status": "connected", "plan": plan_label(data.get("subscriptionType")), "account": str(account)[:120]}


class Login:
    """One official `claude auth login` running in a pseudo-terminal, waiting for the pasted code."""

    def __init__(self):
        master, slave = os.openpty()
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO  # the pasted code is never echoed back into the captured output
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))
        self.proc = subprocess.Popen([CLAUDE, "auth", "login", "--claudeai"], stdin=slave, stdout=slave, stderr=slave,
                                     env=claude_env(), cwd=WORK, start_new_session=True, close_fds=True)
        os.close(slave)
        self.master, self.buf, self.lock = master, "", threading.Lock()
        self.started, self.code_sent = time.monotonic(), False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        while True:
            try:
                ready, _, _ = select.select([self.master], [], [], 0.5)
                if ready:
                    data = os.read(self.master, 65536)
                    if not data:
                        break
                    with self.lock:
                        self.buf = (self.buf + data.decode("utf-8", "replace"))[-65536:]
                elif self.proc.poll() is not None:
                    break
            except OSError:
                break

    def text(self) -> str:
        with self.lock:
            return clean(self.buf)

    def url(self) -> str:
        for candidate in URL.findall(self.text()):
            parts = urlsplit(candidate)
            if parts.scheme == "https" and parts.hostname in SIGN_IN_HOSTS and "oauth" in parts.path:
                return candidate
        return ""

    def wait_url(self, timeout=45) -> str:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = self.url()
            if found and "paste code" in self.text().lower():
                return found
            if self.proc.poll() is not None:
                return self.url()
            time.sleep(0.2)
        return self.url()

    def submit(self, code: str, timeout=90) -> dict:
        self.code_sent = True
        mark = len(self.text())
        os.write(self.master, code.encode() + b"\r")
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.proc.poll() is None:
            time.sleep(0.25)
        if self.proc.poll() is None:
            self.close()
            return {"ok": False, "message": "Claude did not answer in time. Try connecting again."}
        tail = self.text()[mark:]
        match = re.search(r"Login (successful[^\n]*|failed[^\n]*)", tail)
        message = URL.sub("[link]", match.group(0).strip())[:200] if match else ""
        ok = self.proc.returncode == 0
        self.close()
        if not message:
            message = "Signed in." if ok else "Claude did not accept that code. Start again and paste the newest code."
        return {"ok": ok, "message": message}

    def alive(self) -> bool:
        return self.proc.poll() is None and time.monotonic() - self.started < LOGIN_TTL

    def close(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            os.close(self.master)
        except OSError:
            pass
        self.proc.wait()


class State:
    lock = threading.Lock()
    login: Login | None = None
    login_id = ""
    busy = threading.Lock()  # one test/logout at a time
    after_sign_in = None  # set by the pool server: make the new sign-in the agent's model when it has none


def end_login():
    if State.login is not None:
        State.login.close()
    State.login, State.login_id = None, ""


def connect() -> tuple[int, dict]:
    with State.lock:
        end_login()
        try:
            login = Login()
        except OSError:
            return 500, {"ok": False, "message": "Could not start Claude Code."}
        url = login.wait_url()
        if not url or not login.alive():
            login.close()
            return 502, {"ok": False, "message": "Claude Code did not show a sign-in link. Try again in a minute."}
        State.login, State.login_id = login, secrets.token_urlsafe(16)
        return 200, {"ok": True, "login_id": State.login_id, "url": url}


def submit_code(login_id: str, code: str) -> tuple[int, dict]:
    code = code.strip()
    if not code or len(code) > 512 or not re.fullmatch(r"[A-Za-z0-9._~#=+/-]+", code):
        return 400, {"ok": False, "message": "That doesn't look like a Claude code. Copy the whole code Claude shows you."}
    with State.lock:
        login = State.login
        if login is not None and not login.alive():
            end_login()
            login = None
        if login is None or not hmac.compare_digest(login_id.encode(), State.login_id.encode()):
            return 409, {"ok": False, "message": "This sign-in expired. Press Connect again."}
        result = login.submit(code)
        State.login, State.login_id = None, ""
    if result["ok"] and State.after_sign_in is not None:
        try:
            result = {**result, "agent_default": State.after_sign_in()}
        except Exception:
            pass
    return (200 if result["ok"] else 400), {**result, "claude": claude_status()}


def logout() -> tuple[int, dict]:
    with State.lock:
        end_login()
    with State.busy:
        try:
            out = subprocess.run([CLAUDE, "auth", "logout"], env=claude_env(), cwd=WORK,
                                 capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return 500, {"ok": False, "message": "Claude Code did not finish signing out."}
        status = claude_status()
        ok = status.get("status") == "not_connected"
        message = "Disconnected." if ok else (clean(out.stdout + out.stderr).strip()[:200] or "Still connected.")
        return (200 if ok else 500), {"ok": ok, "message": message, "claude": status}


def run_test() -> tuple[int, dict]:
    if not State.busy.acquire(blocking=False):
        return 409, {"ok": False, "message": "A test is already running."}
    try:
        work = WORK / "test"
        work.mkdir(parents=True, exist_ok=True)
        cmd = [CLAUDE, "-p", "Reply with exactly the word OK.", "--model", "haiku", "--output-format", "json",
               "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--max-turns", "1"]
        start = time.monotonic()
        try:
            out = subprocess.run(cmd, env=claude_env(), cwd=work, capture_output=True, text=True, timeout=120,
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return 504, {"ok": False, "message": "Claude did not answer within 2 minutes."}
        seconds = round(time.monotonic() - start, 1)
        try:
            data = json.loads(out.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 502, {"ok": False, "message": "Claude Code returned no result.", "seconds": seconds}
        reply = URL.sub("[link]", clean(str(data.get("result") or ""))).strip()[:200]
        models = sorted((data.get("modelUsage") or {}).keys())
        if data.get("is_error"):
            return 502, {"ok": False, "message": reply or "Claude returned an error.", "seconds": seconds}
        return 200, {"ok": True, "message": "OK: Claude answered.", "reply": reply, "model": models[0] if models else "",
                     "seconds": seconds}
    finally:
        State.busy.release()


def card(host: str) -> dict:
    base = f"http://{host}" if host else f"http://wizard-claude:{PORT}"
    return {
        "name": "wizard-claude", "version": VERSION, "title": "Claude",
        "description": "Connect your Claude subscription once with the official Claude Code login. "
                       "Agent apps on this server reuse the login through a shared private volume.",
        "remotes": [],
        "x-wizard": {
            "kind": "system-agent-app",
            "provides": ["ai-connection", "claude-subscription"],
            "contract": "wizard.ai-connection/2",
            "skill": f"{base}/SKILL.md",
            "connection_api": f"{base}/api/connection",
            "shared_volume": {"name": "wizard-ai-accounts-claude", "mount": "/claude", "uid": 1000, "gid": 1000,
                              "consumer_env": {"CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR": "/claude"}},
            "claude_code": {"version": os.environ.get("CLAUDE_CODE_VERSION", ""), "auto_update": False},
            "ai_calls": "owner test, and one Haiku renewal turn when the sign-in has expired (at most every 10 min)",
            "secrets_exposed": False,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "wizard-claude"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 - request lines only; never bodies
        sys.stderr.write("%s %s\n" % (self.command, urlsplit(self.path).path))

    def send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # Framing: only this page itself and the Wizard shell origins the App Manager trusts (WIZARD_TRUSTED_ORIGINS),
        # so the page opens inside a Wizard window and no other site can frame its Connect buttons.
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors " + FRAME_ANCESTORS +
                         "; base-uri 'none'; form-action 'none'")
        if FRAME_ANCESTORS == "'self'":
            self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code: int, data: dict):
        self.send(code, json.dumps(data).encode(), "application/json")

    def authorized(self, path: str) -> bool:
        if path == "/api/connection" and self.headers.get("X-Wizard-Grant"):
            try:
                if inference.admit(self.headers):
                    return True
            except inference.Fault as e:
                self.json(e.status, e.payload())
                return False
        if not PASSWORD or path == "/health":
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                _, _, given = base64.b64decode(header[6:]).decode().partition(":")
                if hmac.compare_digest(given.encode(), PASSWORD.encode()):
                    return True
            except (ValueError, UnicodeDecodeError):
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Claude", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def proxied(self) -> bool:
        return any(k.lower() in PROXY_HEADERS or k.lower().startswith("cf-") for k in self.headers.keys())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.authorized(path):
            return
        if path == "/health":
            return self.json(200, {"status": "ok", "version": VERSION,
                                   "claude_code": os.environ.get("CLAUDE_CODE_VERSION", "")})
        if path == "/.well-known/mcp/server-cards.json":
            return self.json(200, card(self.headers.get("Host", "")))
        if path == "/api/connection":
            if self.proxied():
                return self.json(403, {"error": "box-only: call this from the server (app network or 127.0.0.1)"})
            answer = renew_if_expired(CONNECTION.read())
            if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
                # Service-supplied subscription credential, never written to the login volume.
                answer = {**answer, "status": "connected", "error": None}
            try:
                return self.json(200, {**answer, "contract": "wizard.ai-connection/2", "models": inference.models()})
            except inference.Fault as e:
                return self.json(200, {**answer, "contract": "wizard.ai-connection/2", "models": [], "models_error": {"code": e.code, "message": str(e)}})
        if path == "/api/accounts":
            login = State.login
            claude = {"id": "claude-subscription", "name": "Claude subscription", "kind": "subscription",
                      "detail": "Pro or Max plan, signed in with the official Claude Code app.", **claude_status(),
                      "signing_in": bool(login and login.alive())}
            return self.json(200, {"accounts": [claude], "version": VERSION})
        if path in STATIC:
            name, ctype = STATIC[path]
            return self.send(200, (APP / "static" / name).read_bytes() if name != "SKILL.md" else
                             (APP / "SKILL.md").read_bytes(), ctype)
        self.json(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/infer":
            return inference.handle(self, CLAUDE, CLAUDE_DIR, WORK)
        if not self.authorized(path):
            return
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.json(403, {"ok": False, "message": "Cross-site request refused."})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.json(415, {"ok": False, "message": "JSON only."})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 4096:
            return self.json(413, {"ok": False, "message": "Too large."})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.json(400, {"ok": False, "message": "Bad request."})
        if path == "/api/claude/connect":
            return self.json(*connect())
        if path == "/api/claude/code":
            return self.json(*submit_code(str(body.get("login_id", "")), str(body.get("code", ""))))
        if path == "/api/claude/cancel":
            with State.lock:
                end_login()
            return self.json(200, {"ok": True})
        if path == "/api/claude/logout":
            return self.json(*logout())
        if path == "/api/claude/test":
            return self.json(*run_test())
        self.json(404, {"ok": False, "message": "not found"})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):  # skip getfqdn(): it stalls without a resolver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for _ in range(120):  # Runtipi may still be preparing the shared volume
        if os.access(CLAUDE_DIR, os.W_OK):
            break
        time.sleep(1)
    server = Server((BIND, PORT), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"Claude {VERSION} on {BIND}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        with State.lock:
            end_login()
        server.server_close()


if __name__ == "__main__":
    main()
