---
wizard: 0.2
id: wizard-tinfoil
name: Tinfoil
type: external
category: system
version: 0.3.21
summary: Private AI. Connect your Tinfoil API key and your agent gets a private, enclave-verified model.
tags: [security]
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/wizard-tinfoil
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 18804
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 18804
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 18804
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [ai-connection, tinfoil-api-key, private-inference]
private_inference:
  kind: attested-relay
  client: tinfoil
  relay_port: 8090
  egress: [inference.tinfoil.sh, atc.tinfoil.sh]
system: true
uses: [hermes-agent]
needs: []
health: /healthz
icon: icon.png
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Tinfoil
Private AI inference for your Wizard. Paste a Tinfoil API key and Connect: the app checks Tinfoil's secure enclave with the official SDK and adds a private model to your agent's model list. The key never leaves this app; the agent gets a local token for this box only. Disconnect removes both.
