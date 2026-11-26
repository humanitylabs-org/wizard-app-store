---
wizard: 0.2
id: outline
renamed_from: [outline-streaming-demo]
name: Outline
type: service
category: app
version: 0.2.2
summary: A minimal notes-style nested outline you can type into or dictate into, with durable recovery.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/outline
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
provides: [outlining, live-dictation]
system: false
uses: []
needs: [mic]
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Outline

James's one Outline app: a minimal, Obsidian-like nested outline you can type or
dictate into through Wizard's shared microphone. The implementation is in
`runtime/` in this repo; this package connects Wizard to the owner-supervised runtime on Thales.
Its id was `outline-streaming-demo` before app ids followed app names; boxes move with `renamed_from`. No cloud credentials or fallback in source.
