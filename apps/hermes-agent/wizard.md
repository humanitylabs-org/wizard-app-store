---
wizard: 0.2
id: hermes-agent
name: Hermes Agent
type: agent
category: agent
tags: [productivity, automation]
version: 2026.9.24-wizard2
summary: The AI agent itself (Nous Research), with Claude subscription support built in.
icon: icon.png
license: MIT
source: https://github.com/oscarhenrycollins/hermes-agent
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 9119
  transport: streamable-http
  auth: bearer:HERMES_API_KEY
skill: SKILL.md
view:
  path: /
  port: 9119
provides:
- agent
---

# Hermes Agent

The AI agent itself (Nous Research), with Claude subscription support built in.
