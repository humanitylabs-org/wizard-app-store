---
wizard: 0.2
id: importer
name: Importer
type: service
category: app
version: 0.1.12
summary: Bring your ChatGPT, Claude, Claude Code or Hermes memories, chats, skills and personality into your Wizard.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-importer
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
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides:
- data-import
system: false
uses: []
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Importer

The screen for "Bring my AI": pick ChatGPT, Claude, Claude Code, Hermes or Other; follow the in-app guide
(exact steps, a direct link to the right settings page, what to expect); the Importer waits for the export to
land in Files › Inbox (and, when the Mail app is connected, spots the export email and shows its link), then
shows what it found. The owner chooses chats, skills, personality and edits a "What I know about you" card,
which is saved only on approval. Every import can be undone. Claude Code and Hermes on this box need no export.

The engine is the agent's `wizard-os` plugin (`bring_data.py`, the same code as the `wizard_bring_data` tool),
behind the agent dashboard route `/api/plugins/wizard-os/bring-data/*`. This app holds no data and parses
nothing: it relays with the dashboard login it was installed with (filled in automatically, like ChatGPT's).
Setup's optional "Bring your AI" step opens this same screen.

Appearance: [the canonical Wizard app style guide](https://github.com/humanitylabs-org/wizard-os/blob/main/style/APP-DESIGN-RULES.md); kit classes and `--wz-*` roles only.
