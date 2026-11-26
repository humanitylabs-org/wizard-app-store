---
wizard: 0.2
id: defleur-video
name: DeFleur Video
type: service
category: app
tags: [video]
version: 0.7.2
summary: "James' vertical-video workflow. It cuts, crops, adds motion graphics and captions."
icon: icon.png
license: MIT
source: https://github.com/humanitylabs-org/defleur-video
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 8787
  transport: streamable-http
skill: SKILL.md
provides: [video-editing, short-form-video]
recommends:
  agent: hermes
  model: claude-opus-5-5
system: false
uses: [transcriber, browser, files]
needs: [files]
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# DeFleur Video

Ask your Wizard to "edit this video". It transcribes through the Transcriber app, proposes one combined cut + motion plan for approval, renders through the shared Browser app, and saves the finished short to Files/Videos/Edited.

Split out of `wizard-app-store` with full history on 9 Oct 2026. The Runtipi files are unchanged and live in `runtipi/`. This repo builds, tests and publishes its own image (`.github/workflows/image.yml`): every push to `main` publishes `ghcr.io/humanitylabs-org/defleur-video-app:<version>`.
