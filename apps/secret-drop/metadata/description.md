# Secret Drop

Give an AI agent an API key, token or password **without pasting it into chat**.

1. The agent asks for a key and sends you a one-time link (for example `http://100.72.13.24:8792/#c=…`).
2. You open it. The page shows who is asking, what it is for, the name it will be saved as and the agent's key fingerprint.
3. You type the value. Your browser encrypts it to that agent's own public key and sends only ciphertext.
4. The agent collects it once and decrypts it on its side. The link then shows "Already used".

This app is only a relay: it never has a key that can decrypt what you type, and it deletes the ciphertext at pickup. Links work once and expire after 2 hours by default (5 hours at most). It is not a password manager; for a vault, install Vaultwarden.

**For agents:** fetch the instructions and the single-file client from the app itself:

```
curl -fsS http://<server>:8792/SKILL.md
curl -fsS http://<server>:8792/client.py -o secret_drop_client.py
```

**Security notes**
- Encryption: HPKE (RFC 9180) with X25519, HKDF-SHA256 and AES-256-GCM, done in the page with vendored, pinned, audited [noble](https://paulmillr.com/noble/) libraries. It works over plain `http://` on Tailscale (WireGuard already encrypts the connection), where browsers disable their built-in crypto.
- The page code is served by this app, so the server it runs on must be trusted. Keep it private: Tailscale only. Docker-published ports bypass `ufw`, so if the server also has a public IP, block port 8792 at your provider's firewall.
- No password by default. Optionally set an agent API token so only agents that know it can create and collect requests; your link never needs it.
- The first start may restart once while Runtipi fixes folder permissions.
