#!/usr/bin/env python3
"""Secret Drop relay: one-time, end-to-end-encrypted credential handoff to agents.

An agent registers a request with its own X25519 public key. A human opens a
one-time link, the page encrypts the value to that key (HPKE, RFC 9180) and the
relay stores only ciphertext until the agent picks it up once. The relay never
holds a decryption key, so it never sees plaintext.

Standard library only. UX and security contract adapted from
humanitylabs-org/hermes-tailnet-secret-drop (MIT, Copyright (c) 2026 Humanity Labs).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APP_VERSION = "0.1.1"
SUITE = "HPKE-base/DHKEM-X25519-HKDF-SHA256/HKDF-SHA256/AES-256-GCM"
INFO_PREFIX = "wizard-secret-drop/v1"
DEFAULT_TTL_MINUTES = 120
HARD_MAX_TTL_MINUTES = 300
MIN_TTL_MINUTES = 5
TOMBSTONE_SECONDS = 24 * 3600
CLEANUP_INTERVAL_SECONDS = 30
MAX_VALUE_BYTES = 32 * 1024
# enc (32) + value + GCM tag (16), base64url-expanded, plus a JSON envelope.
MAX_SUBMIT_BODY = 64 * 1024
MAX_CREATE_BODY = 4 * 1024
MAX_CIPHERTEXT_BYTES = MAX_VALUE_BYTES + 16
MAX_CONCURRENT_CONNECTIONS = 64
SOCKET_TIMEOUT_SECONDS = 15
CAPABILITY_HEADER = "X-Secret-Drop-Capability"
PICKUP_HEADER = "X-Secret-Drop-Pickup"
CAPABILITY_RE = re.compile(r"[A-Za-z0-9_-]{43}")
PICKUP_RE = re.compile(r"[A-Za-z0-9_-]{43}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{64}")
B64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
HOST_RE = re.compile(r"(?:[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?")
ENV_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
SECRET_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASS", "_URL", "_URI", "_CREDENTIAL")
DANGEROUS_KEYS = {"BASH_ENV", "ENV", "HOME", "IFS", "PATH", "PROMPT_COMMAND", "PYTHONHOME", "PYTHONPATH", "SHELL", "SHELLOPTS"}
DANGEROUS_PREFIXES = ("LD_", "SUDO_", "SYSTEMD_", "XDG_")
ACTIVE = ("pending", "submitted")
# X25519 points of small order (RFC 7748 / libsodium blocklist), little-endian u-coordinates.
_LOW_ORDER_HEX = (
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800",
    "5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f1157",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)
LOW_ORDER_POINTS = {bytes.fromhex(h) for h in _LOW_ORDER_HEX}

HERE = Path(__file__).resolve().parent


class DropError(Exception):
    """A safe client-facing failure that carries no secret material."""

    def __init__(self, status: int, code: str, message: str, title: str = "Unavailable"):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
        self.title = title


# --------------------------------------------------------------------------- config

def _int_env(env: dict[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass
class Config:
    data_dir: Path = Path("/data")
    bind: str = "0.0.0.0"
    port: int = 8792
    public_url: str = ""
    api_token: str = ""
    allowed_hosts: tuple[str, ...] = ()
    max_active: int = 100
    default_ttl_minutes: int = DEFAULT_TTL_MINUTES
    max_ttl_minutes: int = HARD_MAX_TTL_MINUTES
    # (limit, window seconds) per client IP and class.
    rate_limits: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "create": (30, 600), "submit": (20, 600), "view": (240, 600), "agent": (600, 600),
    })
    static_dir: Path = HERE / "static"
    client_path: Path = HERE / "client.py"
    skill_path: Path = HERE / "SKILL.md"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        token = env.get("SECRET_DROP_API_TOKEN", "").strip()
        if token and not re.fullmatch(r"[A-Za-z0-9._~+/=-]{32,256}", token):
            raise ValueError("SECRET_DROP_API_TOKEN must be 32-256 URL-safe characters (or empty to disable)")
        public_url = env.get("SECRET_DROP_PUBLIC_URL", "").strip().rstrip("/")
        if public_url:
            parsed = urlsplit(public_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment \
                    or not HOST_RE.fullmatch(parsed.netloc):
                raise ValueError("SECRET_DROP_PUBLIC_URL must look like http://100.x.y.z:8792")
        cfg = cls(
            data_dir=Path(env.get("SECRET_DROP_DATA_DIR", "/data")),
            bind=env.get("SECRET_DROP_BIND", "0.0.0.0"),
            port=_int_env(env, "SECRET_DROP_PORT", 8792, 1, 65535),
            public_url=public_url,
            api_token=token,
            allowed_hosts=tuple(h.strip().lower() for h in env.get("SECRET_DROP_ALLOWED_HOSTS", "").split(",") if h.strip()),
            max_active=_int_env(env, "SECRET_DROP_MAX_ACTIVE", 100, 1, 10000),
            max_ttl_minutes=_int_env(env, "SECRET_DROP_MAX_TTL_MINUTES", HARD_MAX_TTL_MINUTES, MIN_TTL_MINUTES, HARD_MAX_TTL_MINUTES),
        )
        cfg.default_ttl_minutes = min(DEFAULT_TTL_MINUTES, cfg.max_ttl_minutes)
        return cfg


# --------------------------------------------------------------------------- helpers

def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(value: Any, *, minimum: int, maximum: int) -> bytes:
    if not isinstance(value, str) or not B64URL_RE.fullmatch(value) or len(value) > (maximum * 4) // 3 + 4:
        raise DropError(400, "bad_encoding", "Malformed encoding.")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        raise DropError(400, "bad_encoding", "Malformed encoding.") from None
    if not minimum <= len(raw) <= maximum or b64u_encode(raw) != value:
        raise DropError(400, "bad_encoding", "Malformed encoding.")
    return raw


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def fingerprint(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).hexdigest()[:16]
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def validate_key_name(key: Any) -> str:
    if not isinstance(key, str):
        raise DropError(400, "bad_key", "key must be a string.")
    key = key.strip()
    if not ENV_KEY_RE.fullmatch(key) or key in DANGEROUS_KEYS or key.startswith(DANGEROUS_PREFIXES):
        raise DropError(400, "bad_key", "The destination key name is not allowed.")
    if not key.endswith(SECRET_SUFFIXES):
        raise DropError(400, "bad_key", "The key must end in " + ", ".join(SECRET_SUFFIXES) + ".")
    return key


def validate_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise DropError(400, f"bad_{name}", f"{name} must be a string.")
    value = " ".join(value.strip().split())
    if not value or len(value) > maximum or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in value) \
            or any(c in value for c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"):
        raise DropError(400, f"bad_{name}", f"{name} must be 1-{maximum} printable characters.")
    return value


def hpke_info(request_id: str, key_name: str) -> str:
    """The HPKE info string binds the ciphertext to one request and one key name."""
    return f"{INFO_PREFIX}|{request_id}|{key_name}"


# --------------------------------------------------------------------------- rate limiting

class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]]):
        self.limits = limits
        self.events: dict[tuple[str, str], list[float]] = {}
        self.lock = threading.Lock()

    def allow(self, cls: str, ip: str) -> bool:
        limit, window = self.limits[cls]
        now = time.monotonic()
        with self.lock:
            if len(self.events) > 20000:  # bounded memory under address churn
                self.events = {k: v for k, v in self.events.items() if v and v[-1] > now - 900}
            bucket = [t for t in self.events.get((cls, ip), []) if t > now - window]
            allowed = len(bucket) < limit
            if allowed:
                bucket.append(now)
            self.events[(cls, ip)] = bucket
            return allowed


# --------------------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,               -- SHA-256(capability), hex; never the capability
  pickup_hash TEXT NOT NULL,         -- SHA-256(pickup secret), hex
  label TEXT NOT NULL,
  key_name TEXT NOT NULL,
  requester TEXT NOT NULL,
  public_key TEXT NOT NULL,          -- agent X25519 public key, base64url
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  status TEXT NOT NULL,              -- pending|submitted|picked_up|expired|superseded|cancelled
  status_at INTEGER NOT NULL,
  ciphertext BLOB                    -- HPKE enc||ct; NULL once retired
);
CREATE INDEX IF NOT EXISTS requests_status ON requests(status, expires_at);
"""


