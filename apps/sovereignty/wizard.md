---
wizard: 0.2
id: sovereignty
name: Sovereignty
type: view
category: app
version: 0.2.1
summary: See how much of your digital life you own, area by area, from rented services up to self-hosted.
license: GPL-3.0-only
icon: icon.png
author: Humanity Labs
tags:
- productivity
- security
source: https://github.com/oscarhenrycollins/sovereignty
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
- sovereignty-checklist
system: false
uses: []
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Sovereignty

A checklist of the owner's digital life (AI, agent, mail, calendar, chats, contacts, photos, files, backup, money, search, network). Each area sits on a 4-rung ladder from rented big-company services up to running on the owner's own box. The screen shows the overall score, each area's rung and, on tap, the ladder, what is used now, how it was checked, and the next step up. The agent checks the owner's live setup and records it with `sovereignty_set`.

Appearance decisions: [the canonical Wizard app style guide](https://github.com/humanitylabs-org/wizard-os/blob/main/style/APP-DESIGN-RULES.md).
