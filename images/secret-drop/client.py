#!/usr/bin/env python3
"""Secret Drop agent client (single file; needs only `cryptography` >= 46 for HPKE).

Lets an agent receive one credential from a human without it passing through chat:

  keygen  --key-file PATH                      create a private X25519 key (0600)
  create  --relay URL --key-file PATH --key NAME --label TEXT --requester NAME
          [--ttl-minutes N] [--state PATH]     register a request; prints request_url
  status  --state PATH                         sanitized status of that request
  wait    --state PATH [--timeout S]           poll until submitted/expired
  pickup  --state PATH --key-file PATH (--write-env FILE | --stdout --i-understand-this-prints-the-secret)
  cancel  --state PATH                         withdraw a pending request

The relay only ever stores ciphertext sealed to your public key (HPKE, RFC 9180:
DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-256-GCM). Decryption happens here.
The request state file holds the pickup secret; keep it 0600 and never paste it.
Optional: SECRET_DROP_API_TOKEN env var is sent as a bearer token if the relay requires it.

MIT License. Part of humanitylabs-org/wizard-app-store (apps/secret-drop).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CLIENT_VERSION = "0.1.0"
SUITE = "HPKE-base/DHKEM-X25519-HKDF-SHA256/HKDF-SHA256/AES-256-GCM"
INFO_PREFIX = "wizard-secret-drop/v1"
PICKUP_HEADER = "X-Secret-Drop-Pickup"
ENV_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{64}")
MAX_ENV_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024


class ClientError(Exception):
    pass


def _crypto():
    try:
        from cryptography.hazmat.primitives import hpke, serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ClientError("This client needs the `cryptography` package, version 46 or newer (HPKE support).") from exc
    suite = hpke.Suite(hpke.KEM.X25519, hpke.KDF.HKDF_SHA256, hpke.AEAD.AES_256_GCM)
    return suite, serialization, X25519PrivateKey, X25519PublicKey


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ClientError("Relay returned malformed data.")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def fingerprint(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).hexdigest()[:16]
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def _no_symlinks(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ClientError(f"Refusing to use a path containing a symlink: {current}")


def _write_private(path: Path, data: bytes, *, exclusive: bool) -> None:
    path = Path(os.path.abspath(path.expanduser()))
    _no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_private(path: Path, what: str) -> bytes:
    path = Path(os.path.abspath(path.expanduser()))
    _no_symlinks(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        raise ClientError(f"{what} not found: {path}") from None
    if st.st_mode & 0o077:
        raise ClientError(f"{what} {path} must not be readable by group/others (chmod 600).")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise ClientError(f"{what} {path} is not owned by the current user.")
    return path.read_bytes()


# ----------------------------------------------------------------------------- keys

def keygen(key_file: Path) -> dict[str, str]:
    _, serialization, X25519PrivateKey, _ = _crypto()
    private = X25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    try:
        _write_private(key_file, pem, exclusive=True)
    except FileExistsError:
        raise ClientError(f"{key_file} already exists; refusing to overwrite a private key.") from None
    public = public_key_bytes(load_private(key_file))
    return {"key_file": str(key_file), "public_key": b64u(public), "fingerprint": fingerprint(public)}


def load_private(key_file: Path):
    _, serialization, X25519PrivateKey, _ = _crypto()
    key = serialization.load_pem_private_key(_read_private(key_file, "Private key"), password=None)
    if not isinstance(key, X25519PrivateKey):
        raise ClientError("Private key file is not an X25519 key.")
    return key


def public_key_bytes(private) -> bytes:
    _, serialization, _, _ = _crypto()
    return private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


# ----------------------------------------------------------------------------- HTTP

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def normalize_relay(url: str) -> str:
    url = url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise ClientError("--relay must look like http://100.x.y.z:8792 (no path).")
    return url


def call(relay: str, method: str, path: str, body: dict[str, Any] | None = None,
         pickup: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json", "User-Agent": f"secret-drop-client/{CLIENT_VERSION}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if pickup:
        headers[PICKUP_HEADER] = pickup
    token = os.environ.get("SECRET_DROP_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(relay + path, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        raise ClientError(f"Cannot reach the Secret Drop relay at {relay}: {type(exc).__name__}") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ClientError("Relay response too large.")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        raise ClientError(f"Relay returned non-JSON (HTTP {status}).") from None
    return status, payload if isinstance(payload, dict) else {}


def _fail(status: int, payload: dict[str, Any]) -> ClientError:
    return ClientError(f"HTTP {status}: {payload.get('error', 'error')}: {payload.get('message', '')}".rstrip(": "))


# ----------------------------------------------------------------------------- commands

def create(relay: str, key_file: Path, key: str, label: str, requester: str, ttl: int | None,
           state_path: Path) -> dict[str, Any]:
    relay = normalize_relay(relay)
    if not ENV_KEY_RE.fullmatch(key):
        raise ClientError("--key must be an uppercase environment variable name, e.g. EXAMPLE_API_KEY.")
    if state_path.exists():
        raise ClientError(f"{state_path} already exists. Use a new --state path, or finish/cancel that request first.")
    public = public_key_bytes(load_private(key_file))
    body: dict[str, Any] = {"key": key, "label": label, "requester": requester, "public_key": b64u(public)}
    if ttl is not None:
        body["ttl_minutes"] = ttl
    status, payload = call(relay, "POST", "/api/v1/requests", body)
    if status != 201:
        raise _fail(status, payload)
    request_id = str(payload.get("request_id", ""))
    if not REQUEST_ID_RE.fullmatch(request_id) or payload.get("suite") != SUITE \
            or payload.get("fingerprint") != fingerprint(public) or payload.get("key") != key \
            or payload.get("info") != f"{INFO_PREFIX}|{request_id}|{key}":
        raise ClientError("Relay response does not match this request; refusing to use it.")
    url = str(payload.get("request_url", ""))
    fragment = url.partition("#c=")[2]
    if not fragment or hashlib.sha256(fragment.encode("ascii")).hexdigest() != request_id:
        raise ClientError("Relay returned a link that does not match its request id; refusing to use it.")
    state = {"relay": relay, "request_id": request_id, "pickup_secret": payload["pickup_secret"], "key": key,
             "label": payload.get("label"), "requester": payload.get("requester"), "key_file": str(key_file),
             "fingerprint": payload["fingerprint"], "expires_at": payload.get("expires_at")}
    _write_private(state_path, json.dumps(state, indent=2).encode("utf-8"), exclusive=True)
    return {"request_url": url, "request_id": request_id, "key": key, "label": payload.get("label"),
            "requester": payload.get("requester"), "fingerprint": payload["fingerprint"],
            "expires_at": payload.get("expires_at"),
            "expires_at_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(payload.get("expires_at", 0)))),
            "superseded_older_links": payload.get("superseded", 0), "state_file": str(state_path)}


def load_state(state_path: Path) -> dict[str, Any]:
    try:
        state = json.loads(_read_private(state_path, "Request state"))
    except ValueError:
        raise ClientError("Request state file is corrupt.") from None
    if not REQUEST_ID_RE.fullmatch(str(state.get("request_id", ""))):
        raise ClientError("Request state file is corrupt.")
    return state


def status(state_path: Path) -> dict[str, Any]:
    state = load_state(state_path)
    code, payload = call(state["relay"], "GET", f"/api/v1/requests/{state['request_id']}", pickup=state["pickup_secret"])
    if code != 200:
        raise _fail(code, payload)
    return payload


def wait(state_path: Path, timeout: float, interval: float = 3.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        current = status(state_path)
        if current.get("status") != "pending" or time.monotonic() >= deadline:
            return current
        time.sleep(interval)


def parse_env_line_key(line: str) -> str | None:
    match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    return match.group(1) if match else None


def quote_dotenv_value(value: str) -> str:
    """Single-quoted literal: python-dotenv and docker compose do no interpolation inside."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def atomic_update_env(env_path: Path, key: str, value: str) -> None:
    env_path = Path(os.path.abspath(env_path.expanduser()))
    _no_symlinks(env_path)
    if env_path.exists():
        st = env_path.stat()
        if not os.path.isfile(env_path) or st.st_size > MAX_ENV_BYTES:
            raise ClientError("Target env file is not a regular file of sane size.")
        text = env_path.read_text(encoding="utf-8")
    else:
        text = ""
    output: list[str] = []
    replaced = False
    for line in text.splitlines(keepends=True):
        if parse_env_line_key(line) == key:
            if not replaced:
                output.append(f"{key}={quote_dotenv_value(value)}\n")
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append(f"{key}={quote_dotenv_value(value)}\n")
    _write_private(env_path, "".join(output).encode("utf-8"), exclusive=False)
    os.chmod(env_path, 0o600)


