---
wizard: 0.2
id: translator
name: Translator
type: service
category: app
version: 0.2.0
summary: Translate Thai, English and more with a private AI model, or offline on your phone.
license: GPL-3.0-only
icon: icon.png
source: https://github.com/humanitylabs-org/wizard-translator
runtime:
  package: source
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
provides:
- translation
system: false
uses: [tinfoil-api-key]
needs: []
receives_voice_input: true
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Translator

A private Google Translate: pick the languages (Detect, Thai, English, Japanese, Chinese, Korean, Vietnamese, Spanish,
French, German, Russian), type or paste, and the translation appears as you type. Swap, copy, and tap a recent
translation to bring it back.

**Two engines that work together** (chosen by a 33-phrase bake-off, see BAKEOFF.md):
- *Private AI* (server, best quality): `gemma4-31b` through the box's Tinfoil app (`uses: tinfoil-api-key`), in an
  attested Tinfoil enclave. The Tinfoil key never comes here: the owner's Translator page asks the Tinfoil app for a
  Translator-only box token (`POST /wizard-tinfoil/api/app-tokens`) and hands it to `POST /api/tinfoil`, the same link
  Messenger and Search use. Unlink here or Remove on the Tinfoil page revokes it.
- *On this device* (offline, instant): Firefox Translations (Bergamot, MPL-2.0) compiled to WebAssembly runs in a Web
  Worker in the phone's browser. The box mirrors only the pinned model files (`app/bergamot_models.json`, sha256-checked,
  from Mozilla's CDN) at `offline/<sha256>`; the device keeps them in Cache Storage. Thai <-> English (73 MB) downloads
  by itself on Wi-Fi; other languages from Engines.
- Flow: with the models on the device a draft appears at once, then the private AI replaces it. Without a connection,
  or when Tinfoil is unavailable, the device translation stays and says so. "Only this device" never sends text.

**API.** `POST /api/translate {text, source|auto, target, save}` (server engine) · `GET /api/languages` (languages,
engine state, offline manifest) · `GET/POST /api/tinfoil`, `POST /api/tinfoil/unlink` · `GET /offline/<sha256>` ·
`GET /api/history` · `POST /api/history` (idempotent by id) · `POST /api/history/clear` · `GET/POST /api/prefs`
(source, target, engine auto|device, speaker male|female for ครับ/ค่ะ). See `openapi.json`.

**MCP.** `translate(text, target, source, save)`, `languages()`, `history(limit)`.

**Switches.** `voice-input` (off by default): Wizard voice can send what the owner says into the source box.

**Packaging.** `runtime.package: source`: the container runs `app/server.py` from the read-only pinned source copy.
Run `python3 tools/package.py` after changing the compose shape; `python3 tools/bergamot_manifest.py` re-pins models.

Appearance decisions: [the canonical Wizard app style guide](https://github.com/humanitylabs-org/wizard-os/blob/main/style/APP-DESIGN-RULES.md).
