---
wizard: 0.2
id: secret-drop
name: Secret Drop
type: service
category: system
tags: [security]
version: 0.1.1
summary: One-time encrypted links for giving an agent a password or key without pasting it in chat.
icon: icon.png
license: MIT
source: https://github.com/oscarhenrycollins/secret-drop
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 8792
  transport: streamable-http
skill: SKILL.md
provides:
- secrets
health: /health
---

# Secret Drop

One-time encrypted links for giving an agent a password or key without pasting it in chat.
