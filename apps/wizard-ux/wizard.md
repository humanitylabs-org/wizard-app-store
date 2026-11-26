---
wizard: 0.2
id: wizard-ux
name: Wizard Shell
type: view
category: interface
version: 0.3.0-candidate.20261012
summary: "The existing phone and desktop Wizard shell, independently replaceable."
icon: icon.png
license: MIT
source: https://github.com/humanitylabs-org/wizard-ux
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
view:
  path: /wizard-os-home/
  port: 8788
system: true
provides:
- shell
uses:
- agent-service
needs:
- mic
- notifications
- files
health: /shell-health
skill: skill/SKILL.md
---

# Wizard Shell
The existing phone/desktop UX, native bridge and permanent in-app Back behavior are preserved.
Serves its own static files and streams all same-origin API requests to the independently installed
Wizard Agent Service. Holds no Hermes credentials or durable agent state. No headless-browser
replacement is introduced: Chromium remains the Browser system app, as in the approved slots.
Android/Mac native wrappers continue to load the same HTTPS surface and bridge.
