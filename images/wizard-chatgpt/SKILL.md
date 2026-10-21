---
name: wizard-chatgpt
description: Use when the owner wants to connect ChatGPT subscriptions or check their separate usage on this Wizard server. Hermes owns the credentials.
---

# ChatGPT subscriptions

- Open the ChatGPT app (`http://<server>:8800`). Each subscription has its own card and usage meter. The owner uses **Sign in / + Add** and completes the provider's sign-in on the page; never ask for codes, passwords or tokens in chat.
- Hermes owns and renews these credentials. Never read, copy, print or send its auth files. Never change external-login adoption, provider, or model settings as a side effect of connecting.
- `GET /api/accounts` reads the inventory. Account changes are disabled unless the broker explicitly reports `management.contract=wizard.account-management/1`, `management.status=available` and exact boolean action permissions. Missing/off/unsupported/unavailable brokers fail closed. Server configuration uses the existing authenticated dashboard bridge.
- Reconnect and remove target an exact managed sign-in, after in-app confirmation. Remove is not a provider-wide logout. Multiple sign-ins for the same principal may share quota; nicknames/emails are not proof of separate subscriptions.
- Box-only `GET /api/connection` and the MCP card retain `wizard.ai-connection/2`, model discovery and status fields. Only a usable `ready`/`connected` row makes aggregate status `connected`; an expired row alone reports `expired`, not connected.

## Isolated model calls (decision #65)

Apps declare `requires.models` and call the Connection Router, not this provider directly. `/api/infer` retains main's isolated explicit-text SSE inference, grant enforcement, deadlines and effective-model validation. No persona, memory or session persistence. Text deltas are provisional: only final `done` is success. Never bypass `signed_out`, `expired`, `limit`, `unreachable` or `provider_error` by silently switching accounts or models. Grants remain report-only until configured; keep this app on a trusted private network.

Personal use with the owner's own subscriptions. No credential files are exposed by the HTTP surface.
