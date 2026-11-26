---
wizard: 0.2
id: wizard-files
name: Wizard Files
version: 0.1.6
type: service
category: system
summary: Browse, search and preview your Wizard owner-files storage with the shared resumable upload service.
license: MIT
source: https://github.com/humanitylabs-org/wizard-files
icon: icon.png
runtime:
  package: build
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
view:
  path: /
  port: 8080
  source: .
api:
  path: /api
  port: 8080
mcp:
  path: /mcp
  port: 8080
skill: SKILL.md
provides: [files]
needs: []
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---
Wizard Files is the owner-files provider. It reads only the mounted Wizard files
root; uploads use the box's existing `/wizard/v1/uploads` service configured for
the same root. Legacy catalogs and private-agent storage remain separate.
