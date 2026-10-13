"""ChatGPT sign-in, end to end against a stand-in Hermes Agent dashboard (no network, no real account).

Runs server.py as a subprocess pointed at a fake Hermes that speaks the same routes stock Hermes Agent's
dashboard serves (/auth/password-login, /api/providers/oauth..., /api/model/...). Proves: the page signs in to
Hermes with its dashboard login and re-signs after a 401; Connect shows the OpenAI code; Poll finishes it;
a working agent account is never switched silently; an agent with no working account is switched; Use ChatGPT
needs a connected account; Disconnect works; cancel ends Hermes' session; no token ever reaches the browser.
Usage: python3 test-chatgpt.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = "tok-SECRET-never-shown"


class Fake:
    logged_in = False
    current = "claude-subscription-directsdk-experimental"
    current_ok = True
    sessions: dict = {}
    calls: list = []
    expire_cookie_once = False
    model_set: list = []


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data, cookie=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if Fake.expire_cookie_once:
            Fake.expire_cookie_once = False
            return False
        return "hermes_session_at=ok" in (self.headers.get("Cookie") or "")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def route(self, method):
        path = self.path
        Fake.calls.append(f"{method} {path.split('?')[0]}")
        if method == "POST" and path == "/auth/password-login":
            b = self.body()
            if b == {"provider": "basic", "username": "hermes", "password": "dash-pass"}:
                return self.reply(200, {"ok": True}, "hermes_session_at=ok; Path=/; HttpOnly")
            return self.reply(401, {"detail": "Invalid credentials"})
        if not self.authed():
            return self.reply(401, {"detail": "unauthenticated"})
        if method == "GET" and path == "/api/providers/oauth":
            return self.reply(200, {"providers": [{"id": "openai-codex", "status": {
                "logged_in": Fake.logged_in, "token_preview": TOKEN[-4:]}}]})
        if method == "GET" and path == "/api/model/info":
            return self.reply(200, {"provider": Fake.current, "model": "gpt-6-sol" if Fake.current == "openai-codex" else "opus"})
        if method == "GET" and path.startswith("/api/model/options"):
            return self.reply(200, {"providers": [
                {"slug": "claude-subscription-directsdk-experimental", "is_current": Fake.current != "openai-codex",
                 "authenticated": Fake.current_ok, "models": ["opus"], "featured_models": []},
                {"slug": "openai-codex", "is_current": Fake.current == "openai-codex", "authenticated": Fake.logged_in,
                 "models": ["gpt-6-luna", "gpt-6-sol"] if Fake.logged_in else [], "featured_models": ["gpt-6-sol"] if Fake.logged_in else []}]})
        if method == "POST" and path == "/api/model/set":
            b = self.body()
            Fake.model_set.append(b)
            Fake.current = b["provider"]
            return self.reply(200, {"ok": True})
        if method == "POST" and path == "/api/providers/oauth/openai-codex/start":
            sid = f"s{len(Fake.sessions)}"
            Fake.sessions[sid] = "pending"
            return self.reply(200, {"session_id": sid, "flow": "device_code", "user_code": "ABCD-1234",
                                    "verification_url": "https://auth.openai.com/codex/device", "expires_in": 900})
        if method == "GET" and path.startswith("/api/providers/oauth/openai-codex/poll/"):
            sid = path.rsplit("/", 1)[1]
            if sid not in Fake.sessions:
                return self.reply(404, {"detail": "Session not found or expired"})
            return self.reply(200, {"session_id": sid, "status": Fake.sessions[sid]})
        if method == "DELETE" and path.startswith("/api/providers/oauth/sessions/"):
            Fake.sessions.pop(path.rsplit("/", 1)[1], None)
            return self.reply(200, {"ok": True})
        if method == "DELETE" and path == "/api/providers/oauth/openai-codex":
            Fake.logged_in = False
            return self.reply(200, {"ok": True, "provider": "openai-codex"})
        return self.reply(404, {"detail": "no route"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    port = free_port()
    work = tempfile.mkdtemp()
    env = {"PATH": os.environ["PATH"], "AI_ACCOUNTS_PORT": str(port), "AI_ACCOUNTS_BIND": "127.0.0.1",
           "AI_ACCOUNTS_CLAUDE_DIR": work, "AI_ACCOUNTS_WORK_DIR": work, "AI_ACCOUNTS_CLAUDE": "/nonexistent",
           "AI_ACCOUNTS_HERMES_URL": f"http://127.0.0.1:{stub.server_port}",
           "AI_ACCOUNTS_HERMES_USER": "hermes", "AI_ACCOUNTS_HERMES_PASSWORD": "dash-pass"}
    proc = subprocess.Popen([sys.executable, str(HERE / "server.py")], env=env)
    base = f"http://127.0.0.1:{port}"
    seen = []

    def req(path, body=None):
        r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(r, timeout=30) as res:
                raw = res.read()
                code = res.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        seen.append(raw.decode())
        return code, json.loads(raw)

    def chatgpt():
        return next(a for a in req("/api/accounts")[1]["accounts"] if a["id"] == "chatgpt-subscription")

    try:
        for _ in range(100):
            try:
                req("/health")
                break
            except OSError:
                time.sleep(0.1)
        ids = [a["id"] for a in req("/api/accounts")[1]["accounts"]]
        assert ids == ["claude-subscription", "chatgpt-subscription", "api-keys"], ids
        assert chatgpt()["status"] == "not_connected"

        # Use before connecting is refused.
        code, d = req("/api/chatgpt/use", {})
        assert code == 409 and not Fake.model_set, (code, d)

        # Connect -> code + OpenAI link; a stale handle is refused; Hermes' session id never leaves the server.
        code, d = req("/api/chatgpt/connect", {})
        assert code == 200 and d["code"] == "ABCD-1234" and d["url"] == "https://auth.openai.com/codex/device", d
        assert "session_id" not in d and "s0" not in json.dumps(d), d
        assert chatgpt()["signing_in"] is True
        assert req("/api/chatgpt/poll", {"login_id": "stale"})[0] == 409
        code, d2 = req("/api/chatgpt/poll", {"login_id": d["login_id"]})
        assert code == 200 and d2["status"] == "pending", d2

        # The dashboard session expires mid-way: the app signs in again and carries on.
        Fake.expire_cookie_once = True
        assert req("/api/chatgpt/poll", {"login_id": d["login_id"]})[1]["status"] == "pending"

        # Approved while the agent's Claude account works: connected, NOT switched.
        Fake.sessions["s0"], Fake.logged_in = "approved", True
        code, d3 = req("/api/chatgpt/poll", {"login_id": d["login_id"]})
        assert code == 200 and d3["status"] == "approved" and "keeps its current account" in d3["message"], d3
        assert not Fake.model_set and Fake.current != "openai-codex"
        c = chatgpt()
        assert c["status"] == "connected" and c["in_use"] is False and not c["signing_in"], c

        # Use ChatGPT switches the main model to the first featured ChatGPT model.
        code, d4 = req("/api/chatgpt/use", {})
        assert code == 200 and d4["ok"], d4
        assert Fake.model_set[-1] == {"scope": "main", "provider": "openai-codex", "model": "gpt-6-sol",
                                      "confirm_expensive_model": True}, Fake.model_set
        assert chatgpt()["in_use"] is True

        # Disconnect: signed out, and the owner is told the agent was using it.
        code, d5 = req("/api/chatgpt/logout", {})
        assert code == 200 and d5["chatgpt"]["status"] == "not_connected" and "was using ChatGPT" in d5["message"], d5

        # A fresh agent with no working account: approving switches it automatically.
        Fake.current, Fake.current_ok, Fake.model_set = "claude-subscription-directsdk-experimental", False, []
        d = req("/api/chatgpt/connect", {})[1]
        sid = max(Fake.sessions)
        Fake.sessions[sid], Fake.logged_in = "approved", True
        d6 = req("/api/chatgpt/poll", {"login_id": d["login_id"]})[1]
        assert "now uses ChatGPT" in d6["message"] and Fake.current == "openai-codex", d6

        # Cancel ends Hermes' own session too.
        Fake.logged_in = False
        d = req("/api/chatgpt/connect", {})[1]
        sid = max(Fake.sessions)
        assert req("/api/chatgpt/cancel", {})[1]["ok"] and sid not in Fake.sessions
        assert req("/api/chatgpt/poll", {"login_id": d["login_id"]})[0] == 409

        # Expired code: a clear message, nothing switched.
        Fake.current, Fake.model_set = "claude-subscription-directsdk-experimental", []
        d = req("/api/chatgpt/connect", {})[1]
        Fake.sessions[max(Fake.sessions)] = "expired"
        code, d7 = req("/api/chatgpt/poll", {"login_id": d["login_id"]})
        assert code == 400 and "expired" in d7["message"] and not Fake.model_set, d7

        # Cross-site posts are refused like the Claude routes.
        r = urllib.request.Request(base + "/api/chatgpt/use", data=b"{}",
                                   headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        try:
            urllib.request.urlopen(r, timeout=10)
            raise AssertionError("cross-site post accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # Nothing the browser saw carries a token, the dashboard password or a Hermes session id.
        everything = "\n".join(seen)
        for secret in (TOKEN, TOKEN[-4:], "dash-pass", "hermes_session_at"):
            assert secret not in everything, secret
        assert "/auth/password-login" in " ".join(Fake.calls)
        print(json.dumps({"ok": True, "hermes_calls": len(Fake.calls), "browser_responses": len(seen)}))
    finally:
        proc.terminate()
        proc.wait(10)
        stub.shutdown()


def no_hermes():
    """Without the Hermes Agent dashboard login, the ChatGPT row says what it needs and nothing is called."""
    port = free_port()
    work = tempfile.mkdtemp()
    env = {"PATH": os.environ["PATH"], "AI_ACCOUNTS_PORT": str(port), "AI_ACCOUNTS_BIND": "127.0.0.1",
           "AI_ACCOUNTS_CLAUDE_DIR": work, "AI_ACCOUNTS_WORK_DIR": work, "AI_ACCOUNTS_CLAUDE": "/nonexistent"}
    proc = subprocess.Popen([sys.executable, str(HERE / "server.py")], env=env)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/accounts", timeout=5) as r:
                    rows = json.loads(r.read())["accounts"]
                break
            except OSError:
                time.sleep(0.1)
        row = next(a for a in rows if a["id"] == "chatgpt-subscription")
        assert row["status"] == "unavailable" and "Hermes Agent" in row["detail"], row
    finally:
        proc.terminate()
        proc.wait(10)


if __name__ == "__main__":
    main()
    no_hermes()
