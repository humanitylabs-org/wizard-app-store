---
wizard: 0.2
id: wizard-claude
name: Claude
type: external
category: system
tags: [security]
version: 0.2.24
summary: Connect one or more Claude subscriptions; every agent on the box uses them, and you see how much each has left.
icon: icon.png
license: MIT
source: https://github.com/oscarhenrycollins/claude-connection
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: SKILL.md
view:
  path: /
  port: 8799
provides:
- ai-connection
- claude-subscription
health: /health
---

# Claude

Connect your Claude Pro or Max subscriptions. The original sign-in runs Anthropic's official Claude Code login and stays in a private shared volume; **Add account** signs in more subscriptions (any number) inside your agent with Hermes' own Claude sign-in, so your agent rotates across them when one hits its limit. Agents never see a token.

This is a Wizard AI connection app (`wizard.ai-connection/2`): `GET /api/connection` reports the overall status, plan and usage plus one row per subscription, `GET /api/accounts` lists the subscriptions, and the MCP tool `connection_status` gives agents the same answer. Adding, reconnecting and removing subscriptions goes through the agent's dashboard (Wizard OS plugin, stock `hermes auth`); the original Claude Code sign-in keeps its own page at `/claude-code/`. Engine source: `humanitylabs-org/wizard-app-store` `images/wizard-claude`.
