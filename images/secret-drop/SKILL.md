---
name: secret-drop-request
description: Use when you need an API key, token, or password from a human. Get it via a one-time encrypted Secret Drop link, never chat.
version: 0.1.1
author: Humanity Labs
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [secrets, credentials, encryption, onboarding, privacy, runtipi]
---

# Secret Drop: request a credential without chat

Use this when a task needs a credential (API key, token, password, private URL) that you do not have.
The human types it into a one-time page; the page encrypts it to **your** public key; you pick up
the ciphertext once and decrypt it locally. The relay never sees the plaintext.

## Rules (non-negotiable)

- Never ask the human to paste a secret into chat, email, a ticket, or a file you can read. If they paste one anyway, do not repeat it; tell them to rotate it and send a fresh Secret Drop link.
- Send the human **only the full `request_url`**, unshortened. The part after `#` is the one-time capability; a truncated link does not work.
- Never print, echo, log, summarize, or commit the value, the pickup secret, the state file, or the private key. `--stdout` exists for pipes only and must never be used where output reaches a transcript.
- Report honestly: what you stored where, and what you did **not** verify (the relay checks nothing about the value; only a real call to the provider proves a key works).

## 1. Get the client (once)

The relay serves its own client and this skill read-only. Replace `RELAY` with the relay URL you were given (e.g. `http://100.72.13.24:8792`).

```bash
RELAY=http://100.72.13.24:8792
mkdir -p ~/.secret-drop && chmod 700 ~/.secret-drop
curl -fsS "$RELAY/client.py" -o ~/.secret-drop/secret_drop_client.py
curl -fsS "$RELAY/api/v1/info"   # shows client_sha256; compare with: sha256sum ~/.secret-drop/secret_drop_client.py
```

It needs Python 3.10+ and `cryptography` >= 47 (HPKE). Hermes' own venv already has it; otherwise use
`uv run --with 'cryptography>=47' python ...`. Check with `python -c "from cryptography.hazmat.primitives import hpke"`.

## 2. Create a key pair (once per agent)

```bash
python ~/.secret-drop/secret_drop_client.py keygen --key-file ~/.secret-drop/agent.key
```

The private key is written 0600 and is never overwritten. Keep it; reuse it for later requests.

## 3. Create the request

`--key` is the env var you want to fill. It must be uppercase and end in `_API_KEY`, `_TOKEN`, `_SECRET`,
`_PASSWORD`, `_PASS`, `_URL`, `_URI` or `_CREDENTIAL`. `--requester` is how you are shown to the human.

```bash
python ~/.secret-drop/secret_drop_client.py create --relay "$RELAY" \
  --key-file ~/.secret-drop/agent.key \
  --key OPENAI_API_KEY --label "OpenAI API key" --requester "Hermes on demobox" \
  --state ~/.secret-drop/openai.request.json
```

Default lifetime is 2 hours (`--ttl-minutes`, 5 to 300). Creating a new request for the same key with the
same agent key replaces the older pending link (it shows "Replaced"). If the relay requires a token, export
`SECRET_DROP_API_TOKEN` first.

Send the human something like:

> Please open this one-time link and paste your OpenAI API key there (not here): <request_url>
> It shows "Requested by Hermes on demobox", "Saved as OPENAI_API_KEY" and agent key `<fingerprint>`.
> It works once and expires at <expires_at_utc>.

## 4. Wait, then pick up once

```bash
python ~/.secret-drop/secret_drop_client.py wait --state ~/.secret-drop/openai.request.json --timeout 900
python ~/.secret-drop/secret_drop_client.py pickup --state ~/.secret-drop/openai.request.json \
  --key-file ~/.secret-drop/agent.key --write-env ~/.hermes/.env
```

`pickup` deletes the ciphertext on the relay, decrypts locally, writes `KEY='value'` atomically into the
env file (other lines preserved, mode 0600) and removes the state file. Its JSON output contains only the
byte length and a short hash prefix, never the value. Status values: `pending`, `submitted`, `picked_up`,
`expired`, `superseded`, `cancelled`. Withdraw an unneeded request with `cancel --state ...`.

If your runtime caches env vars, reload it the normal way (Hermes: `/reload` or a safe restart).

## 5. Verify and report

- Confirm presence without revealing it: `grep -c '^OPENAI_API_KEY=' ~/.hermes/.env`.
- If you can, make one cheap real call to the provider and report the result (e.g. "OpenAI accepted the key: models list returned 200"). If you did not, say "stored, not verified with the provider".
- Never include the value, pickup secret, or capability in your report. The `request_id` is safe to mention.

## Security model (short)

HPKE base mode (RFC 9180): DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-256-GCM. The HPKE `info` binds the
ciphertext to the request id (SHA-256 of the capability) and the key name. The relay stores only the
capability hash, the pickup-secret hash, your public key and the ciphertext; it cannot decrypt. It does
serve the page code, so whoever controls the relay host could swap the page to capture future inputs:
treat the relay host as trusted for code integrity, and keep it on a private network (Tailscale).
