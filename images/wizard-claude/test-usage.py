"""Unit tests for usage.py (wizard.ai-connection/1) against a stand-in Anthropic usage server.

Stdlib only; runs on the host or in CI before the image is published:
    python3 images/wizard-claude/test-usage.py
Covers the ported normalization (current and legacy payloads, spend and extra_usage), signed out,
expired (local expiresAt and a 401), the 60 s cache, last-good kept for 30 min on outages, a new
sign-in dropping the cache, headers sent, the never-refresh rule, and that no token reaches any
answer. The expected rows were produced by wizard-agent-service server/ai-usage.mjs itself.
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usage  # noqa: E402
import inference

TOKEN = "sk-ant-oat01-TEST-ACCESS-TOKEN-should-never-leak"
REFRESH = "sk-ant-ort01-TEST-REFRESH-TOKEN-should-never-leak"
NOW = 1_792_000_000.0  # fixed clock (seconds)

CURRENT = {
    "limits": [
        {"kind": "session", "group": "five_hour", "percent": 12.345, "resets_at": "2026-10-15T18:00:00+00:00"},
        {"kind": "weekly_all", "group": "seven_day", "percent": 40, "resets_at": "2026-10-20T07:00:00Z"},
        {"kind": "weekly_scoped", "scope": {"model": {"display_name": "Opus"}}, "percent": 99.96, "resets_at": None},
        {"kind": "weekly_scoped", "percent": -5},
        {"kind": "new_kind_x", "percent": 130, "resets_at": 1792100000},
        {"group": "mystery_group", "percent": 1},
        {"kind": "session", "percent": "50"},
        None,
        {"percent": 0.05},
    ],
    "spend": {"enabled": True, "used": {"amount_minor": 1234.5, "currency": "EUR"},
              "limit": {"amount_minor": 5000, "currency": "USD", "exponent": 2}},
    "five_hour": {"utilization": 77},
}
LEGACY = {
    "five_hour": {"utilization": 8.0, "resets_at": "2026-10-15T18:00:00.123456+00:00"},
    "seven_day": {"utilization": 33.33, "resets_at": "2026-10-20T07:00:00Z"},
    "seven_day_opus": None,
    "seven_day_sonnet": {"utilization": None},
    "extra_usage": {"is_enabled": False, "monthly_limit": 10000, "used_credits": 250, "decimal_places": 2},
}
# Produced by running ai-usage.mjs's claudeLimits/claudePaid on the payloads above (node 22).
EXPECTED_CURRENT_LIMITS = [
    {"id": "session:five_hour", "label": "Session", "usedPercent": 12.3, "remainingPercent": 87, "resetsAt": "2026-10-15T18:00:00.000Z"},
    {"id": "weekly_all:seven_day", "label": "All models · weekly", "usedPercent": 40, "remainingPercent": 60, "resetsAt": "2026-10-20T07:00:00.000Z"},
    {"id": "weekly_scoped:Opus", "label": "Opus · weekly", "usedPercent": 100, "remainingPercent": 0, "resetsAt": None},
    {"id": "weekly_scoped:3", "label": "Scoped · weekly", "usedPercent": 0, "remainingPercent": 100, "resetsAt": None},
    {"id": "new_kind_x:4", "label": "New Kind X", "usedPercent": 100, "remainingPercent": 0, "resetsAt": "2026-10-15T21:33:20.000Z"},
    {"id": "limit:mystery_group", "label": "Mystery Group", "usedPercent": 1, "remainingPercent": 99, "resetsAt": None},
    {"id": "limit:8", "label": "Limit", "usedPercent": 0.1, "remainingPercent": 99, "resetsAt": None},
]
EXPECTED_CURRENT_PAID = {"type": "spend", "enabled": True, "currency": "USD", "exponent": 2, "usedMinor": 1235,
                         "limitMinor": 5000, "balanceMinor": None, "unlimited": False}
EXPECTED_LEGACY_LIMITS = [
    {"id": "five_hour", "label": "Session", "usedPercent": 8, "remainingPercent": 92, "resetsAt": "2026-10-15T18:00:00.123Z"},
    {"id": "seven_day", "label": "All models · weekly", "usedPercent": 33.3, "remainingPercent": 66, "resetsAt": "2026-10-20T07:00:00.000Z"},
]
EXPECTED_LEGACY_PAID = {"type": "spend", "enabled": False, "currency": "USD", "exponent": 2, "usedMinor": 250,
                        "limitMinor": 10000, "balanceMinor": None, "unlimited": False}


class Upstream:
    mode = "ok"  # ok | 401 | 500 | down | garbage | redirect
    payload = CURRENT
    hits = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        Upstream.hits.append({k.lower(): v for k, v in self.headers.items()} | {"path": self.path})
        if Upstream.mode == "down":
            self.connection.close()
            return
        if Upstream.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/x")
            self.end_headers()
            return
        code = {"401": 401, "500": 500}.get(Upstream.mode, 200)
        body = b"not json" if Upstream.mode == "garbage" else json.dumps(
            Upstream.payload if code == 200 else {"error": {"message": "bad " + TOKEN}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/api/oauth/usage" % srv.server_address[1]
    d = tempfile.mkdtemp()
    creds_path = os.path.join(d, ".credentials.json")
    clock = [NOW]

    def write_creds(token=TOKEN, expires=(NOW + 3600) * 1000, tier="default_claude_max_20x", sub="max"):
        with open(creds_path, "w") as f:
            json.dump({"claudeAiOauth": {"accessToken": token, "refreshToken": REFRESH, "expiresAt": expires,
                                         "scopes": ["user:inference"], "subscriptionType": sub, "rateLimitTier": tier}}, f)
        before = open(creds_path, "rb").read()
        return before

    answers = []

    def read(reader):
        out = reader.read()
        text = json.dumps(out)
        assert TOKEN not in text and REFRESH not in text and "Bearer" not in text, "token leaked"
        assert set(out) == {"contract", "provider", "name", "status", "plan", "account", "usage", "error"}, sorted(out)
        assert out["contract"] == "wizard.ai-connection/1" and out["provider"] == "claude" and out["name"] == "Claude"
        assert out["status"] in ("connected", "not_connected", "expired", "error"), out["status"]
        answers.append(text)
        return out

    def reader():
        return usage.ConnectionReader(d, url, now=lambda: clock[0], timeout_s=2)

    # /2 is additive: catalogue is separate; legacy usage values remain byte-for-byte compatible.
    assert [m["tier"] for m in inference.models()] == ["fast", "standard", "frontier"]
    assert all("web_search" in m["abilities"] for m in inference.models())

    # Normalization: exactly the Agent Service rows.
    assert usage.claude_limits(CURRENT) == EXPECTED_CURRENT_LIMITS, usage.claude_limits(CURRENT)
    assert usage.claude_paid(CURRENT) == EXPECTED_CURRENT_PAID, usage.claude_paid(CURRENT)
    assert usage.claude_limits(LEGACY) == EXPECTED_LEGACY_LIMITS, usage.claude_limits(LEGACY)
    assert usage.claude_paid(LEGACY) == EXPECTED_LEGACY_PAID, usage.claude_paid(LEGACY)
    assert usage.claude_limits({}) == [] and usage.claude_paid({}) is None and usage.claude_limits(None) == []
    assert usage.claude_plan({"rateLimitTier": "default_claude_max_5x"}) == "Max 5x"
    assert usage.claude_plan({"rateLimitTier": "weird", "subscriptionType": " Pro "}) == "Pro"
    assert usage.claude_plan({}) is None

    # Signed out: no credentials file.
    r = reader()
    out = read(r)
    assert out["status"] == "not_connected" and out["usage"] is None and out["error"]["code"] == "signed_out", out
    assert not Upstream.hits

    # Connected: plan, account, rows; the request carries the right headers.
    with open(os.path.join(d, ".claude.json"), "w") as f:
        json.dump({"oauthAccount": {"emailAddress": "owner@example.com", "organizationName": "Org"}}, f)
    before = write_creds()
    out = read(r)
    assert out["status"] == "connected" and out["plan"] == "Max 20x" and out["account"] == "owner@example.com", out
    assert out["usage"]["limits"] == EXPECTED_CURRENT_LIMITS and out["usage"]["paid"] == EXPECTED_CURRENT_PAID
    assert out["usage"]["fetchedAt"] == "2026-10-14T17:46:40.000Z", out["usage"]["fetchedAt"]
    assert out["error"] is None
    h = Upstream.hits[-1]
    assert h["authorization"] == "Bearer " + TOKEN and h["anthropic-beta"] == "oauth-2025-04-20", h
    assert h["accept"] == "application/json" and h["path"] == "/api/oauth/usage"

    # 60 s cache: no second provider call inside the window, one after it.
    n = len(Upstream.hits)
    clock[0] += 59
    read(r)
    assert len(Upstream.hits) == n
    clock[0] += 2
    read(r)
    assert len(Upstream.hits) == n + 1

    # Outage: last good usage kept (error unreachable / provider_error) for at most 30 min, then usage null.
    good_at = clock[0]
    for mode, code in (("down", "unreachable"), ("500", "provider_error"), ("garbage", "provider_error"),
                       ("redirect", "unreachable")):
        Upstream.mode = mode
        clock[0] += 61
        out = read(r)
        assert out["status"] == "connected" and out["error"]["code"] == code, (mode, out)
        assert out["usage"]["limits"] == EXPECTED_CURRENT_LIMITS, out
    Upstream.mode = "down"
    clock[0] = good_at + 30 * 60 + 1
    out = read(r)
    assert out["status"] == "error" and out["usage"] is None and out["error"]["code"] == "unreachable", out

    # Recovery, then a 401: expired, last good dropped, never refreshed (credentials untouched, one GET only).
    Upstream.mode, Upstream.payload = "ok", LEGACY
    clock[0] += 61
    out = read(r)
    assert out["status"] == "connected" and out["usage"]["limits"] == EXPECTED_LEGACY_LIMITS and out["usage"]["paid"] == EXPECTED_LEGACY_PAID
    Upstream.mode = "401"
    clock[0] += 61
    out = read(r)
    assert out["status"] == "expired" and out["usage"] is None and out["error"]["code"] == "expired", out
    Upstream.mode = "down"
    clock[0] += 61
    out = read(r)
    assert out["status"] == "error" and out["usage"] is None, out  # no stale rows after an expiry
    assert all(set(x) - {"path"} <= {"host", "authorization", "accept", "anthropic-beta", "user-agent",
                                      "accept-encoding", "connection"} for x in Upstream.hits)
    assert all(x["path"] == "/api/oauth/usage" for x in Upstream.hits), "only the usage endpoint is called"
    assert open(creds_path, "rb").read() == before, "credentials file must never be rewritten"

    # Expired locally (expiresAt in the past): no provider call at all.
    Upstream.mode = "ok"
    n = len(Upstream.hits)
    write_creds(expires=(clock[0] - 1) * 1000)
    out = read(r)
    assert out["status"] == "expired" and out["plan"] == "Max 20x" and out["usage"] is None, out
    assert len(Upstream.hits) == n

    # A new sign-in drops the old cache straight away.
    Upstream.payload = CURRENT
    write_creds(token=TOKEN + "-2", tier="", sub="pro")
    out = read(r)
    assert out["status"] == "connected" and out["plan"] == "Pro" and out["usage"]["limits"] == EXPECTED_CURRENT_LIMITS
    assert len(Upstream.hits) == n + 1 and Upstream.hits[-1]["authorization"] == "Bearer " + TOKEN + "-2"
    assert all((TOKEN + "-2") not in a for a in answers)

    # Signed out again (logout empties the file): no stale usage.
    with open(creds_path, "w") as f:
        f.write("{}")
    out = read(r)
    assert out["status"] == "not_connected" and out["usage"] is None

    print(json.dumps({"ok": True, "answers": len(answers), "provider_calls": len(Upstream.hits)}))
    srv.shutdown()


if __name__ == "__main__":
    main()
