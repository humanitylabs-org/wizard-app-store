---
wizard: 0.2
id: wizard-notes
name: Wizard Notes
type: service
category: app
privacy: private
personal_data: reads your notes   # holds the owner's personal data (wizard-os spec/WIZARD_MD.md "Personal data"); a label only
version: 0.1.0-alpha.17
summary: A private Markdown vault with nested folders, linked thoughts and fast full-text search.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-notes
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /gateway/mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: none
    dist: web
provides:
- note-taking
system: false
uses: []
needs: []
health: /healthz
# Owner feature switches (wizard.app-switches/1, wizard-os docs/APP_SWITCHES.md), listed and flipped by the App Manager.
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---
# Wizard Notes
Plain Markdown is the source of truth. API, MCP and view share one vault service.
Owner authorization belongs to the gateway. Back, theme, sharing and update safety use WizardApp.
