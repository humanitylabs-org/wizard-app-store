"""wizard.ai-connection/1 for Claude: sign-in state, plan and usage limits, never a token.

Reads this app's own Claude Code login (`<dir>/.credentials.json` -> `claudeAiOauth`) only to call
Anthropic's usage endpoint. It never refreshes the token: Claude Code refresh tokens are single-use,
so a refresh here would sign out every agent sharing the login. An expired token is reported as
`expired`; the official CLI renews it the next time it runs (the page's Test button, or an agent).

The limit/paid/plan normalization is a line-for-line port of wizard-agent-service
`server/ai-usage.mjs` (claudePlan, claudeLimitLabel, claudeLimits, claudePaid, usageRow), so the rows
are exactly what `GET /wizard/ai-usage` already returns and the shell needs no change.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

CONTRACT = "wizard.ai-connection/1"
IDENTITY = {"provider": "claude", "name": "Claude"}
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_S = 60
STALE_LIMIT_S = 30 * 60
TIMEOUT_S = 8
MAX_RESPONSE_BYTES = 256 * 1024

SIGNED_OUT, EXPIRED, UNREACHABLE, PROVIDER_ERROR = "signed_out", "expired", "unreachable", "provider_error"
STALE_ELIGIBLE = {UNREACHABLE, PROVIDER_ERROR}
MESSAGES = {
    SIGNED_OUT: "Claude is not signed in. Open the Claude app and press Connect.",
    EXPIRED: "The Claude sign-in has expired. Open the Claude app and press Test (Claude Code renews it), "
             "or Connect again.",
    UNREACHABLE: "Couldn't reach Claude.",
    PROVIDER_ERROR: "Claude's usage service returned an error.",
}


class UsageError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---- JavaScript semantics the port depends on ----------------------------------------------------

def is_finite_number(value) -> bool:  # typeof value === 'number' && Number.isFinite(value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def js_round(value: float) -> int:  # Math.round: halves round up, toward +Infinity
    return math.floor(value + 0.5)


def js_str(value) -> str:  # String(value ?? '')
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return "[object Object]" if isinstance(value, dict) else ",".join(js_str(v) for v in value)
    return str(value)


def js_truthy(value) -> bool:  # JavaScript truthiness: {} and [] are truthy, 0/''/NaN/None are not
    if isinstance(value, (dict, list)):
        return True
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


def get(obj, key):  # obj?.[key]
    return obj.get(key) if isinstance(obj, dict) else None


def iso_ms(dt: datetime) -> str:  # Date.prototype.toISOString
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---- ported from ai-usage.mjs ---------------------------------------------------------------------

def clamp_percent(value):
    if not is_finite_number(value):
        return None
    return min(100, max(0, value))


def iso_time(value):
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:  # Date.parse reads a zone-less date-time as local; the box runs UTC
            parsed = parsed.replace(tzinfo=timezone.utc)
        return iso_ms(parsed)
    if is_finite_number(value) and value > 0:  # epoch seconds
        try:
            return iso_ms(datetime.fromtimestamp(value, timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    return None


def title_from_slug(value) -> str:
    cleaned = js_str(value).replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return ""
    return " ".join(word[0].upper() + word[1:] for word in cleaned.split())


def usage_row(id_, label, used_percent, resets_at):
    used = clamp_percent(used_percent)
    if used is None:
        return None
    tenths = js_round(used * 10)
    used_out = tenths // 10 if tenths % 10 == 0 else tenths / 10  # 40, not 40.0, as JSON.stringify writes it
    return {"id": id_, "label": label, "usedPercent": used_out,
            "remainingPercent": math.floor(100 - used), "resetsAt": iso_time(resets_at)}


CLAUDE_TIERS = {"default_claude_max_20x": "Max 20x", "default_claude_max_5x": "Max 5x", "default_claude_pro": "Pro"}
CLAUDE_SUBSCRIPTIONS = {"max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise", "free": "Free"}
CLAUDE_LEGACY_WINDOWS = [("five_hour", "Session"), ("seven_day", "All models · weekly"),
                         ("seven_day_opus", "Opus · weekly"), ("seven_day_sonnet", "Sonnet · weekly")]


def claude_plan(credentials):
    tier = js_str(get(credentials, "rateLimitTier")).strip()
    if tier in CLAUDE_TIERS:
        return CLAUDE_TIERS[tier]
    return CLAUDE_SUBSCRIPTIONS.get(js_str(get(credentials, "subscriptionType")).strip().lower())


def claude_limit_label(entry, model: str) -> str:
    kind = js_str(get(entry, "kind")).strip()
    if kind == "session":
        return f"{model} · session" if model else "Session"
    if kind == "weekly_all":
        return "All models · weekly"
    if kind == "weekly_scoped":
        return f"{model} · weekly" if model else "Scoped · weekly"
    return model or title_from_slug(kind) or title_from_slug(get(entry, "group")) or "Limit"


def claude_limits(payload) -> list:
    labelled = get(payload, "limits")
    labelled = labelled if isinstance(labelled, list) else []
    rows = []
    for index, entry in enumerate(labelled):
        if not isinstance(entry, (dict, list)):
            continue
        model = js_str(get(get(get(entry, "scope"), "model"), "display_name")).strip()[:40]
        kind = js_str(get(entry, "kind")).strip()[:40]
        group = get(entry, "group")
        tail = model or (js_str(group) if js_truthy(group) else "") or str(index)
        row = usage_row(f"{kind or 'limit'}:{tail}", claude_limit_label(entry, model), get(entry, "percent"),
                        get(entry, "resets_at"))
        if row:
            rows.append(row)
    if rows:
        return rows
    for key, label in CLAUDE_LEGACY_WINDOWS:
        window = get(payload, key)
        if not isinstance(window, (dict, list)):
            continue
        row = usage_row(key, label, get(window, "utilization"), get(window, "resets_at"))
        if row:
            rows.append(row)
    return rows


def _first(*values):  # a ?? b ?? c
    for value in values:
        if value is not None:
            return value
    return None


def claude_paid(payload):
    spend = get(payload, "spend")
    if isinstance(spend, dict):
        used_minor = get(get(spend, "used"), "amount_minor")
        limit_minor = get(get(spend, "limit"), "amount_minor")
        if is_finite_number(used_minor) or is_finite_number(limit_minor):
            exponent = get(get(spend, "limit"), "exponent")
            return {
                "type": "spend",
                "enabled": spend.get("enabled") is True,
                "currency": js_str(_first(get(get(spend, "limit"), "currency"), get(get(spend, "used"), "currency"),
                                          "USD"))[:8],
                "exponent": exponent if is_finite_number(exponent) else 2,
                "usedMinor": js_round(used_minor) if is_finite_number(used_minor) else None,
                "limitMinor": js_round(limit_minor) if is_finite_number(limit_minor) else None,
                "balanceMinor": None,
                "unlimited": False,
            }
    extra = get(payload, "extra_usage")
    if isinstance(extra, dict) and (is_finite_number(extra.get("used_credits")) or is_finite_number(extra.get("monthly_limit"))):
        decimals = extra.get("decimal_places")
        return {
            "type": "spend",
            "enabled": extra.get("is_enabled") is True,
            "currency": js_str(_first(extra.get("currency"), "USD"))[:8],
            "exponent": decimals if is_finite_number(decimals) else 2,
            "usedMinor": js_round(extra["used_credits"]) if is_finite_number(extra.get("used_credits")) else None,
            "limitMinor": js_round(extra["monthly_limit"]) if is_finite_number(extra.get("monthly_limit")) else None,
            "balanceMinor": None,
            "unlimited": False,
        }
    return None


# ---- the reader --------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # fetch(..., {redirect: 'error'})
        raise UsageError(UNREACHABLE)


def read_json(path: str):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read(1 << 20))
    except (OSError, ValueError):
        return None


def get_usage(url: str, token: str, timeout: float) -> dict:
    """GET the usage payload. Errors carry only a code: never the token, URL query or response body."""
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            raw = res.read(MAX_RESPONSE_BYTES + 1)
    except UsageError:
        raise
    except urllib.error.HTTPError as e:
        raise UsageError(EXPIRED if e.code in (401, 403) else PROVIDER_ERROR) from None
    except (OSError, ValueError):  # URLError, timeouts, resets
        raise UsageError(UNREACHABLE) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UsageError(PROVIDER_ERROR)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise UsageError(PROVIDER_ERROR) from None
    return payload if payload is not None else {}


class ConnectionReader:
    """GET /api/connection. Provider reads are cached 60 s; on unreachable/provider_error the last good
    usage is kept for at most 30 min, marked by `error`. A different sign-in drops the cache."""

    def __init__(self, claude_dir: str, usage_url: str = USAGE_URL, now=time.time,
                 cache_s: float = CACHE_S, stale_s: float = STALE_LIMIT_S, timeout_s: float = TIMEOUT_S):
        self.creds_path = claude_dir.rstrip("/") + "/.credentials.json"
        self.account_path = claude_dir.rstrip("/") + "/.claude.json"
        self.usage_url, self.now = usage_url, now
        self.cache_s, self.stale_s, self.timeout_s = cache_s, stale_s, timeout_s
        self.lock = threading.Lock()
        self.login = ""  # sha256 of the token in use; only ever compared, never shown
        self.at = 0.0
        self.result: dict | None = None
        self.last_good: dict | None = None
        self.last_good_at = 0.0

    def account(self) -> str | None:
        acct = get(read_json(self.account_path), "oauthAccount")
        label = js_str(get(acct, "emailAddress") or get(acct, "organizationName")).strip()[:120]
        return label or None

    def base(self, status, plan=None, account=None, usage=None, error=None) -> dict:
        return {"contract": CONTRACT, **IDENTITY, "status": status, "plan": plan, "account": account,
                "usage": usage, "error": {"code": error, "message": MESSAGES[error]} if error else None}

    def read(self) -> dict:
        creds = get(read_json(self.creds_path), "claudeAiOauth")
        token = creds.get("accessToken").strip() if isinstance(get(creds, "accessToken"), str) else ""
        if not token:
            with self.lock:
                self.login, self.result, self.last_good = "", None, None
            return self.base("not_connected", error=SIGNED_OUT)
        plan, account = claude_plan(creds), self.account()
        expires = creds.get("expiresAt")
        now = self.now()
        if is_finite_number(expires) and expires <= now * 1000:
            return self.base("expired", plan, account, error=EXPIRED)
        login = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:  # one provider request at a time; concurrent callers share its result
            if login != self.login:
                self.login, self.result, self.last_good, self.at = login, None, None, 0.0
            if self.result is None or now - self.at >= self.cache_s:
                self.result = self._attempt(token, now)
                self.at = now
            result = dict(self.result)
        result["plan"], result["account"] = plan, account
        return result

    def _attempt(self, token: str, now: float) -> dict:
        try:
            payload = get_usage(self.usage_url, token, self.timeout_s)
        except UsageError as e:
            code = e.code
        except Exception:  # noqa: BLE001 - nothing about the failure may leak into the answer
            code = UNREACHABLE
        else:
            usage = {"fetchedAt": iso_ms(datetime.fromtimestamp(now, timezone.utc)),
                     "limits": claude_limits(payload), "paid": claude_paid(payload)}
            self.last_good, self.last_good_at = usage, now
            return self.base("connected", usage=usage)
        if code == EXPIRED:
            self.last_good = None
            return self.base("expired", error=EXPIRED)
        if code in STALE_ELIGIBLE and self.last_good is not None and now - self.last_good_at <= self.stale_s:
            return self.base("connected", usage=self.last_good, error=code)
        self.last_good = None
        return self.base("error", error=code)
