---
wizard: 0.2
id: profiles
name: Profiles
type: view
category: app
version: 0.5.3
summary: Your Wizard profile with its own Nostr ID. Add friends by ID and share your look, build and App Store apps.
tags: [communication]
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/profiles
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8836
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8836
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8836
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides:
- profiles
system: false
uses: []
needs: []
health: /healthz
---

# Profiles

Your Wizard profile has three parts, and each one is Private, Friends or Everyone:

- **Build**: your version of Wizard, with every change of your own. Friends can **try it on**: it runs beside your own Wizard with your chats and apps, and Stop ends it. Your Wizard is never changed.
- **Look**: your skin and your own touches to it. Friends can **wear it**; one tap puts yours back.
- **Apps**: the App Store apps you have, and which ones you use a lot. Apps you build yourself never show; putting an app in the App Store is what makes it public.

Nothing is shared until you tap Publish, and others only ever see that frozen copy.

Your profile's ID is a Nostr ID (npub) that your Wizard makes for itself. To add a friend, paste their Nostr ID; they add yours. Nobody ever connects to your Wizard: what you share goes out through public Nostr relays, each friend's copy encrypted to that friend alone, and friend requests are sealed so relays can't see who added whom. There is no Publish step: Profiles shares again by itself whenever your look, build, apps or settings change.
