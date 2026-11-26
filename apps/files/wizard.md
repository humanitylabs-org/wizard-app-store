---
wizard: 0.2
id: files
name: Files
type: view
category: system
tags: [data]
version: 2.63.23-wizard3
summary: Your own cloud folder that every app shares.
icon: icon.png
license: WTFPL
source: https://github.com/oscarhenrycollins/files
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
view:
  path: /files/
  port: 8794
mcp:
  path: /mcp
  port: 8080
  transport: streamable-http
skill: SKILL.md
provides:
- files
needs:
- files
---

# Files

Your own cloud folder that every app shares.
