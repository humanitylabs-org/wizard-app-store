---
wizard: 0.2
id: wizard-simplefin
name: SimpleFIN
type: external
category: system
version: 0.1.8
summary: Connect your banks through SimpleFIN. Your apps get read-only accounts, balances and transactions.
tags: [finance]
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/wizard-simplefin
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8808
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8808
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8808
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [bank-connection, simplefin-bank-data]
system: true
uses: []
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# SimpleFIN

The bank connection for your Wizard. Create your own SimpleFIN Bridge account ($15 a year, paid to SimpleFIN), link your banks there, create a setup token and paste it here. Your bank passwords go to SimpleFIN, never to this app. SimpleFIN covers thousands of U.S. and Canadian banks, including Chase and American Express, and refreshes them about once a day.

The app keeps its private SimpleFIN access address and a local copy of accounts, balances and transactions in its own folder, syncs a few times a day within SimpleFIN's request limits, and offers the data read-only to other apps on this box (`bank-connection` spot, contract `wizard.bank-connection/1`). Disconnect deletes the copy here.
