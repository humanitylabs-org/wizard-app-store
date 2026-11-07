---
name: wizard-claude
description: Use when the owner wants to connect Claude subscriptions or check separate Claude usage on this Wizard server. Never handle credentials in chat.
---

# Claude subscriptions

- Open the Claude app (`http://<server>:8799`). Each account is one row with its own status and usage meter. The owner uses **Connect** (no accounts yet) or **Add account** and completes the official sign-in in the page; never ask for codes, passwords or tokens in chat.
- Hermes owns its managed sign-ins. Account changes are disabled unless the broker explicitly reports `management.contract=wizard.account-management/1`, `management.status=available` and exact boolean action permissions. Missing/off/unsupported/unavailable brokers fail closed. Server configuration uses the existing authenticated dashboard bridge.
- Reconnect and remove target an exact managed sign-in after in-app confirmation; remove is not provider-wide logout. Nicknames/emails do not prove distinct subscriptions or additional quota. Never change adoption, provider or model settings as a sign-in side effect.
- An existing shared Claude Code volume remains a separate, non-removable legacy source. Never copy its login into Hermes or expose anything from `/claude`. Existing DirectSDK settings stay unchanged.
- On expired legacy credentials the owning app may run one bounded noninteractive Haiku test through its official CLI. GET schedules this in the background and returns `renewing` immediately; after completion a fresh read reports `connected` or `expired` with its reason. Only one renewal runs at a time; a 600-second completion-based cooldown follows success/failure/challenge/timeout. `WIZARD_CLAUDE_AUTO_RENEW=0` disables it. This existing test policy may consume one Haiku turn; never start an automatic login or implement a token refresh yourself.
- Box-only `GET /api/connection` and the MCP card retain `wizard.ai-connection/2`, plan/account/usage and model discovery. Aggregate status is connected only when a usable subscription exists; expired rows alone never imply connected.

## Isolated model calls (decision #65)

Apps declare `requires.models` and call the Connection Router, not this provider directly. `/api/infer` retains main's isolated explicit-text SSE inference, warm single-use spare, model catalogue, grant enforcement, deadlines and effective-model validation. No persona, memory or session persistence. Deltas are provisional: only final `done` is success. Never bypass `signed_out`, `expired`, `limit`, `unreachable` or `provider_error` by silently switching accounts/models. Grants remain report-only until configured; keep this app on a trusted private network.

Personal use with the owner's own subscriptions. Fixture checks do not prove real sign-in or renewal success.
