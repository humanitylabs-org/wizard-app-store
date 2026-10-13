---
name: wizard-ai-accounts
description: Use when the owner wants an agent on this Wizard server to use his Claude or ChatGPT subscription, or asks whether one is connected. AI Accounts holds the sign-ins; agents never handle them.
---

# AI Accounts (Wizard system app)

AI Accounts is where the owner connects AI subscriptions once for the whole server: a Claude subscription
(Pro or Max) and a ChatGPT subscription (Plus or Pro). An API-key gateway comes later.

## What the agent must know

- The sign-in is done **by the owner, in the AI Accounts page** (`http://<server>:8795`). It runs the
  official Claude Code login. Never ask the owner for a code, token or password in chat, and never try
  to sign in yourself.
- The login lives in a private shared volume mounted at `/claude` in agent apps that support it
  (Hermes Agent from the Wizard App Store). Never read, copy, print or send anything from that folder.
- Status (read-only, plan and account label only): `GET http://wizard-ai-accounts:8795/api/accounts`.
  The `claude-subscription` row has `status`: `connected` (with `plan`) or `not_connected`.

## Using Claude from Hermes Agent

Hermes Agent from the Wizard App Store ships the official plugin
**Claude Subscription DirectSDK (Experimental)** and the official Claude Code CLI, already pointed at
the shared login. To switch, the owner picks that provider and a model (e.g. Opus) in Hermes' model
picker, or runs `hermes model`. Don't change the provider or model unless the owner asks.

If a request fails with "not logged in", tell the owner: open AI Accounts, press **Connect** on
"Claude subscription", sign in, paste the code, then press **Test**.

## ChatGPT

- The owner presses **Connect** next to "ChatGPT subscription", opens OpenAI's page, enters the short code
  shown, and approves. The page finishes by itself. The sign-in is Hermes Agent's own ChatGPT login, so the
  token stays inside Hermes.
- If the agent had no working account, it switches to ChatGPT automatically. If it already works on Claude,
  it stays there until the owner presses **Use ChatGPT**. Don't switch models unless the owner asks.
- Status: the `chatgpt-subscription` row in `/api/accounts` (`connected` + `in_use`, `not_connected`, or
  `unavailable` when Hermes Agent isn't installed).

## Limits

- One Claude account per server. Disconnecting in AI Accounts signs out every agent that uses it.
- This is for the owner's own use with his own subscription. A product that serves other people should
  use API keys instead.