class Store:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "secret-drop.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        for pragma in ("PRAGMA secure_delete=ON", "PRAGMA journal_mode=DELETE", "PRAGMA synchronous=FULL"):
            self.db.execute(pragma)
        self.db.executescript(SCHEMA)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def tx(self):
        return _Tx(self)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def get(self, request_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()

    def retire_expired(self, now: int) -> int:
        with self.tx() as db:
            n = db.execute("UPDATE requests SET status='expired', status_at=?, ciphertext=NULL "
                           "WHERE status IN ('pending','submitted') AND expires_at<=?", (now, now)).rowcount
            db.execute("DELETE FROM requests WHERE status NOT IN ('pending','submitted') AND status_at<=?",
                       (now - TOMBSTONE_SECONDS,))
            return n


class _Tx:
    def __init__(self, store: Store):
        self.store = store

    def __enter__(self) -> sqlite3.Connection:
        self.store.lock.acquire()
        self.store.db.execute("BEGIN IMMEDIATE")
        return self.store.db

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.store.db.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.store.lock.release()


# --------------------------------------------------------------------------- core operations

class Relay:
    def __init__(self, config: Config):
        self.config = config
        self.store = Store(config.data_dir)
        self.limiter = RateLimiter(config.rate_limits)
        self.store.retire_expired(int(time.time()))

    def create(self, payload: Any, base_url: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DropError(400, "bad_json", "Body must be a JSON object.")
        unknown = set(payload) - {"label", "key", "requester", "public_key", "ttl_minutes"}
        if unknown:
            raise DropError(400, "unknown_field", "Unknown field(s): " + ", ".join(sorted(unknown)))
        key = validate_key_name(payload.get("key"))
        label = validate_text(payload.get("label"), "label", 160)
        requester = validate_text(payload.get("requester"), "requester", 80)
        public_key = b64u_decode(payload.get("public_key"), minimum=32, maximum=32)
        if public_key in LOW_ORDER_POINTS:
            raise DropError(400, "bad_public_key", "The public key is not a usable X25519 key.")
        ttl = payload.get("ttl_minutes", self.config.default_ttl_minutes)
        if type(ttl) is not int or not MIN_TTL_MINUTES <= ttl <= self.config.max_ttl_minutes:
            raise DropError(400, "bad_ttl", f"ttl_minutes must be {MIN_TTL_MINUTES}-{self.config.max_ttl_minutes}.")
        capability = secrets.token_urlsafe(32)
        pickup = secrets.token_urlsafe(32)
        request_id = sha256_hex(capability)
        now = int(time.time())
        expires = now + ttl * 60
        with self.store.tx() as db:
            db.execute("UPDATE requests SET status='expired', status_at=?, ciphertext=NULL "
                       "WHERE status IN ('pending','submitted') AND expires_at<=?", (now, now))
            superseded = db.execute(
                "UPDATE requests SET status='superseded', status_at=? "
                "WHERE status='pending' AND public_key=? AND key_name=?", (now, b64u_encode(public_key), key)).rowcount
            active = db.execute("SELECT COUNT(*) FROM requests WHERE status IN ('pending','submitted')").fetchone()[0]
            if active >= self.config.max_active:
                raise DropError(429, "too_many_active", "Too many active requests. Pick up or cancel some first.")
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                       (request_id, sha256_hex(pickup), label, key, requester, b64u_encode(public_key),
                        now, expires, "pending", now))
        return {
            "request_id": request_id,
            "request_url": f"{base_url}/#c={capability}",
            "pickup_secret": pickup,
            "key": key, "label": label, "requester": requester,
            "fingerprint": fingerprint(public_key),
            "suite": SUITE, "info": hpke_info(request_id, key),
            "created_at": now, "expires_at": expires, "superseded": superseded, "status": "pending",
        }

    def _by_capability(self, capability: str | None) -> tuple[str, sqlite3.Row | None]:
        if capability is None:
            return "", None
        request_id = sha256_hex(capability)
        return request_id, self.store.get(request_id)

    def view(self, capability: str | None) -> dict[str, Any]:
        request_id, row = self._by_capability(capability)
        row = self._fresh(row)
        if row is None:
            raise DropError(404, "not_found", "This Secret Drop link is not valid. Ask for a new one.", "Not found")
        self._raise_if_inactive(row, for_human=True)
        public_key = b64u_decode(row["public_key"], minimum=32, maximum=32)
        return {
            "request_id": request_id, "label": row["label"], "key": row["key_name"], "requester": row["requester"],
            "public_key": row["public_key"], "fingerprint": fingerprint(public_key),
            "suite": SUITE, "info": hpke_info(request_id, row["key_name"]),
            "expires_in_seconds": max(0, row["expires_at"] - int(time.time())),
            "max_value_bytes": MAX_VALUE_BYTES,
        }

    def submit(self, capability: str | None, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"version", "suite", "enc", "ct"} \
                or payload.get("version") != 1 or payload.get("suite") != SUITE:
            raise DropError(400, "bad_envelope", "Only an encrypted envelope is accepted. Nothing was stored.", "Not sent")
        enc = b64u_decode(payload["enc"], minimum=32, maximum=32)
        ct = b64u_decode(payload["ct"], minimum=17, maximum=MAX_CIPHERTEXT_BYTES)
        request_id, _ = self._by_capability(capability)
        if not request_id:
            raise DropError(404, "not_found", "This Secret Drop link is not valid.", "Not found")
        now = int(time.time())
        with self.store.tx() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise DropError(404, "not_found", "This Secret Drop link is not valid.", "Not found")
            if row["status"] in ACTIVE and row["expires_at"] <= now:
                db.execute("UPDATE requests SET status='expired', status_at=?, ciphertext=NULL WHERE id=?", (now, request_id))
                raise DropError(410, "expired", "This Secret Drop link has expired. Ask for a new one.", "Expired")
            self._raise_if_inactive(row, for_human=True)
            # Conditional update: exactly one submission can ever win.
            won = db.execute("UPDATE requests SET status='submitted', status_at=?, ciphertext=? "
                             "WHERE id=? AND status='pending'", (now, enc + ct, request_id)).rowcount
            if won != 1:
                raise DropError(409, "used", "This Secret Drop link has already been used. If that was not you, tell the agent that asked so it can discard it and send a new link.", "Already used")
        return {"status": "submitted", "requester": row["requester"]}

    def _fresh(self, row: sqlite3.Row | None) -> sqlite3.Row | None:
        if row is not None and row["status"] in ACTIVE and row["expires_at"] <= int(time.time()):
            self.store.retire_expired(int(time.time()))
            return self.store.get(row["id"])
        return row

    @staticmethod
    def _raise_if_inactive(row: sqlite3.Row, for_human: bool) -> None:
        status = row["status"]
        if status == "pending":
            return
        if status == "expired":
            raise DropError(410, "expired", "This Secret Drop link has expired. Ask for a new one.", "Expired")
        if status == "superseded":
            raise DropError(410, "superseded", "This link was replaced by a newer request. Use the most recent link.", "Replaced")
        if status == "cancelled":
            raise DropError(410, "cancelled", "This request was cancelled by the agent.", "Cancelled")
        if for_human:
            raise DropError(409, "used", "This Secret Drop link has already been used. If that was not you, tell the agent that asked so it can discard it and send a new link.", "Already used")

    def _authorized(self, request_id: str, pickup: str | None) -> sqlite3.Row:
        if not REQUEST_ID_RE.fullmatch(request_id) or pickup is None:
            raise DropError(404, "not_found", "Unknown request or wrong pickup secret.")
        row = self._fresh(self.store.get(request_id))
        expected = row["pickup_hash"] if row is not None else "0" * 64
        if not hmac.compare_digest(sha256_hex(pickup), expected) or row is None:
            raise DropError(404, "not_found", "Unknown request or wrong pickup secret.")
        return row

    @staticmethod
    def public_status(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["id"], "status": row["status"], "key": row["key_name"], "label": row["label"],
            "requester": row["requester"], "created_at": row["created_at"], "expires_at": row["expires_at"],
            "status_at": row["status_at"], "ready": row["status"] == "submitted",
        }

    def status(self, request_id: str, pickup: str | None) -> dict[str, Any]:
        return self.public_status(self._authorized(request_id, pickup))

    def pickup(self, request_id: str, pickup: str | None) -> dict[str, Any]:
        self._authorized(request_id, pickup)
        now = int(time.time())
        with self.store.tx() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None or row["status"] != "submitted" or row["ciphertext"] is None:
                status = row["status"] if row is not None else "gone"
                raise DropError(409, "not_ready" if status == "pending" else status,
                                "Nothing to pick up: request is " + status + ".")
            blob = bytes(row["ciphertext"])
            db.execute("UPDATE requests SET status='picked_up', status_at=?, ciphertext=NULL WHERE id=?", (now, request_id))
        return {"request_id": request_id, "key": row["key_name"], "suite": SUITE,
                "info": hpke_info(request_id, row["key_name"]),
                "enc": b64u_encode(blob[:32]), "ct": b64u_encode(blob[32:]), "status": "picked_up"}

    def cancel(self, request_id: str, pickup: str | None) -> dict[str, Any]:
        self._authorized(request_id, pickup)
        now = int(time.time())
        with self.store.tx() as db:
            db.execute("UPDATE requests SET status='cancelled', status_at=?, ciphertext=NULL "
                       "WHERE id=? AND status IN ('pending','submitted')", (now, request_id))
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        return self.public_status(row)


# --------------------------------------------------------------------------- HTTP

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "form-action 'none'; base-uri 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'")
BASE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-read=(), payment=(), usb=()",
}


