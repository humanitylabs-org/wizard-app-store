# Secret Drop relay

One-time, write-only, end-to-end-encrypted credential handoff from a human to an agent.
Runtipi app: `apps/secret-drop`. Agent instructions: [`SKILL.md`](SKILL.md) (also served at `GET /SKILL.md`).
Single-file client: [`client.py`](client.py) (served at `GET /client.py`).

## Flow

1. Agent: `client.py keygen` (X25519 private key, 0600, path chosen by the agent).
2. Agent: `client.py create` → `POST /api/v1/requests {label, key, requester, public_key, ttl_minutes}`.
   Relay returns `request_url` (`http://host:8792/#c=<capability>`) and a separate `pickup_secret`.
   It stores only `SHA-256(capability)` (the request id), `SHA-256(pickup_secret)`, metadata and the public key.
3. Human opens the link. The page reads the fragment (never sent to the server in a request line,
   log or Referer), removes it from history, and shows requester, label, key name and the public-key
   fingerprint. The browser seals the value with HPKE to the agent's key and submits only `{version, suite, enc, ct}`.
   Exactly one submission can win; the link then reports "Already used".
4. Agent: `client.py pickup --write-env FILE` → `POST /api/v1/requests/<id>/pickup` with the pickup secret.
   The relay returns the ciphertext once and deletes it (tombstone with sanitized status kept 24 h).
   The client decrypts locally and writes `KEY='value'` atomically (0600, other lines preserved).

## Crypto

HPKE base mode, RFC 9180: `DHKEM(X25519, HKDF-SHA256)`, `HKDF-SHA256`, `AES-256-GCM`, single-shot, empty AAD.
`info = "wizard-secret-drop/v1|<request_id>|<KEY_NAME>"` binds the ciphertext to one request and one destination
name; the browser recomputes `request_id = SHA-256(capability)` itself rather than trusting the server.

Why this scheme: it is a standard (not a home-grown ECIES), X25519 keys are 32 bytes (easy to show
as a fingerprint), Python `cryptography` >= 46 implements it natively (the agent side has no custom crypto),
and the browser side needs only three audited primitives. RSA-OAEP would need WebCrypto or a much larger,
slower pure-JS RSA implementation.

The browser uses `static/noble-crypto.js`, an esbuild bundle of exact-pinned `@noble/curves`, `@noble/hashes`,
`@noble/ciphers` 2.4.0 (MIT, Paul Miller; audited), rebuilt byte-for-byte in CI from `vendor/package-lock.json`
(npm sha512 integrity). `static/hpke.js` implements the RFC 9180 key schedule on top; tests check the KEM against
the RFC 9180 A.1 X25519 vector and decrypt browser-sealed messages with `cryptography`'s independent HPKE.

## Why plain HTTP works, and the trust model

Runtipi serves apps at `http://<tailscale-ip>:<port>`. That is not a browser "secure context", so
`crypto.subtle` is undefined; `crypto.getRandomValues` *is* available in insecure contexts (verified in the
Chromium smoke: `isSecureContext=false`, `crypto.subtle` absent, `getRandomValues` present). The page therefore
uses pure-JS crypto and needs no HTTPS. Tailscale (WireGuard) already encrypts and authenticates the transport
between tailnet devices.

What this protects: the relay process, its SQLite file, backups of the Runtipi app-data dir, and logs only
ever hold ciphertext, hashes and metadata. A dump of the relay host cannot recover a submitted value.

What it does not protect: the relay serves the page code. Whoever controls the relay host (or can tamper with
traffic on the path, which on a Tailscale-only host means the tailnet itself) could serve modified JavaScript that
captures future inputs. Subresource Integrity on the page assets only stops mismatched asset files, not a
modified page. So the relay host is trusted for **code integrity**, not for plaintext. The fingerprint shown to the
human lets an attentive user match it with the one the agent reports, which detects a swapped public key from a
malicious relay *database* but not malicious page code. Keep the app off the public internet.

Optional HTTPS (not required, and not exercised by the release tests): on the host,
`tailscale serve --bg --https=8443 http://127.0.0.1:8792` gives `https://<host>.<tailnet>.ts.net:8443`
(MagicDNS names pass the host guard); set `SECRET_DROP_PUBLIC_URL` to that URL so agents hand it out.

## Hardening

- Caps: create body 4 KiB, submit body 64 KiB, value 32 KiB, labels 160 chars; `Content-Length` required.
- Per-IP rate limits (10-minute windows): create 30, submit 20, page metadata 240, agent status/pickup 600.
- At most 100 active requests (`SECRET_DROP_MAX_ACTIVE`); at most 64 concurrent connections; 15 s socket timeout.
- CSP `default-src 'none'; script-src 'self'; ... require-trusted-types-for 'script'`, SRI on all assets, no inline
  script, no external resources, `no-store`, `no-referrer`, `nosniff`, `DENY` framing.
- Submit requires exactly one same-origin `Origin` (and `Sec-Fetch-Site: same-origin` when sent); refused before
  any state is touched. No CORS preflight is ever approved. A Host allowlist (IP literals, single-label names,
  `*.ts.net`, `SECRET_DROP_PUBLIC_URL`, `SECRET_DROP_ALLOWED_HOSTS`) blocks DNS-rebinding.
- Pickup secret compared via `hmac.compare_digest` of SHA-256 digests; unknown id and wrong secret are indistinguishable.
- New request for the same key name from the same agent key supersedes the older pending link.
- Expired requests are retired every 30 s (ciphertext nulled); tombstones are deleted after 24 h. SQLite
  `secure_delete=ON`, file mode 0600.
- Logs contain only timestamp, method, route class and status (no paths, ids, headers or bodies).
- Optional `SECRET_DROP_API_TOKEN` requires `Authorization: Bearer` on create/status/pickup/cancel; the human page
  works with the capability alone.
- Startup waits (does not crash) until `/data` becomes writable, for Runtipi's post-up `chmod -Rf a+rwx`.

## HTTP API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` , `/static/*` | none | human page |
| GET | `/api/request` | `X-Secret-Drop-Capability` | page metadata (label, key, requester, public key) |
| POST | `/api/submit` | capability + same origin | `{version:1, suite, enc, ct}` |
| POST | `/api/v1/requests` | optional bearer | create |
| GET | `/api/v1/requests/<id>` | `X-Secret-Drop-Pickup` (+ bearer) | sanitized status |
| POST | `/api/v1/requests/<id>/pickup` | pickup (+ bearer) | ciphertext once |
| DELETE | `/api/v1/requests/<id>` | pickup (+ bearer) | cancel |
| GET | `/client.py`, `/SKILL.md`, `/api/v1/info`, `/health` | none | bootstrap + hashes |

## Development

```bash
cd images/secret-drop
uv run --no-project --with cryptography==50.0.2 python -m unittest discover -s tests -v
(cd vendor && npm ci && node build.mjs)          # must leave static/noble-crypto.js unchanged
sh test-container.sh
cd ../.. && SMOKE_HOST_IP=<tailscale-ip> uv run --no-project --with playwright==1.63.0 \
  --with cryptography==50.0.2 python scripts/smoke-secret-drop.py
```

UX and security contract adapted from humanitylabs-org/hermes-tailnet-secret-drop (MIT).
