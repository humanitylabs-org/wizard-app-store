---
wizard: 0.2
id: wizard-music
name: Music
version: 0.2.0-test.30
type: service
category: app
voice_names: [music, songs, music player, wizard music]
summary: Your music player and library. Online songs come from music connector apps like YouTube Music.
license: MIT
source: https://github.com/humanitylabs-org/wizard-music
icon: icon.png
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  path: /wizard-music/api
  port: 9205
  spec: API.md
mcp:
  path: /mcp
  port: 9205
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /wizard-music/
  port: 9205
  source:
    path: src
    build: npm ci && npm run build
    dist: dist
health: /health
provides: [music]
voice_routes:
  - words: [music, shazam]
    open: "?view=identify&listen=1"
    rest_param: q
needs: []
uses: [music-source]
# More like this stations (wizard-music#90, on for everyone): the one AI need, reached through the
# Connection Router (wizard-os spec/CONNECTION_ROUTER.md). Optional: without it a station is plain radio.
requires:
  models:
    curated-radio:
      label: Pick songs like this for a station
      purpose: Pick songs that sound like the one you started a station from
      tier: fast
      tested_on: claude-haiku-4-5
      swap: ask
      private_data: false
      required: false
      abilities: []
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---
## Registry packaging

The Alpha Store installs architecture-specific, checksum-verified Docker archives from the public prerelease, like Android Apps. The shared Actions builder also produces a multi-architecture GHCR index. Image-only packaging is not required on older Wizard releases.

Test release. Open Music after Store Get; online sources are off until you choose to enable them. Your data directory and server-only token are initialized automatically.
Requires the host's shared WizardApp client and authenticated same-origin gateway.
Native background playback is not certified by this embedded web package.
