---
wizard: 0.2
id: wizard-youtube-music
name: YouTube Music
type: service
category: system
version: 0.1.7
summary: YouTube catalog, optional account library and playback for Music; cloud Wizards may need an always-on home relay.
tags: [audio]
license: MIT
source: https://github.com/humanitylabs-org/wizard-youtube-music
icon: icon.png
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 9206
  path: /api
mcp:
  path: /mcp
  port: 9206
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 9206
health: /healthz
provides: [music-source, youtube-music]
uses: []
needs: []
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# YouTube Music

A music source for Wizard's Music app, like SimpleFIN is a bank source for Money. Music finds it automatically and shows YouTube search, radio and songs.

Try playback directly on a home Wizard. YouTube may block cloud/VPS networks; an always-on home computer on your private Tailscale can provide a relay. The setup screen provides guided help and tests a real download before reporting playback success. Neither home internet nor account sign-in guarantees playback, ad-free/unlimited use, Premium features or lower account risk.

Optional own-account device OAuth is documented in README.md. It requires an owner-provisioned Google Cloud TV/device client and consent on Google. Account status is separate from playback; a credential file is unverified until an authenticated library call succeeds. The additive `/api/music/library/playlists`, `/likes` and `/playlist?id=` endpoints use the existing sanitized track shape; Music clients must add library consumption UI. No passwords or cookies should be sent through chat. No automatic setup message or notification delivery is claimed.

Contract `wizard.music-source/1`: `GET /api/status`, `/api/music/search?q=`, `/api/music/radio?seed=`, `/api/music/related-artists?name=`, `/api/music/genre?genre=`, `/api/music/audio/<videoId>` (Range supported; `?live=1` sends the song from byte 0 while it is still downloading, with its exact size as Content-Length when YouTube gives one, for Music's progressive play, wizard-music#46; `?codec=opus` takes YouTube's best signed-out stream, Opus itag 251 in webm, falling back to AAC when a song has none, cached beside the AAC copy, wizard-os#820). Errors return 502 with `error: blocked` when YouTube refuses this network.