def decrypt(private, info: str, enc: bytes, ct: bytes) -> str:
    suite, _, _, _ = _crypto()
    try:
        plaintext = suite.decrypt(enc + ct, private, info=info.encode("utf-8"))
    except Exception:
        raise ClientError("Decryption failed: the ciphertext was not sealed to this key for this request.") from None
    try:
        value = plaintext.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ClientError("Decrypted value is not UTF-8.") from None
    if not value or any(c in value for c in "\r\n\x00"):
        raise ClientError("Decrypted value is empty or contains line breaks; refusing to store it.")
    return value


def pickup(state_path: Path, key_file: Path | None, write_env: Path | None, to_stdout: bool,
           env_key: str | None) -> tuple[dict[str, Any], str | None]:
    state = load_state(state_path)
    private = load_private(Path(key_file or state["key_file"]))
    if fingerprint(public_key_bytes(private)) != state["fingerprint"]:
        raise ClientError("This private key does not match the key the request was created with.")
    key = env_key or state["key"]
    if not ENV_KEY_RE.fullmatch(key):
        raise ClientError("Invalid env key name.")
    code, payload = call(state["relay"], "POST", f"/api/v1/requests/{state['request_id']}/pickup", {},
                         pickup=state["pickup_secret"])
    if code != 200:
        raise _fail(code, payload)
    expected_info = f"{INFO_PREFIX}|{state['request_id']}|{state['key']}"
    if payload.get("suite") != SUITE or payload.get("info") != expected_info:
        raise ClientError("Relay response does not match this request.")
    value = decrypt(private, expected_info, unb64u(payload["enc"]), unb64u(payload["ct"]))
    result = {"request_id": state["request_id"], "status": "picked_up", "key": key,
              "value_bytes": len(value.encode("utf-8")),
              "value_sha256_prefix": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]}
    if write_env is not None:
        atomic_update_env(write_env, key, value)
        result["written_to"] = str(write_env)
        _finish_state(state_path)
        return result, None
    _finish_state(state_path)
    return result, value if to_stdout else None


