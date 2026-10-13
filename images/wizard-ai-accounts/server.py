"""AI Accounts: the owner connects AI subscriptions once; agent apps on the same server reuse them.

Claude subscription: through the unmodified official Claude Code CLI. This process never reads, copies,
prints or serves the credential files: it only runs `claude auth login|logout|status` and one tiny
`claude -p` test, and reports plan/account labels.

ChatGPT subscription: through stock Hermes Agent's own ChatGPT sign-in (its dashboard's device-code login).
This app signs in to the Hermes Agent dashboard with that app's own dashboard login and uses only the
ChatGPT sign-in and model routes. The ChatGPT tokens are created and kept inside Hermes; this app never
sees them.
"""
from __future__ import annotations

import base64
import fcntl
import hmac
import http.cookiejar
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
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "0.2.0"
APP = Path(__file__).resolve().parent
CLAUDE = os.environ.get("AI_ACCOUNTS_CLAUDE", "/usr/local/bin/claude")
CLAUDE_DIR = os.environ.get("AI_ACCOUNTS_CLAUDE_DIR", "/claude")
WORK = Path(os.environ.get("AI_ACCOUNTS_WORK_DIR", "/tmp/ai-accounts"))
BIND = os.environ.get("AI_ACCOUNTS_BIND", "0.0.0.0")
PORT = int(os.environ.get("AI_ACCOUNTS_PORT", "8795"))
PASSWORD = os.environ.get("AI_ACCOUNTS_PASSWORD", "")
LOGIN_TTL = 15 * 60
SIGN_IN_HOSTS = {"claude.com", "claude.ai", "console.anthropic.com", "platform.claude.com"}
# Hermes Agent app (same server): its dashboard, reached on the Runtipi network by the app's name.
HERMES_URL = os.environ.get("AI_ACCOUNTS_HERMES_URL", "http://hermes-agent:9119").rstrip("/")
HERMES_USER = os.environ.get("AI_ACCOUNTS_HERMES_USER", "") or "hermes"
HERMES_PASSWORD = os.environ.get("AI_ACCOUNTS_HERMES_PASSWORD", "")
CODEX = "openai-codex"   # Hermes' provider id for a ChatGPT subscription
CHATGPT_HOSTS = {"auth.openai.com"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")
URL = re.compile(r"https://[^\s\"'<>]+")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"), "/SKILL.md": ("SKILL.md", "text/markdown; charset=utf-8")}
# Later rows plug in here; the page renders whatever this list says.
COMING_SOON = [
    {"id": "api-keys", "name": "API keys", "kind": "api-key-gateway",
     "detail": "OpenRouter, Tinfoil, OpenAI and Anthropic keys, shared through one gateway.", "status": "coming_soon"},
]


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


class HermesError(Exception):
    pass


class Hermes:
    """The Hermes Agent dashboard, signed in with that app's dashboard login (session cookies, kept in memory).
    Only the ChatGPT sign-in and model routes are called. Error text never carries a token."""
    lock = threading.Lock()
    opener = None

    @classmethod
    def configured(cls) -> bool:
        return bool(HERMES_PASSWORD)

    @classmethod
    def _login(cls):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        body = json.dumps({"provider": "basic", "username": HERMES_USER, "password": HERMES_PASSWORD}).encode()
        req = urllib.request.Request(HERMES_URL + "/auth/password-login", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=20) as res:
                res.read()
        except urllib.error.HTTPError as e:
            raise HermesError("Hermes Agent did not accept this app's sign-in. Reinstall AI Accounts so it "
                              "gets the Hermes Agent dashboard login." if e.code in (401, 404)
                              else f"Hermes Agent answered {e.code}.") from None
        except OSError:
            raise HermesError("Hermes Agent is not reachable from AI Accounts. Is it running?") from None
        cls.opener = opener

    @classmethod
    def call(cls, method: str, path: str, body: dict | None = None, timeout: int = 40) -> dict:
        if not cls.configured():
            raise HermesError("Needs the Hermes Agent app from Wizard Apps on this server.")
        for attempt in (0, 1):
            with cls.lock:
                if cls.opener is None:
                    cls._login()
                opener = cls.opener
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(HERMES_URL + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"} if data is not None else {})
            try:
                with opener.open(req, timeout=timeout) as res:
                    return json.loads(res.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:   # the dashboard session expired: sign in once more
                    with cls.lock:
                        cls.opener = None
                    continue
                try:
                    detail = str(json.loads(e.read() or b"{}").get("detail") or "")
                except (ValueError, AttributeError):
                    detail = ""
                raise HermesError(URL.sub("[link]", detail)[:200] or f"Hermes Agent answered {e.code}.") from None
            except (OSError, ValueError):
                raise HermesError("Hermes Agent is not reachable from AI Accounts. Is it running?") from None
        raise HermesError("Hermes Agent did not accept this app's sign-in.")


def chatgpt_status() -> dict:
    """Connected or not (from Hermes' own sign-in status) and whether the agent uses it now. No token data."""
    if not Hermes.configured():
        return {"status": "unavailable", "detail": "Needs the Hermes Agent app from Wizard Apps on this server."}
    try:
        rows = Hermes.call("GET", "/api/providers/oauth").get("providers") or []
        row = next((p for p in rows if isinstance(p, dict) and p.get("id") == CODEX), None)
        info = Hermes.call("GET", "/api/model/info")
    except HermesError as e:
        return {"status": "error", "detail": str(e)}
    if row is None:
        return {"status": "error", "detail": "This Hermes Agent has no ChatGPT sign-in."}
    in_use = info.get("provider") == CODEX
    if not (row.get("status") or {}).get("logged_in"):
        return {"status": "not_connected", "in_use": in_use}
    return {"status": "connected", "plan": "ChatGPT", "account": "", "in_use": in_use,
            "model": str(info.get("model") or "")[:80] if in_use else ""}


def use_chatgpt(force: bool) -> bool:
    """Point the agent's main model at ChatGPT. Without force, only when its current account doesn't work,
    so connecting ChatGPT never silently moves an agent off a working account. True when switched."""
    rows = Hermes.call("GET", "/api/model/options?include_unconfigured=true", timeout=90).get("providers") or []
    current = next((p for p in rows if p.get("is_current")), None)
    if current and current.get("slug") == CODEX:
        return False
    if not force and current and current.get("authenticated"):
        return False
    codex = next((p for p in rows if p.get("slug") == CODEX), {})
    models = [m for m in (codex.get("featured_models") or []) + (codex.get("models") or []) if isinstance(m, str)]
    if not models:
        raise HermesError("ChatGPT is connected, but Hermes lists no ChatGPT models yet. Press Use ChatGPT in a minute.")
    res = Hermes.call("POST", "/api/model/set", {"scope": "main", "provider": CODEX, "model": models[0],
                                                 "confirm_expensive_model": True}, timeout=90)
    if res.get("ok") is False:
        raise HermesError(str(res.get("confirm_message") or res.get("detail") or "Hermes did not switch the model.")[:200])
    return True


class ChatGPT:
    lock = threading.Lock()
    session = ""     # Hermes' sign-in session id (never sent to the browser)
    login_id = ""    # this page's handle for it
    started = 0.0


def _end_chatgpt():
    sid, ChatGPT.session, ChatGPT.login_id = ChatGPT.session, "", ""
    if sid:
        try:
            Hermes.call("DELETE", f"/api/providers/oauth/sessions/{sid}")
        except HermesError:
            pass


def chatgpt_connect() -> tuple[int, dict]:
    with ChatGPT.lock:
        _end_chatgpt()
        try:
            d = Hermes.call("POST", f"/api/providers/oauth/{CODEX}/start", {}, timeout=40)
        except HermesError as e:
            return 502, {"ok": False, "message": str(e)}
        url, code, sid = str(d.get("verification_url") or ""), str(d.get("user_code") or ""), str(d.get("session_id") or "")
        parts = urlsplit(url)
        if not sid or parts.scheme != "https" or parts.hostname not in CHATGPT_HOSTS \
                or not re.fullmatch(r"[A-Za-z0-9-]{4,24}", code):
            ChatGPT.session = sid
            _end_chatgpt()
            return 502, {"ok": False, "message": "ChatGPT did not give a sign-in code. Try again in a minute."}
        ChatGPT.session, ChatGPT.login_id, ChatGPT.started = sid, secrets.token_urlsafe(16), time.monotonic()
        return 200, {"ok": True, "login_id": ChatGPT.login_id, "url": url, "code": code,
                     "expires_in": int(d.get("expires_in") or 900)}


def chatgpt_poll(login_id: str) -> tuple[int, dict]:
    with ChatGPT.lock:
        if not ChatGPT.login_id or not hmac.compare_digest(login_id.encode(), ChatGPT.login_id.encode()):
            return 409, {"ok": False, "status": "expired", "message": "This sign-in expired. Press Connect again."}
        sid = ChatGPT.session
    try:
        d = Hermes.call("GET", f"/api/providers/oauth/{CODEX}/poll/{sid}")
    except HermesError as e:
        with ChatGPT.lock:
            ChatGPT.session = ChatGPT.login_id = ""
        return 409, {"ok": False, "status": "expired", "message": "This sign-in expired. Press Connect again."
                     if "not found" in str(e).lower() else str(e)}
    status = d.get("status")
    if status == "pending":
        return 200, {"ok": True, "status": "pending"}
    with ChatGPT.lock:
        ChatGPT.session = ChatGPT.login_id = ""
    if status != "approved":
        return 400, {"ok": False, "status": status or "error",
                     "message": "The code expired before it was approved. Press Connect again." if status == "expired"
                     else "ChatGPT sign-in did not finish. Press Connect to try again."}
    try:
        switched = use_chatgpt(force=False)
        message = ("Connected. Your agent now uses ChatGPT." if switched else
                   "Connected. Your agent keeps its current account; press Use ChatGPT to switch.")
    except HermesError as e:
        message = f"Connected, but the agent was not switched: {e}"
    return 200, {"ok": True, "status": "approved", "message": message, "chatgpt": chatgpt_status()}


def chatgpt_cancel() -> tuple[int, dict]:
    with ChatGPT.lock:
        _end_chatgpt()
    return 200, {"ok": True}


def chatgpt_use() -> tuple[int, dict]:
    if chatgpt_status().get("status") != "connected":
        return 409, {"ok": False, "message": "Connect ChatGPT first."}
    try:
        switched = use_chatgpt(force=True)
    except HermesError as e:
        return 502, {"ok": False, "message": str(e)}
    return 200, {"ok": True, "message": "Your agent now uses ChatGPT for new chats." if switched
                 else "Your agent already uses ChatGPT.", "chatgpt": chatgpt_status()}


def chatgpt_logout() -> tuple[int, dict]:
    with ChatGPT.lock:
        _end_chatgpt()
    before = chatgpt_status()
    try:
        Hermes.call("DELETE", f"/api/providers/oauth/{CODEX}")
    except HermesError as e:
        return 502, {"ok": False, "message": str(e)}
    status = chatgpt_status()
    ok = status.get("status") == "not_connected"
    message = "Disconnected." if ok else "Still connected."
    if ok and before.get("in_use"):
        message = "Disconnected. Your agent was using ChatGPT: connect it again, or connect another account."
    return (200 if ok else 500), {"ok": ok, "message": message, "chatgpt": status}


def card(host: str) -> dict:
    base = f"http://{host}" if host else f"http://wizard-ai-accounts:{PORT}"
    return {
        "name": "wizard-ai-accounts", "version": VERSION, "title": "AI Accounts",
        "description": "Connect AI subscriptions once: Claude (official Claude Code login, shared with agent apps "
                       "through a private volume) and ChatGPT (Hermes Agent's own ChatGPT sign-in).",
        "remotes": [],
        "x-wizard": {
            "kind": "system-agent-app",
            "provides": ["claude-subscription", "chatgpt-subscription"],
            "skill": f"{base}/SKILL.md",
            "status_api": f"{base}/api/accounts",
            "shared_volume": {"name": "wizard-ai-accounts-claude", "mount": "/claude", "uid": 1000, "gid": 1000,
                              "consumer_env": {"CLAUDE_SUBSCRIPTION_DIRECTSDK_CONFIG_DIR": "/claude"}},
            "claude_code": {"version": os.environ.get("CLAUDE_CODE_VERSION", ""), "auto_update": False},
            "coming_soon": [row["id"] for row in COMING_SOON],
            "ai_calls": "owner-initiated test only",
            "secrets_exposed": False,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "wizard-ai-accounts"
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
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code: int, data: dict):
        self.send(code, json.dumps(data).encode(), "application/json")

    def authorized(self, path: str) -> bool:
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
        self.send_header("WWW-Authenticate", 'Basic realm="AI Accounts", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

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
        if path == "/api/accounts":
            login = State.login
            claude = {"id": "claude-subscription", "name": "Claude subscription", "kind": "subscription",
                      "detail": "Pro or Max plan, signed in with the official Claude Code app.", **claude_status(),
                      "signing_in": bool(login and login.alive())}
            chatgpt = {"id": "chatgpt-subscription", "name": "ChatGPT subscription", "kind": "subscription",
                       "detail": "Plus or Pro plan, signed in through Hermes Agent's own ChatGPT sign-in.",
                       **chatgpt_status(), "signing_in": bool(ChatGPT.login_id)}
            return self.json(200, {"accounts": [claude, chatgpt, *COMING_SOON], "version": VERSION})
        if path in STATIC:
            name, ctype = STATIC[path]
            return self.send(200, (APP / "static" / name).read_bytes() if name != "SKILL.md" else
                             (APP / "SKILL.md").read_bytes(), ctype)
        self.json(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
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
        if path == "/api/chatgpt/connect":
            return self.json(*chatgpt_connect())
        if path == "/api/chatgpt/poll":
            return self.json(*chatgpt_poll(str(body.get("login_id", ""))))
        if path == "/api/chatgpt/cancel":
            return self.json(*chatgpt_cancel())
        if path == "/api/chatgpt/use":
            return self.json(*chatgpt_use())
        if path == "/api/chatgpt/logout":
            return self.json(*chatgpt_logout())
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
    print(f"AI Accounts {VERSION} on {BIND}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        with State.lock:
            end_login()
        with ChatGPT.lock:
            _end_chatgpt()
        server.server_close()


if __name__ == "__main__":
    main()
