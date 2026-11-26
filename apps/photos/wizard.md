---
wizard: 0.2
id: photos
name: Photos
type: view
category: app
tags: [photos]
version: 0.5.2
summary: Your own Google Photos on your Wizard (Immich). Import from Google Takeout, group faces, clean up, back up your phone.
icon: icon.png
license: AGPL-3.0-only
source: https://github.com/humanitylabs-org/photos
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8080
  path: /photos/api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8080
  transport: streamable-http
skill: SKILL.md
provides:
- photos
health: /healthz
view:
  path: /photos/
  port: 8080
  source:
    path: web
    build: python3 mcp/inline.py
    dist: web
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Photos

[Immich](https://immich.app), the open-source Google Photos replacement, set up and run on your Wizard. Unmodified and pinned to Immich v3.4.1.

- **Leave Google Photos.** Ask Google Takeout for Google Photos only (.zip, 50 GB parts), put the parts in **Files › Photos › Import**, tap **Import now**. Dates, places, descriptions and albums come across ([immich-go](https://github.com/simulot/immich-go)); running it again never makes duplicates.
- **Faces and search.** Immich groups faces by itself and lets you search by what is in a photo ("beach at sunset"), by person, place or date.
- **Clean up.** Select by person or date and delete in bulk. Deleted photos go to the trash for 30 days, then they are gone for good.
- **No sign-in.** No email, no password, no account to make. Your Tailscale is the lock: any device on your tailnet opens straight into your library. Photos makes Immich's one account by itself (a placeholder email and a random password that stays on your box, never shown) and signs every visit in for you.
- **Phone backup.** In the Wizard OS Android app, open Photos and tap **Phone backup**: one switch turns it on (sign in with your fingerprint), Wi-Fi only, first backup while charging, choose albums. Originals go to this library; nothing is deleted from the phone. On iPhone or any other phone, install the Immich app on Android or iPhone, type your Photos address as the server (Photos › Agent shows it), tap **Next**, then **Continue**. Nothing else to type.
- **Your agent** is connected by itself: "how many photos of Ana from 2019?", "import my Takeout", "move my 2015 screenshots to the trash" (always with your yes, never a permanent delete).

Your photos stay on your box in Files › Photos › Library. Immich is AGPL-3.0; this packaging is AGPL-3.0 too.
