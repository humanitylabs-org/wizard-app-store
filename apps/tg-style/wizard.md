---
wizard: 0.2
id: tg-style
renamed_from: [telegram]
name: TG style
type: service
category: app
version: 0.8.48
summary: Your Wizard chats with Telegram's look.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/telegram
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
provides: []
system: false
uses: [transcription]
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# TG style

A different look for the same Wizard chats: Telegram's chat list (folders, avatars, unread badges, archived chats, search) and Telegram-style message bubbles. It opens as a normal app window (desktop and phone) and reads the same threads as Chats through the shell, keeps no messages of its own, and never changes the built-in Chats.