def _finish_state(state_path: Path) -> None:
    """The pickup secret is useless after pickup; drop the state file."""
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass


def cancel(state_path: Path) -> dict[str, Any]:
    state = load_state(state_path)
    code, payload = call(state["relay"], "DELETE", f"/api/v1/requests/{state['request_id']}", pickup=state["pickup_secret"])
    if code != 200:
        raise _fail(code, payload)
    _finish_state(state_path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secret_drop_client.py", description=(__doc__ or "").split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("keygen", help="create a private X25519 key file (0600)")
    p.add_argument("--key-file", type=Path, required=True)
    p = sub.add_parser("create", help="register a request and print the link for the human")
    p.add_argument("--relay", default=os.environ.get("SECRET_DROP_URL", ""), help="e.g. http://100.72.13.24:8792")
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--key", required=True, help="destination env var name, e.g. OPENAI_API_KEY")
    p.add_argument("--label", required=True, help="what the human is asked for, e.g. 'OpenAI API key'")
    p.add_argument("--requester", required=True, help="who is asking, e.g. 'Hermes on demobox'")
    p.add_argument("--ttl-minutes", type=int)
    p.add_argument("--state", type=Path, required=True, help="private file to keep request id + pickup secret")
    for name, helptext in (("status", "sanitized status"), ("cancel", "withdraw the request")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--state", type=Path, required=True)
    p = sub.add_parser("wait", help="poll until the human has submitted (or the link expired)")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=600)
    p = sub.add_parser("pickup", help="fetch the ciphertext once, decrypt locally, store it")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--key-file", type=Path)
    p.add_argument("--env-key", help="override the env var name to write (default: the requested key)")
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--write-env", type=Path, help="dotenv file to update atomically (0600)")
    dest.add_argument("--stdout", action="store_true", help="print the value (needs the explicit flag below)")
    p.add_argument("--i-understand-this-prints-the-secret", dest="confirm_stdout", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            out: Any = keygen(args.key_file)
        elif args.command == "create":
            if not args.relay:
                raise ClientError("Pass --relay URL or set SECRET_DROP_URL.")
            out = create(args.relay, args.key_file, args.key, args.label, args.requester, args.ttl_minutes, args.state)
        elif args.command == "status":
            out = status(args.state)
        elif args.command == "wait":
            out = wait(args.state, args.timeout)
        elif args.command == "cancel":
            out = cancel(args.state)
        else:
            if args.stdout and not args.confirm_stdout:
                raise ClientError("--stdout prints the secret; add --i-understand-this-prints-the-secret, "
                                  "and never run it where output reaches a chat transcript or log.")
            out, value = pickup(args.state, args.key_file, args.write_env, args.stdout, args.env_key)
            if value is not None:
                sys.stdout.write(value + "\n")
                sys.stderr.write(json.dumps(out) + "\n")
                return 0
    except ClientError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