def _sri(data: bytes) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")


class Assets:
    def __init__(self, config: Config):
        static = config.static_dir
        self.files: dict[str, tuple[bytes, str]] = {}
        for name, ctype in (("noble-crypto.js", "text/javascript"), ("hpke.js", "text/javascript"),
                            ("app.js", "text/javascript"), ("app.css", "text/css")):
            self.files["/static/" + name] = ((static / name).read_bytes(), ctype + "; charset=utf-8")
        page = (static / "index.html").read_text("utf-8")
        for name in ("noble-crypto.js", "hpke.js", "app.js", "app.css"):
            page = page.replace("{{sri:" + name + "}}", _sri(self.files["/static/" + name][0]))
        page = page.replace("{{version}}", APP_VERSION)
        if "{{" in page:
            raise RuntimeError("unfilled page template")
        self.page = page.encode("utf-8")
        self.client = config.client_path.read_bytes()
        self.skill = config.skill_path.read_bytes()
        self.client_sha256 = hashlib.sha256(self.client).hexdigest()
        self.skill_sha256 = hashlib.sha256(self.skill).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "SecretDrop/" + APP_VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = SOCKET_TIMEOUT_SECONDS

    @property
    def relay(self) -> Relay:
        return self.server.relay  # type: ignore[attr-defined]

    @property
    def assets(self) -> Assets:
        return self.server.assets  # type: ignore[attr-defined]

    # Never log paths, headers or bodies: they can carry identifiers. Route class + status only.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        route = getattr(self, "_route", "other")
        sys.stdout.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {self.command} {route} {code}\n")
        sys.stdout.flush()

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in {**BASE_HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))

    def _error(self, exc: DropError) -> None:
        self._json(exc.status, {"error": exc.code, "message": exc.message, "title": exc.title})

    def _single_header(self, name: str, pattern: re.Pattern[str]) -> str | None:
        values = self.headers.get_all(name) or []
        if len(values) != 1 or not pattern.fullmatch(values[0]):
            return None
        return values[0]

    def _ip(self) -> str:
        return str(self.client_address[0])

    def _limit(self, cls: str) -> None:
        if not self.relay.limiter.allow(cls, self._ip()):
            raise DropError(429, "rate_limited", "Too many attempts. Wait a few minutes and try again.", "Slow down")

    def _read_body(self, maximum: int) -> Any:
        raw_length = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding") or raw_length is None or not raw_length.isdigit():
            self.close_connection = True
            raise DropError(411, "length_required", "Content-Length is required.")
        length = int(raw_length)
        if length > maximum:
            self.close_connection = True
            raise DropError(413, "too_large", "Request body is too large.", "Too large")
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        body = self.rfile.read(length)
        if ctype != "application/json":
            raise DropError(415, "json_required", "Send application/json.")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise DropError(400, "bad_json", "Malformed JSON.") from None

    def _host(self) -> str | None:
        values = self.headers.get_all("Host") or []
        if len(values) != 1 or not HOST_RE.fullmatch(values[0]):
            return None
        return values[0].lower()

    def _host_allowed(self) -> bool:
        """DNS-rebinding guard: a browser page on an attacker domain must not reach this API.

        Accept IP literals, localhost, single-label names (Docker service aliases),
        Tailscale MagicDNS (*.ts.net), the configured public host and SECRET_DROP_ALLOWED_HOSTS.
        """
        host = self._host()
        if host is None:
            return False
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]", 1)[0] + "]"
        if name.startswith("["):
            return True
        if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}", name) or name == "localhost" or "." not in name:
            return True
        if name.endswith(".ts.net"):
            return True
        allowed = set(self.relay.config.allowed_hosts)
        if self.relay.config.public_url:
            allowed.add(urlsplit(self.relay.config.public_url).hostname or "")
        return name in allowed

    def _guard(self) -> bool:
        if self._host_allowed():
            return True
        self._route = "bad_host"
        self.close_connection = True
        self._json(421, {"error": "bad_host", "message": "Unrecognized Host. Add it to SECRET_DROP_ALLOWED_HOSTS.",
                         "title": "Blocked"})
        return False

    def _base_url(self) -> str:
        if self.relay.config.public_url:
            return self.relay.config.public_url
        host = self._host()
        if host is None:
            raise DropError(400, "bad_host", "Missing or invalid Host header; set SECRET_DROP_PUBLIC_URL.")
        return "http://" + host

    def _same_origin(self) -> bool:
        """Browser submissions must come from this page: one Origin equal to our Host."""
        origins = self.headers.get_all("Origin") or []
        if len(origins) != 1:
            return False
        parsed = urlsplit(origins[0].strip())
        if parsed.scheme not in ("http", "https") or parsed.path or parsed.query or parsed.fragment:
            return False
        allowed = set()
        host = self._host()
        if host:
            allowed.add(host)
        if self.relay.config.public_url:
            allowed.add(urlsplit(self.relay.config.public_url).netloc.lower())
        site = self.headers.get("Sec-Fetch-Site")
        return parsed.netloc.lower() in allowed and (site is None or site == "same-origin")

    def _require_agent_token(self) -> None:
        token = self.relay.config.api_token
        if not token:
            return
        values = self.headers.get_all("Authorization") or []
        supplied = values[0] if len(values) == 1 else ""
        if not hmac.compare_digest(supplied.encode("utf-8", "replace"), ("Bearer " + token).encode("utf-8")):
            raise DropError(401, "unauthorized", "This relay requires Authorization: Bearer <SECRET_DROP_API_TOKEN>.")

    # ------------------------------------------------------------------ routes

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        try:
            if path == "/":
                self._route = "page"
                self._send(200, self.assets.page, "text/html; charset=utf-8")
            elif path in self.assets.files:
                self._route = "static"
                body, ctype = self.assets.files[path]
                self._send(200, body, ctype)
            elif path == "/health":
                self._route = "health"
                self._json(200, {"status": "ok", "version": APP_VERSION})
            elif path == "/client.py":
                self._route = "client"
                self._send(200, self.assets.client, "text/x-python; charset=utf-8",
                           {"Content-Disposition": 'inline; filename="secret_drop_client.py"',
                            "X-Content-SHA256": self.assets.client_sha256})
            elif path == "/SKILL.md":
                self._route = "skill"
                self._send(200, self.assets.skill, "text/markdown; charset=utf-8",
                           {"X-Content-SHA256": self.assets.skill_sha256})
            elif path == "/api/v1/info":
                self._route = "info"
                self._json(200, {"version": APP_VERSION, "suite": SUITE, "info_prefix": INFO_PREFIX,
                                 "token_required": bool(self.relay.config.api_token),
                                 "default_ttl_minutes": self.relay.config.default_ttl_minutes,
                                 "max_ttl_minutes": self.relay.config.max_ttl_minutes,
                                 "max_value_bytes": MAX_VALUE_BYTES,
                                 "client_sha256": self.assets.client_sha256, "skill_sha256": self.assets.skill_sha256})
            elif path == "/api/request":
                self._route = "view"
                self._limit("view")
                if self.headers.get("Origin") is not None and not self._same_origin():
                    raise DropError(403, "foreign_origin", "Blocked.", "Blocked")
                self._json(200, self.relay.view(self._single_header(CAPABILITY_HEADER, CAPABILITY_RE)))
            elif path.startswith("/api/v1/requests/") and path.count("/") == 4:
                self._route = "status"
                self._limit("agent")
                self._require_agent_token()
                self._json(200, self.relay.status(path.rsplit("/", 1)[1], self._single_header(PICKUP_HEADER, PICKUP_RE)))
            else:
                self._route = "other"
                self._send(404, b'{"error":"not_found"}')
        except DropError as exc:
            self._error(exc)

    def do_POST(self) -> None:
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/submit":
                self._route = "submit"
                self._limit("submit")
                # Enforced before reading state: a refused origin never consumes a request.
                if not self._same_origin():
                    self.close_connection = True
                    raise DropError(403, "foreign_origin", "This submission did not come from the Secret Drop page.", "Blocked")
                capability = self._single_header(CAPABILITY_HEADER, CAPABILITY_RE)
                payload = self._read_body(MAX_SUBMIT_BODY)
                self._json(200, self.relay.submit(capability, payload))
            elif path == "/api/v1/requests":
                self._route = "create"
                self._limit("create")
                self._require_agent_token()
                payload = self._read_body(MAX_CREATE_BODY)
                self._json(201, self.relay.create(payload, self._base_url()))
            elif path.startswith("/api/v1/requests/") and path.endswith("/pickup") and path.count("/") == 5:
                self._route = "pickup"
                self._limit("agent")
                self._require_agent_token()
                self._json(200, self.relay.pickup(path.split("/")[4], self._single_header(PICKUP_HEADER, PICKUP_RE)))
            else:
                self._route = "other"
                self.close_connection = True
                self._send(404, b'{"error":"not_found"}')
        except DropError as exc:
            self.close_connection = True
            self._error(exc)

    def do_DELETE(self) -> None:
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        try:
            if path.startswith("/api/v1/requests/") and path.count("/") == 4:
                self._route = "cancel"
                self._limit("agent")
                self._require_agent_token()
                self._json(200, self.relay.cancel(path.rsplit("/", 1)[1], self._single_header(PICKUP_HEADER, PICKUP_RE)))
            else:
                self._route = "other"
                self._send(404, b'{"error":"not_found"}')
        except DropError as exc:
            self._error(exc)

    def do_PUT(self) -> None:
        self._route = "other"
        self.close_connection = True
        self._send(405, b'{"error":"method_not_allowed"}')

    do_PATCH = do_PUT
    do_OPTIONS = do_PUT  # no CORS preflight is ever approved


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, config: Config):
        self.relay = Relay(config)
        self.assets = Assets(config)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT_CONNECTIONS)
        super().__init__((config.bind, config.port), Handler)

    def server_bind(self) -> None:
        # Skip HTTPServer's reverse-DNS getfqdn(): it stalls startup ~5 s without resolvers.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def process_request(self, request, client_address):  # bounded concurrency
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")  # type: ignore[attr-defined]
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self) -> None:
        super().server_close()
        self.relay.store.close()


