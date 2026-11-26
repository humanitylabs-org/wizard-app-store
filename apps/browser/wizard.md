---
wizard: 0.2
id: browser
name: Browser
type: service
category: system
tags: [research, automation]
version: 155.0.8059.40
summary: A shared headless Chrome for rendering and web tasks.
icon: icon.png
license: WTFPL
source: https://github.com/oscarhenrycollins/browser
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 9222
  transport: streamable-http
skill: SKILL.md
provides:
- browser
---

# Browser

A shared headless Chrome for rendering and web tasks.
