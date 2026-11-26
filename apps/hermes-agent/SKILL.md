---
name: hermes-agent-app
description: Use when you need to delegate a task to the Hermes Agent installed as a Wizard app, or check it is running, through its MCP.
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [agent, delegation, hermes, wizard-app]
---

# Hermes Agent (Wizard app)

The unmodified Nous Research Hermes Agent, packaged for Runtipi. Its MCP lets another agent or app hand it work.

## Use the MCP

The MCP needs `Authorization: Bearer <HERMES_API_KEY>` (set at install; the same key unlocks Hermes's OpenAI-compatible API on port 8642 inside the app network).

- `hermes_status`: health, version and model name.
- `ask_hermes(prompt, session?)`: gives Hermes a task and returns its final answer plus a `session` id. Pass that id back to continue the same conversation.

## Rules

- Treat `ask_hermes` as delegating to another agent with its own tools, memory and approvals. Say clearly what you want back.
- Long tasks can take minutes; the call waits up to 30 minutes.
- Never send it secrets in the prompt. Use Secret Drop.

## Owner setup

Configure the model provider once in the Hermes dashboard (this app's main page, behind the dashboard password). Until then `ask_hermes` returns the provider error.