def wait_for_writable(data_dir: Path) -> None:
    """Runtipi creates the bind dir root:755 and only later runs chmod a+rwx: wait instead of crashing."""
    announced = False
    while True:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            probe = data_dir / f".probe-{os.getpid()}"
            probe.write_bytes(b"")
            probe.unlink()
            return
        except OSError:
            if not announced:
                print(f"waiting for {data_dir} to become writable", flush=True)
                announced = True
            time.sleep(1)


def cleanup_loop(server: Server, stop: threading.Event) -> None:
    while not stop.wait(CLEANUP_INTERVAL_SECONDS):
        try:
            server.relay.store.retire_expired(int(time.time()))
        except Exception as exc:  # keep serving; report type only
            print("cleanup failed: " + type(exc).__name__, flush=True)


def main() -> None:
    os.umask(0o077)
    try:
        config = Config.from_env()
    except ValueError as exc:  # messages never contain the configured values
        print(f"configuration error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    wait_for_writable(config.data_dir)
    server = Server(config)
    stop = threading.Event()
    threading.Thread(target=cleanup_loop, args=(server, stop), daemon=True).start()

    def _terminate(*_: Any) -> None:
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    print(f"secret-drop {APP_VERSION} listening on {config.bind}:{config.port} "
          f"(agent token {'required' if config.api_token else 'not required'})", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
