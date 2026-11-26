---
wizard: 0.2
id: wizard-search
name: Search
type: service
category: app
version: 0.3.14
renamed_from: [search-preview]
summary: Free private web and image search out of the box (bundled SearXNG); optional cited AI overviews with the Tinfoil app.
license: MIT
source: .
receives_voice_input: true
icon: web/icon.png
runtime:
  kind: runtipi
  package: image
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 9288
  path: /api
  spec: openapi.json
mcp:
  port: 9288
  path: /mcp
  transport: streamable-http
skill: skill/SKILL.md
view:
  port: 9288
  path: /
  source:
    path: web
    build: python3 tools/check_view.py
    dist: web
provides: [web-search, image-search]
system: true
uses: [tinfoil-api-key]
needs: []
health: /api/health
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Search

Works on install: a bundled SearXNG sidecar (free, no account, AGPL-3.0 upstream image, private to
this app) answers web and image searches. No credentials or history are bundled. Optional paid
lanes and Tinfoil overviews are configured with SETUP.md and setup.json. Wizard gateway supplies the shared app client and authenticated
routing. This is not a new Connections implementation. Runtime dependencies are explicit
operator settings rather than fictitious installable Wizard app IDs.

## Receives voice input

The shared Wizard client delivers a transcript to Search, not Chats. A frozen
query/tab/result context selects the web or images API. Text becomes a literal
query (maximum 300 characters); no new inference provider or follow-up rewriting.
The existing typed search/overview flow is unchanged.

IndexedDB durably stores voice request identity, query/context and results in
this browser. Same-ID/same-payload retries do not run another search; conflicting
payloads, attachments and unavailable storage reject admission. An accepted
request interrupted by a reload is shown but never automatically restarted;
type a fresh query to try again. Receipts are not evicted automatically. Clearing
browser site data removes them; deduplication is not cross-device. No server-side
search history is introduced. The local-serving voice branch is a separate base;
this port preserves package setup, provider configuration and local image Save.
