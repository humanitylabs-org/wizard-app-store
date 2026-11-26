---
name: wizard-chatgpt
description: Use when the owner wants his agent on this Wizard server to use his ChatGPT subscription, or asks whether ChatGPT is connected. The ChatGPT app starts the agent's own ChatGPT sign-in; agents never handle the token.
---

# ChatGPT (Wizard AI connection app)

The ChatGPT app is where the owner connects his ChatGPT subscriptions (Plus or Pro) for the server
(decision #61: one connection app per AI provider). Any number of subscriptions; the agent uses them all.

## What the agent must know

- Sign-in is done **by the owner, on the ChatGPT app's page**: **Connect** (or **Add account**), copy the code,
  **Open sign-in and paste the code**, approve on ChatGPT. ChatGPT refuses the code until the owner turns on
  **Settings → Security → Device code sign-in for Codex** once; the page says so first. Never ask the owner for
  a code, token or password in chat, and never try to sign in yourself.
- Each sign-in runs inside the agent (stock `hermes auth add openai-codex`, started by the agent's dashboard),
  so it lands in the agent's own credential pool and the agent renews it. Never read, copy, print or send
  Hermes' `auth.json` or any ChatGPT token: refresh tokens are single-use, so a copy signs the agent out.
- Status (read-only, never a token): the MCP tool `connection_status`, or `GET /api/connection` from the app
  network: `wizard.ai-connection/2` with `status`, `plan`, `usage`, `accounts` (one row per subscription) and
  `error` with a plain message.

## When status is `error`

- `error.code` `unreachable`, `not_configured` or `login_rejected`: the app can't reach or log in to the agent's
  dashboard (for example after the server's private address changed). Alongside your own Hermes: run
  `wam alongside`, then any `wam app update ...` it prints (re-points the app at this agent and restarts it);
  otherwise `wam app update wizard-chatgpt`. Then check again. The page shows the same reason with a Retry button.
- `limit`: that subscription hit its limit; the owner can add another one with **Add account**.

## Limits

- One agent per app: the sign-ins belong to the agent this app is linked to.
- Personal use with the owner's own subscriptions.
