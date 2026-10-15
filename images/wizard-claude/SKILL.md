---
name: wizard-claude
description: Use when the owner wants an agent on this Wizard server to use his Claude subscription, or asks whether Claude is connected or how much of his Claude usage is left. The Claude app holds the one shared sign-in; agents never handle it.
---

# Claude (Wizard AI connection app)

The Claude app is where the owner connects his Claude subscription (Pro or Max) once for the whole
server. It replaces the Claude part of the older AI Accounts app (decision #61: one app per AI provider).

## What the agent must know

- The sign-in is done **by the owner, on the Claude app's page** (`http://<server>:8799`). It runs the
  official Claude Code login. Never ask the owner for a code, token or password in chat, and never try
  to sign in yourself.
- The login lives in a private shared volume mounted at `/claude` in agent apps that support it
  (Hermes Agent from the Wizard App Store). Never read, copy, print or send anything from that folder.
- Status and usage (read-only, never a token): the MCP tool `connection_status`, or
  `GET http://wizard-claude:8799/api/connection` from the app network. It returns the
  `wizard.ai-connection/1` shape: `status` (`connected`, `not_connected`, `expired`, `error`), `plan`
  (e.g. `Max 20x`), `account`, and `usage.limits[]` (`label`, `usedPercent`, `remainingPercent`,
  `resetsAt`) plus `usage.paid` (extra usage spend, minor units).

## Using Claude from Hermes Agent

Hermes Agent from the Wizard App Store ships the official plugin
**Claude Subscription DirectSDK (Experimental)** and the official Claude Code CLI, already pointed at
the shared login. To switch, the owner picks that provider and a model (e.g. Opus) in Hermes' model
picker, or runs `hermes model`. Don't change the provider or model unless the owner asks.

If status is `not_connected`, tell the owner: open the Claude app, press **Connect**, sign in, paste the
code, then press **Test**. If it is `expired`, pressing **Test** lets Claude Code renew the sign-in; if
that fails, Connect again.

## Limits

- One Claude account per server. Disconnecting in the Claude app signs out every agent that uses it.
- This is for the owner's own use with his own subscription. A product that serves other people should
  use API keys instead.
