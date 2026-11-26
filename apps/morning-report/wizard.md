---
wizard: 0.2
id: morning-report
name: Morning Report
type: service
category: app
version: 0.10.11
summary: Read your daily morning reports, newest first, with an unread badge for new editions.
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/morning-report
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
- morning-report
system: false
uses: []
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Morning Report

A quiet, read-only reader for dated Markdown reports (with optional PDF editions) that a scheduled agent job writes into one folder. Newest edition on top, an unread badge on the app's icon for editions you have not marked as read yet (opening one never marks it; Mark as read at the top or the end of the report does), step to an earlier or later day from the day switcher at the top, pick any day from its list, or open the PDF. The report folder is mounted read-only; the app's only write is which edition you last read (one small file in its data folder), so the badge, the Wizard OS inbox and every device agree. It contains no report content, no schedule and no personal preferences.
