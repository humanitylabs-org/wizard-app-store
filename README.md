# Wizard App Store

A small [Runtipi](https://runtipi.io/) community app store by Humanity Labs. Upstream software, standard Runtipi packaging, no custom Hermes fork.

## Add the store

In Runtipi, open **Settings → App Stores → Add App Store** and enter:

```
https://github.com/humanitylabs-org/wizard-app-store
```

Requires Runtipi 4.8.0 or newer. Install **Hermes Agent**, choose its dashboard credentials, then configure your model/provider in the native Hermes dashboard.

## App types

Every Wizard app is exactly one of four types. The type is shown at the start of each app's description in Runtipi and stored as `wizard_type` in its `config.json`. Runtipi's own category list is fixed, so each type maps to one standard category: Agent → AI, Service → Utilities, View → Media, External → Network.

| Type | What it is | Example |
|---|---|---|
| **Agent** | An AI agent backend | Hermes Agent |
| **Service** | Backend with no web page of its own, used by agents and other apps | Transcriber, Secret Drop, DeFleur Video |
| **View** | Frontend only; connects to a backend that runs elsewhere | Hermes Frontend 3 |
| **External** | Holds the key for an outside service so other apps can use it | none yet |

Services and External apps are marked no-GUI, so Runtipi shows no Open button. Agent-facing apps should also expose an MCP endpoint so an agent can discover and use them without a long prompt. DeFleur Video is the first (`/mcp` on its own port); the Transcriber and Secret Drop will follow the same pattern.

## Agents

**Hermes Agent**: official `nousresearch/hermes-agent` image, pinned by version and multi-architecture digest; native dashboard; persistent `/opt/data`; no Docker-admin access. amd64 and arm64 images are published upstream; runtime smoke tests run on amd64.

Keep it on a trusted private network. Disabling Runtipi domain exposure is not a firewall; secure the published app port on a public VPS. See the [app notes](apps/hermes-agent/metadata/description.md).

## Services

**Transcriber**: shared local speech-to-text with word timings, using the unmodified [Speaches](https://github.com/speaches-ai/speaches) CPU server pinned by digest, with its optional web UI turned off. Other apps and Hermes call its OpenAI-compatible API at `http://transcriber:8000/v1` (inside Runtipi) or `http://<server>:8791/v1`. Verified by `scripts/smoke-transcriber.py`.

**Secret Drop**: a one-time, write-only way to give any agent an API key or password without pasting it into chat. The agent sends you a link. Your browser encrypts the value to that agent's own public key (HPKE: X25519 + AES-256-GCM, pure-JS so it works over plain `http://` on Tailscale), and the agent picks it up once and decrypts it locally. The app relays ciphertext only and keeps nothing long-term. Agents fetch instructions and a single-file client from `http://<server>:8792/SKILL.md` and `/client.py`. Verified by `scripts/smoke-secret-drop.py`, which runs a real Chromium in an insecure context. [Design and trust model](images/secret-drop/README.md).

**DeFleur Video (Testing)**: runs James DeFleur's video workflow for an agent over MCP (`hermes mcp add defleur-video --url http://<server>:8787/mcp`, then just ask Hermes to edit a video), with his original helper scripts bundled. It currently covers the audio/edit half: transcription via the **Transcriber** app (install it first), local word alignment, sample-exact audio cuts, per-edge waveform/spectrogram evidence and the dialogue audio gate. The older 9:16 preview still works. Face/crop audit, captions, final encode, motion graphics and delivery are not built yet. [Connect Hermes](images/defleur-video/HERMES.md) · [Parity status](images/defleur-video/WORKFLOW-PARITY.md).

## Views

**Hermes Frontend 3**: Desktop-style browser UI from the community project [przbadu/hermes-ui](https://github.com/przbadu/hermes-ui), packaged separately with no upstream UI changes. It connects to the existing Hermes backend through its API and native authentication; it does not install another agent. See [connection instructions and limitations](apps/hermes-frontend-3/metadata/description.md). This is a proof of concept, not an official Nous browser release.

## Validation

`npm ci && npm test` validates metadata, native Compose structure, and packaging safety. `python3 scripts/smoke.py` exercises the real pinned image with disposable data, checks authentication and restart persistence, and removes its own test resources. It makes no model calls and uses no real credentials. These tests do not replace a first installation check on your Runtipi host.

The browser image has an additional real-container Playwright smoke test: `uv run --with playwright python scripts/smoke-frontend.py`. The image build workflow verifies native login, session API access, desktop/mobile loading and live WebSocket traffic before publishing. Model turns are not tested. Build instructions and source attribution are in [the image notes](images/hermes-frontend-3/README.md).

## Attribution

Store structure adapted from [runtipi/example-appstore](https://github.com/runtipi/example-appstore); its license is retained. Hermes Agent and its logo belong to [Nous Research](https://github.com/NousResearch/hermes-agent); upstream code remains unmodified and under its own license. The app logo is converted from `website/static/img/logo.png` at the pinned Hermes release. This is community packaging, not an official Nous Research or Runtipi store.
