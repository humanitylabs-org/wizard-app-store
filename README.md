# Wizard App Store

> **Replaced (10 Oct 2026).** Every app here now lives in its own repo and is listed at [aiwizards.com/wizard-apps](https://www.aiwizards.com/wizard-apps). Install with the [Wizard App Manager](https://github.com/humanitylabs-org/wizard-app-manager): `./install.sh`, then `wam install <app>`. This store stays up only until existing boxes have moved; it gets no new apps.


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
| **Service** | Backend with no web page of its own, used by agents and other apps | Transcriber, Browser, Secret Drop, DeFleur Video |
| **View** | Frontend only; connects to a backend that runs elsewhere | Hermes Frontend 3 |
| **External** | Holds the sign-in or key for an outside service so other apps can use it | AI Accounts |

Services are marked no-GUI, so Runtipi shows no Open button. External apps are too, unless they need a page for you to sign in (AI Accounts). Agent-facing apps should also expose an MCP endpoint so an agent can discover and use them without a long prompt. DeFleur Video is the first (`/mcp` on its own port); the Transcriber and Secret Drop will follow the same pattern.

## Agents

**Hermes Agent**: the official `nousresearch/hermes-agent` image, pinned by version and multi-architecture digest, extended only with Anthropic's official Claude Code CLI (pinned, auto-update off) and NousResearch's official Claude Subscription DirectSDK (Experimental) provider plugin (MIT, pinned commit), published as `ghcr.io/humanitylabs-org/hermes-agent:<version>-wizard<N>`. Native dashboard; persistent `/opt/data`, untouched by the update; no Docker-admin access. Your selected model stays as it is; pick "Claude Subscription DirectSDK (Experimental)" in Hermes' model picker to use the Claude subscription connected in AI Accounts. amd64 and arm64 images; runtime smoke tests run on amd64.

Keep it on a trusted private network. Disabling Runtipi domain exposure is not a firewall; secure the published app port on a public VPS. See the [app notes](apps/hermes-agent/metadata/description.md).

## Services

**Transcriber**: shared local speech-to-text with word timings, using the unmodified [Speaches](https://github.com/speaches-ai/speaches) CPU server pinned by digest, with its optional web UI turned off. Other apps and Hermes call its OpenAI-compatible API at `http://transcriber:8000/v1` (inside Runtipi) or `http://<server>:8791/v1`. Verified by `scripts/smoke-transcriber.py`.

**Browser**: one shared headless Chromium for apps that need a real browser (DeFleur Video uses it to capture motion graphics). It is the unmodified [chromedp/headless-shell](https://github.com/chromedp/docker-headless-shell) image (MIT packaging, Chromium BSD-3-Clause), pinned by digest; no UI, no settings, stop the app to turn it off. Other apps connect with Puppeteer or the DevTools Protocol at `http://browser:9222` inside Runtipi; the host port 8793 is bound to loopback only because DevTools has no password. Chosen over browserless/chromium, which is SSPL-1.0 or a paid commercial license. Verified by `scripts/smoke-browser.py`.

**Secret Drop**: a one-time, write-only way to give any agent an API key or password without pasting it into chat. The agent sends you a link. Your browser encrypts the value to that agent's own public key (HPKE: X25519 + AES-256-GCM, pure-JS so it works over plain `http://` on Tailscale), and the agent picks it up once and decrypts it locally. The app relays ciphertext only and keeps nothing long-term. Agents fetch instructions and a single-file client from `http://<server>:8792/SKILL.md` and `/client.py`. Verified by `scripts/smoke-secret-drop.py`, which runs a real Chromium in an insecure context. [Design and trust model](images/secret-drop/README.md).

**DeFleur Video (Testing)**: runs James DeFleur's video workflow for an agent over MCP (`hermes mcp add defleur-video --url http://<server>:8787/mcp`, then just ask Hermes to edit a video), with his original helper scripts bundled. Ask Hermes to "edit this video" and it returns a finished 1080×1920 H.264/AAC vertical short. Along the way: transcription via the **Transcriber** app (install it first), local word alignment, your approval of the cut list, sample-exact audio cuts with per-edge evidence and the dialogue gate, then `render_final`. That step runs a local face audit with one fixed 9:16 crop per setup, burned-in captions via James' `caption_layer.py`, the encode via his `encode.py`, full decode and pixel checks, final re-transcription and his delivery audio gate. 0.6 adds James' motion piece: Hermes writes a small HTML/SVG/GSAP page per video, the app captures it with his `capture.cjs` in the shared **Browser** app (install it too; only motion needs it), with fullscreen B-roll inserts, more than one fixed crop setup per video and per-segment speaker choice. Uploads up to 20 minutes and 4K; finished videos up to 6 minutes. Pauses are cut only where the audio measures silent: if the transcript has a gap but the audio has sound (ASR can skip a sentence), it is listed for your review and never proposed. Measured on a 2-minute motion video (4 vCPU): 3.0 GB peak memory (limit 10 GB), Browser 0.7 GB, about 16 minutes of render, mostly the frame-by-frame Browser capture. [Connect Hermes](images/defleur-video/HERMES.md) · [Parity status](images/defleur-video/WORKFLOW-PARITY.md).

## External

**AI Accounts**: connect your AI subscriptions once for the whole server. Phase 1 is your Claude Pro/Max subscription: press Connect, open Claude's own sign-in link on your phone, paste the code back, then press Test. The sign-in is done and used only by Anthropic's official Claude Code (pinned), and is kept in a private Docker volume (`wizard-ai-accounts-claude`, not the shared media folder) that Hermes Agent also mounts. The page shows only your plan and account name. ChatGPT sign-in and an API-key gateway are listed as coming soon. Personal use with your own subscription only; products for other people should use API keys. Verified by `images/wizard-ai-accounts/test-container.sh` and `scripts/smoke-ai-accounts.py` (logged-out paths only; the real sign-in is yours).

## Views

**Hermes Frontend 3**: Desktop-style browser UI from the community project [przbadu/hermes-ui](https://github.com/przbadu/hermes-ui), packaged separately with no upstream UI changes. It connects to the existing Hermes backend through its API and native authentication; it does not install another agent. See [connection instructions and limitations](apps/hermes-frontend-3/metadata/description.md). This is a proof of concept, not an official Nous browser release.

## Validation

`npm ci && npm test` validates metadata, native Compose structure, and packaging safety. `python3 scripts/smoke.py` exercises the real pinned image with disposable data, checks authentication and restart persistence, and removes its own test resources. It makes no model calls and uses no real credentials. These tests do not replace a first installation check on your Runtipi host.

The browser image has an additional real-container Playwright smoke test: `uv run --with playwright python scripts/smoke-frontend.py`. The image build workflow verifies native login, session API access, desktop/mobile loading and live WebSocket traffic before publishing. Model turns are not tested. Build instructions and source attribution are in [the image notes](images/hermes-frontend-3/README.md).

## Attribution

Store structure adapted from [runtipi/example-appstore](https://github.com/runtipi/example-appstore); its license is retained. Hermes Agent and its logo belong to [Nous Research](https://github.com/NousResearch/hermes-agent); upstream code remains unmodified and under its own license. The app logo is converted from `website/static/img/logo.png` at the pinned Hermes release. This is community packaging, not an official Nous Research or Runtipi store.
