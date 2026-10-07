"""Relay + client tests. Run: uv run --with cryptography==50.0.2 python -m unittest discover -s tests -v

Covers: browser-JS -> Python HPKE round trip (the exact shipped static files, run in Node),
one-time capability, pickup-once, expiry/cleanup, superseding, limits, token mode,
headers/CSP/SRI, origin and host guards, no plaintext at rest, no identifiers in logs,
client env writing.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import client  # noqa: E402
import server  # noqa: E402

SECRET = "sk-test-" + base64.b32encode(os.urandom(15)).decode().lower()
NODE = shutil.which("node")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LogCapture(io.StringIO):
    pass


class RelayTest(unittest.TestCase):
    env: dict[str, str] = {}

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="secret-drop-test-"))
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.port = free_port()
        cfg = server.Config.from_env({"SECRET_DROP_DATA_DIR": str(self.data), "SECRET_DROP_BIND": "127.0.0.1",
                                      "SECRET_DROP_PORT": str(self.port), **self.env})
        self.configure(cfg)
        self.log = LogCapture()
        self._old_stdout = sys.stdout
        sys.stdout = self.log
        self.srv = server.Server(cfg)
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.relay = f"http://127.0.0.1:{self.port}"
        self.keyfile = self.tmp / "agent" / "agent.key"
        with redirect_stdout(io.StringIO()):
            self.pub = client.keygen(self.keyfile)

    def configure(self, cfg: server.Config) -> None:
        pass

    def tearDown(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        sys.stdout = self._old_stdout
        os.environ.pop("SECRET_DROP_API_TOKEN", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def http(self, method: str, path: str, body: bytes | dict | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw) if raw and resp.getheader("Content-Type", "").startswith("application/json") else raw
        except ValueError:
            payload = raw
        return resp.status, payload, resp

    def create(self, key="EXAMPLE_API_KEY", state_name="req.json", **kw):
        state = self.tmp / "agent" / state_name
        out = client.create(self.relay, self.keyfile, key, kw.get("label", "Example API key"),
                            kw.get("requester", "Test agent"), kw.get("ttl"), state)
        cap = out["request_url"].split("#c=", 1)[1]
        return out, cap, state

    def origin(self):
        return {"Origin": f"http://127.0.0.1:{self.port}"}

    def view(self, cap):
        return self.http("GET", "/api/request", headers={server.CAPABILITY_HEADER: cap})

    def seal(self, view_payload, value: str) -> dict:
        """Seal exactly like the browser: run the shipped static JS in Node."""
        out = json.loads(subprocess.check_output(
            [NODE, str(HERE / "hpke_node.mjs"), view_payload["public_key"], view_payload["info"], value], timeout=30))
        self.assertTrue(out["kemOk"])
        return {"version": 1, "suite": server.SUITE, **out["sealed"][0]}

    def submit(self, cap, envelope, origin=True):
        headers = {server.CAPABILITY_HEADER: cap, **(self.origin() if origin else {})}
        return self.http("POST", "/api/submit", envelope, headers)


@unittest.skipUnless(NODE, "node is required for the browser-crypto round trip")
class EndToEnd(RelayTest):
    def test_full_flow_one_time_pickup_once_and_no_plaintext_at_rest(self):
        out, cap, state = self.create()
        self.assertEqual(out["fingerprint"], self.pub["fingerprint"])
        status, view, _ = self.view(cap)
        self.assertEqual(status, 200)
        self.assertEqual((view["label"], view["key"], view["requester"]), ("Example API key", "EXAMPLE_API_KEY", "Test agent"))
        self.assertEqual(view["fingerprint"], self.pub["fingerprint"])
        self.assertEqual(view["request_id"], hashlib.sha256(cap.encode()).hexdigest())
        self.assertLessEqual(abs(view["expires_in_seconds"] - 7200), 5)
        self.assertNotIn("pickup", json.dumps(view))
        envelope = self.seal(view, SECRET)
        status, body, _ = self.submit(cap, envelope)
        self.assertEqual((status, body["status"]), (200, "submitted"))
        # one-time: the link is spent for viewing and submitting
        self.assertEqual(self.view(cap)[0], 409)
        self.assertEqual(self.submit(cap, envelope)[0], 409)
        self.assertEqual(client.status(state)["status"], "submitted")
        # no plaintext, capability or pickup secret at rest (ciphertext only)
        blob = b"".join(p.read_bytes() for p in self.data.rglob("*") if p.is_file())
        pickup_secret = json.loads(state.read_text())["pickup_secret"]
        for needle in (SECRET, cap, pickup_secret):
            self.assertNotIn(needle.encode(), blob)
        env = self.tmp / "out" / ".env"
        env.parent.mkdir()
        env.write_text("OTHER=keep\nexport EXAMPLE_API_KEY=old\n# comment\nLAST=x")
        os.chmod(env, 0o644)
        state_copy = state.read_bytes()
        result, value = client.pickup(state, None, env, False, None)
        self.assertIsNone(value)
        self.assertEqual(result["value_bytes"], len(SECRET))
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(env.read_text(), f"OTHER=keep\nEXAMPLE_API_KEY='{SECRET}'\n# comment\nLAST=x")
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertFalse(state.exists())
        # pickup once: a second pickup with the same secret gets nothing
        state.write_bytes(state_copy)
        os.chmod(state, 0o600)
        with self.assertRaisesRegex(client.ClientError, "picked_up"):
            client.pickup(state, None, env, False, None)
        self.assertEqual(client.status(state)["status"], "picked_up")
        conn = server.sqlite3.connect(self.data / "secret-drop.sqlite3")
        self.assertIsNone(conn.execute("SELECT ciphertext FROM requests").fetchone()[0])
        conn.close()
        # logs: route class and status only
        log = self.log.getvalue()
        for needle in (SECRET, cap, pickup_secret, view["request_id"], "EXAMPLE_API_KEY"):
            self.assertNotIn(needle, log)
        self.assertRegex(log, r"POST submit 200")

    def test_unicode_and_quotes_round_trip_via_stdout(self):
        _, cap, state = self.create()
        value = "pä$$'w\"rd ${X} \\ end"
        self.assertEqual(self.submit(cap, self.seal(self.view(cap)[1], value))[0], 200)
        _, got = client.pickup(state, None, None, True, None)
        self.assertEqual(got, value)

    def test_ciphertext_is_bound_to_request(self):
        _, cap1, _ = self.create(state_name="a.json")
        _, cap2, state2 = self.create(key="OTHER_TOKEN", state_name="b.json")
        sealed_for_1 = self.seal(self.view(cap1)[1], SECRET)
        # Moving a valid envelope to another request is accepted by the blind relay
        # but must fail authentication at the agent.
        self.assertEqual(self.submit(cap2, sealed_for_1)[0], 200)
        with self.assertRaisesRegex(client.ClientError, "Decryption failed"):
            client.pickup(state2, None, self.tmp / "x.env", False, None)
        self.assertFalse((self.tmp / "x.env").exists())

    def test_cli_stdout_requires_explicit_flag(self):
        _, cap, state = self.create()
        self.submit(cap, self.seal(self.view(cap)[1], SECRET))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = client.main(["pickup", "--state", str(state), "--stdout"])
        self.assertEqual(rc, 2)
        self.assertIn("i-understand", err.getvalue())
        self.assertEqual(client.status(state)["status"], "submitted")  # nothing consumed


class Lifecycle(RelayTest):
    def test_expiry_and_cleanup(self):
        _, cap, state = self.create()
        rid = hashlib.sha256(cap.encode()).hexdigest()
        envelope = {"version": 1, "suite": server.SUITE, "enc": client.b64u(os.urandom(32)), "ct": client.b64u(os.urandom(40))}
        self.assertEqual(self.submit(cap, envelope)[0], 200)
        with self.srv.relay.store.tx() as db:
            db.execute("UPDATE requests SET expires_at=? WHERE id=?", (int(time.time()) - 1, rid))
        self.assertEqual(self.view(cap)[0], 410)
        self.assertEqual(client.status(state)["status"], "expired")
        with self.assertRaisesRegex(client.ClientError, "expired"):
            client.pickup(state, None, self.tmp / "e.env", False, None)
        row = self.srv.relay.store.get(rid)
        self.assertIsNone(row["ciphertext"])
        # tombstones are dropped after TOMBSTONE_SECONDS
        self.srv.relay.store.retire_expired(int(time.time()) + server.TOMBSTONE_SECONDS + 1)
        self.assertIsNone(self.srv.relay.store.get(rid))

    def test_expired_submit_rejected(self):
        _, cap, _ = self.create()
        rid = hashlib.sha256(cap.encode()).hexdigest()
        with self.srv.relay.store.tx() as db:
            db.execute("UPDATE requests SET expires_at=? WHERE id=?", (int(time.time()) - 1, rid))
        envelope = {"version": 1, "suite": server.SUITE, "enc": client.b64u(os.urandom(32)), "ct": client.b64u(os.urandom(40))}
        self.assertEqual(self.submit(cap, envelope)[0], 410)

    def test_superseding_same_agent_key_and_name_only(self):
        _, old_cap, old_state = self.create(state_name="old.json")
        out, new_cap, _ = self.create(state_name="new.json")
        self.assertEqual(out["superseded_older_links"], 1)
        status, body, _ = self.view(old_cap)
        self.assertEqual((status, body["error"]), (410, "superseded"))
        self.assertEqual(client.status(old_state)["status"], "superseded")
        self.assertEqual(self.view(new_cap)[0], 200)
        other = self.tmp / "agent2.key"
        with redirect_stdout(io.StringIO()):
            client.keygen(other)
        out2 = client.create(self.relay, other, "EXAMPLE_API_KEY", "x", "Other agent", None, self.tmp / "o.json")
        self.assertEqual(out2["superseded_older_links"], 0)
        self.assertEqual(self.view(new_cap)[0], 200)

    def test_cancel(self):
        _, cap, state = self.create()
        self.assertEqual(client.cancel(state)["status"], "cancelled")
        self.assertEqual(self.view(cap)[0], 410)

    def test_ttl_bounds_and_default(self):
        out, _, _ = self.create(ttl=300, state_name="max.json")
        self.assertLessEqual(abs(out["expires_at"] - time.time() - 300 * 60), 5)
        for ttl in (301, 4, 0):
            with self.assertRaisesRegex(client.ClientError, "bad_ttl"):
                self.create(ttl=ttl, state_name=f"t{ttl}.json")

    def test_restart_keeps_pending_requests(self):
        _, cap, state = self.create()
        self.srv.shutdown()
        self.srv.server_close()
        cfg = server.Config.from_env({"SECRET_DROP_DATA_DIR": str(self.data), "SECRET_DROP_BIND": "127.0.0.1",
                                      "SECRET_DROP_PORT": str(self.port)})
        self.srv = server.Server(cfg)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.assertEqual(self.view(cap)[0], 200)
        self.assertEqual(client.status(state)["status"], "pending")


class Validation(RelayTest):
    def test_create_validation(self):
        pk = self.pub["public_key"]
        base = {"label": "x", "key": "EXAMPLE_API_KEY", "requester": "a", "public_key": pk}
        cases = [
            ({**base, "key": "PATH"}, "bad_key"), ({**base, "key": "LD_PRELOAD_TOKEN"}, "bad_key"),
            ({**base, "key": "example_api_key"}, "bad_key"), ({**base, "key": "EXAMPLE"}, "bad_key"),
            ({**base, "label": ""}, "bad_label"), ({**base, "label": "x" * 161}, "bad_label"),
            ({**base, "requester": "a\u202eb"}, "bad_requester"),
            ({**base, "public_key": client.b64u(bytes(32))}, "bad_public_key"),
            ({**base, "public_key": client.b64u(os.urandom(31))}, "bad_encoding"),
            ({**base, "public_key": pk + "="}, "bad_encoding"),
            ({**base, "extra": 1}, "unknown_field"), ({**base, "ttl_minutes": "60"}, "bad_ttl"),
        ]
        for body, code in cases:
            status, payload, _ = self.http("POST", "/api/v1/requests", body)
            self.assertEqual((status, payload["error"]), (400, code), body)
        self.assertEqual(self.http("POST", "/api/v1/requests", b"x" * 5000, {"Content-Type": "application/json"})[0], 413)
        self.assertEqual(self.http("POST", "/api/v1/requests", json.dumps(base).encode(), {"Content-Type": "text/plain"})[0], 415)

    def test_submit_requires_strict_encrypted_envelope(self):
        _, cap, state = self.create()
        good = {"version": 1, "suite": server.SUITE, "enc": client.b64u(os.urandom(32)), "ct": client.b64u(os.urandom(40))}
        bad = [{"value": SECRET}, {**good, "value": SECRET}, {**good, "version": 2}, {**good, "suite": "RSA"},
               {**good, "enc": client.b64u(os.urandom(31))}, {**good, "ct": client.b64u(os.urandom(16))},
               {**good, "ct": client.b64u(os.urandom(server.MAX_CIPHERTEXT_BYTES + 1))}]
        for body in bad:
            status, _, _ = self.submit(cap, body)
            self.assertIn(status, (400, 413), body)
        self.assertEqual(self.http("POST", "/api/submit", b"{" + b" " * server.MAX_SUBMIT_BODY + b"}",
                                   {server.CAPABILITY_HEADER: cap, "Content-Type": "application/json", **self.origin()})[0], 413)
        self.assertEqual(client.status(state)["status"], "pending")  # nothing consumed
        self.assertNotIn(SECRET.encode(), b"".join(p.read_bytes() for p in self.data.rglob("*") if p.is_file()))

    def test_origin_enforced_before_consumption(self):
        _, cap, state = self.create()
        good = {"version": 1, "suite": server.SUITE, "enc": client.b64u(os.urandom(32)), "ct": client.b64u(os.urandom(40))}
        self.assertEqual(self.submit(cap, good, origin=False)[0], 403)
        for origin in ("http://evil.example", "null", f"http://127.0.0.1:{self.port}/x"):
            self.assertEqual(self.http("POST", "/api/submit", good, {server.CAPABILITY_HEADER: cap, "Origin": origin})[0], 403)
        self.assertEqual(self.http("POST", "/api/submit", good, {server.CAPABILITY_HEADER: cap, **self.origin(),
                                                                 "Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.http("GET", "/api/request", headers={server.CAPABILITY_HEADER: cap, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.http("OPTIONS", "/api/submit")[0], 405)
        self.assertEqual(client.status(state)["status"], "pending")

    def test_dns_rebinding_host_guard(self):
        self.assertEqual(self.http("GET", "/health", headers={"Host": "attacker.example"})[0], 421)
        self.assertEqual(self.http("GET", "/health", headers={"Host": "secret-drop"})[0], 200)
        self.assertEqual(self.http("GET", "/health", headers={"Host": "demobox.tail1234.ts.net:8792"})[0], 200)
        self.assertEqual(self.http("GET", "/health", headers={"Host": "100.72.13.24:8792"})[0], 200)

    def test_bad_capability_and_pickup_secrets(self):
        _, cap, state = self.create()
        self.assertEqual(self.view("A" * 43)[0], 404)
        self.assertEqual(self.view(cap + "x")[0], 404)
        self.assertEqual(self.http("GET", "/api/request", headers={server.CAPABILITY_HEADER: cap, "x": "1"})[0], 200)
        rid = hashlib.sha256(cap.encode()).hexdigest()
        self.assertEqual(self.http("GET", f"/api/v1/requests/{rid}", headers={server.PICKUP_HEADER: "B" * 43})[0], 404)
        self.assertEqual(self.http("GET", f"/api/v1/requests/{rid}")[0], 404)
        self.assertEqual(self.http("POST", f"/api/v1/requests/{rid}/pickup", {}, {server.PICKUP_HEADER: "B" * 43})[0], 404)
        # the capability is not the pickup secret
        self.assertEqual(self.http("GET", f"/api/v1/requests/{rid}", headers={server.PICKUP_HEADER: cap})[0], 404)

    def test_headers_csp_and_sri(self):
        status, page, resp = self.http("GET", "/")
        self.assertEqual(status, 200)
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe", csp)
        for header, value in (("Cache-Control", "no-store, max-age=0"), ("Referrer-Policy", "no-referrer"),
                              ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY")):
            self.assertEqual(resp.getheader(header), value)
        html = page.decode()
        self.assertNotRegex(html, r"https?://(?!www\.w3\.org)")  # no external resources
        self.assertNotIn("<script>", html)
        for name in ("noble-crypto.js", "hpke.js", "app.js", "app.css"):
            body = self.http("GET", "/static/" + name)[1]
            sri = "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode()
            self.assertIn(f'integrity="{sri}"', html)
        for path in ("/health", "/api/v1/info", "/client.py", "/SKILL.md", "/nope"):
            self.assertEqual(self.http("GET", path)[2].getheader("Content-Security-Policy"), csp)
        self.assertNotRegex(Path(ROOT / "static/app.js").read_text(), r"innerHTML|eval\(|new Function|crypto\.subtle")
        self.assertNotRegex(Path(ROOT / "static/hpke.js").read_text(), r"subtle\.(encrypt|deriveBits|importKey|generateKey)")

    def test_serves_client_and_skill_verbatim(self):
        _, body, resp = self.http("GET", "/client.py")
        self.assertEqual(body, (ROOT / "client.py").read_bytes())
        self.assertEqual(resp.getheader("X-Content-SHA256"), hashlib.sha256(body).hexdigest())
        self.assertEqual(self.http("GET", "/SKILL.md")[1], (ROOT / "SKILL.md").read_bytes())
        info = self.http("GET", "/api/v1/info")[1]
        self.assertEqual(info["client_sha256"], hashlib.sha256(body).hexdigest())
        self.assertFalse(info["token_required"])

    def test_vendored_bundle_pins(self):
        bundle = (ROOT / "static/noble-crypto.js").read_text()
        lock = json.loads((ROOT / "vendor/package-lock.json").read_text())
        for name in ("@noble/ciphers", "@noble/curves", "@noble/hashes"):
            entry = lock["packages"][f"node_modules/{name}"]
            self.assertIn(f"{name}@{entry['version']} {entry['integrity']}", bundle)
        pkg = json.loads((ROOT / "vendor/package.json").read_text())
        for version in {**pkg["dependencies"], **pkg["devDependencies"]}.values():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertNotIn("require(", bundle)


class Limits(RelayTest):
    def configure(self, cfg):
        cfg.max_active = 3
        cfg.rate_limits = {"create": (5, 600), "submit": (2, 600), "view": (100, 600), "agent": (100, 600)}

    def test_max_active(self):
        for i in range(3):
            self.create(key=f"K{i}_TOKEN", state_name=f"{i}.json")
        with self.assertRaisesRegex(client.ClientError, "too_many_active"):
            self.create(key="K9_TOKEN", state_name="9.json")

    def test_rate_limits(self):
        good = {"version": 1, "suite": server.SUITE, "enc": client.b64u(os.urandom(32)), "ct": client.b64u(os.urandom(40))}
        for _ in range(2):
            self.assertEqual(self.submit("A" * 43, good)[0], 404)
        self.assertEqual(self.submit("A" * 43, good)[0], 429)
        body = {"label": "x", "key": "EXAMPLE_API_KEY", "requester": "a", "public_key": "!"}
        codes = [self.http("POST", "/api/v1/requests", body)[0] for _ in range(6)]
        self.assertEqual(codes, [400] * 5 + [429])


class TokenMode(RelayTest):
    TOKEN = "t" * 40
    env = {"SECRET_DROP_API_TOKEN": TOKEN}

    @unittest.skipUnless(NODE, "node required")
    def test_agent_endpoints_need_bearer_human_page_does_not(self):
        with self.assertRaisesRegex(client.ClientError, "unauthorized"):
            self.create(state_name="noauth.json")
        self.assertEqual(self.http("POST", "/api/v1/requests", {}, {"Authorization": "Bearer " + "u" * 40})[0], 401)
        os.environ["SECRET_DROP_API_TOKEN"] = self.TOKEN
        _, cap, state = self.create()
        rid = hashlib.sha256(cap.encode()).hexdigest()
        pickup_secret = json.loads(state.read_text())["pickup_secret"]
        self.assertEqual(self.http("GET", f"/api/v1/requests/{rid}", headers={server.PICKUP_HEADER: pickup_secret})[0], 401)
        status, view, _ = self.view(cap)  # human: capability only
        self.assertEqual(status, 200)
        self.assertEqual(self.submit(cap, self.seal(view, SECRET))[0], 200)
        _, value = client.pickup(state, None, None, True, None)
        self.assertEqual(value, SECRET)
        self.assertTrue(self.http("GET", "/api/v1/info")[1]["token_required"])

    def test_token_format_enforced(self):
        with self.assertRaises(ValueError):
            server.Config.from_env({"SECRET_DROP_API_TOKEN": "short"})


class ClientFiles(unittest.TestCase):
    def test_key_and_env_files_are_private_and_not_overwritten(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            key = tmp / "k" / "agent.key"
            client.keygen(key)
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(client.ClientError, "refusing to overwrite"):
                client.keygen(key)
            os.chmod(key, 0o644)
            with self.assertRaisesRegex(client.ClientError, "chmod 600"):
                client.load_private(key)
            link = tmp / "link.env"
            link.symlink_to(tmp / "real.env")
            with self.assertRaisesRegex(client.ClientError, "symlink"):
                client.atomic_update_env(link, "A_TOKEN", "v")
            env = tmp / "new.env"
            client.atomic_update_env(env, "A_TOKEN", "v1")
            client.atomic_update_env(env, "B_TOKEN", "v2")
            client.atomic_update_env(env, "A_TOKEN", "v3")
            self.assertEqual(env.read_text(), "A_TOKEN='v3'\nB_TOKEN='v2'\n")
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
