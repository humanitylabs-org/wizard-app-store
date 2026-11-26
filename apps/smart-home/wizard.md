---
wizard: 0.2
id: smart-home
name: Home Assistant
type: service
category: app
tags: [automation]
version: 0.2.4
summary: Home Assistant, set up and run for you. Your Wizard checks and controls your purifiers, vacuums, lights and plugs.
icon: icon.png
license: Apache-2.0
source: https://github.com/oscarhenrycollins/smart-home
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 8080
  transport: streamable-http
skill: SKILL.md
provides:
- smart-home
health: /smart-home/healthz
view:
  path: /smart-home/
  port: 8080
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Home Assistant

[Home Assistant](https://www.home-assistant.io), the open-source smart-home hub, set up and run for you on your Wizard. You never have to open it yourself: you talk to your agent.

- **Connect your devices** once: pick your brand and sign in. It works with any brand Home Assistant supports.
- **Already run Home Assistant at home?** Choose "My own Home Assistant" and paste its address and an access token instead. Local-only devices like Zigbee and Bluetooth then work too.
- **Your agent** checks and controls your devices: "start the vacuum", "is the air bad at home?", "put the purifier on sleep".

Camera video stays in the brand's own app. Unlocking doors or disarming alarms always needs your yes.
