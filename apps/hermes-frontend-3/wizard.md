---
wizard: 0.2
id: hermes-frontend-3
name: Hermes Desktop in Browser
type: view
category: interface
tags: [productivity, communication]
version: 0.1.0+1af684e
summary: The Hermes Desktop experience in your browser, connected to the Hermes Agent on your Wizard.
icon: icon.png
license: MIT
source: https://github.com/oscarhenrycollins/hermes-frontend-3
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
view:
  path: /
  port: 9120
provides:
- agent-ui
uses:
- hermes-agent
---

# Hermes Desktop in Browser

A Hermes Desktop-style interface in the browser.
