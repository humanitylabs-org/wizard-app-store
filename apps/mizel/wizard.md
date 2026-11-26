---
wizard: 0.2
id: mizel
name: Recorder
type: service
category: app
voice_names: [mizel, meetings, meeting recorder]
tags: [audio, productivity]
privacy: private
# Private app: recordings and transcripts are not readable by public agents.
version: 0.2.10
summary: Record meetings, upload audio, keep notes and search transcripts using the shared transcriber.
icon: icon.png
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-recorder
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8080
  path: /api
  spec: openapi.json
mcp:
  path: /meetings/mcp
  port: 8080
  transport: streamable-http
skill: SKILL.md
view:
  path: /
  port: 8080
provides: [meeting-recording, meeting-transcripts, ready-extension]   # ready-extension: the shell sends due Private-agent meetings (issue 29)
system: false
uses: [transcription]   # the App Manager links this app to the box's Transcription app, which answers as `transcriber` (issue 20)
needs: [mic]
agent_binding:
  required: false
  purpose: Where your meeting recaps go
health: /healthz
owner_proof: hmac-v1   # wizard-os#133: switch calls need the signed owner proof once the box turns owner proof on
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Recorder

Record meetings from your device, upload audio, keep notes and search transcripts. This package is the recorder backend: HTTP API, MCP tools, storage and the transcription queue. The shared transcription provider does the speech recognition; this app contains no model. It starts empty and keeps SQLite, audio and notes in its own app-data volume. Uninstall preserves that volume.

Capture uses the existing Wizard recorder bridge on the owner's device. The full Recorder screen (live words, Ask cards, live summary, playback, transcript and outline; `live/`) is served by this app at `/live/` (opening the app's address goes there) and needs a live words key in the app settings. Optional OpenAI-compatible notes enhancement uses owner-supplied configuration only. Finished recaps go to the agent this app routes through (chosen in Wizard, the main agent by default) through the Wizard delivery endpoint; the app never names an agent, and a bound agent that is down keeps recaps queued (`GET /api/agent-delivery`).
