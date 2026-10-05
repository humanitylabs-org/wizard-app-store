# Wizard App Store

A small [Runtipi](https://runtipi.io/) community app store by Humanity Labs. Upstream software, standard Runtipi packaging, no custom Hermes fork.

## Add the store

In Runtipi, open **Settings → App Stores → Add App Store** and enter:

```
https://github.com/humanitylabs-org/wizard-app-store
```

Requires Runtipi 4.8.0 or newer. Install **Hermes Agent**, choose its dashboard credentials, then configure your model/provider in the native Hermes dashboard.

## Included

**Hermes Agent** — official `nousresearch/hermes-agent` image, pinned by version and multi-architecture digest; native dashboard; persistent `/opt/data`; no Docker-admin access. amd64 and arm64 images are published upstream; runtime smoke tests run on amd64.

Keep it on a trusted private network. Disabling Runtipi domain exposure is not a firewall; secure the published app port on a public VPS. See the [app notes](apps/hermes-agent/metadata/description.md).

**Hermes Frontend 3** — Desktop-style browser UI from the community project [przbadu/hermes-ui](https://github.com/przbadu/hermes-ui), packaged separately with no upstream UI changes. It connects to the existing Hermes backend through its API and native authentication; it does not install another agent. See [connection instructions and limitations](apps/hermes-frontend-3/metadata/description.md). This is a proof of concept, not an official Nous browser release.

## Validation

`npm ci && npm test` validates metadata, native Compose structure, and packaging safety. `python3 scripts/smoke.py` exercises the real pinned image with disposable data, checks authentication and restart persistence, and removes its own test resources. It makes no model calls and uses no real credentials. These tests do not replace a first installation check on your Runtipi host.

The browser image has an additional real-container Playwright smoke test: `uv run --with playwright python scripts/smoke-frontend.py`. The image build workflow verifies native login, session API access, desktop/mobile loading and live WebSocket traffic before publishing. Model turns are not tested. Build instructions and source attribution are in [the image notes](images/hermes-frontend-3/README.md).

## Attribution

Store structure adapted from [runtipi/example-appstore](https://github.com/runtipi/example-appstore); its license is retained. Hermes Agent and its logo belong to [Nous Research](https://github.com/NousResearch/hermes-agent); upstream code remains unmodified and under its own license. The app logo is converted from `website/static/img/logo.png` at the pinned Hermes release. This is community packaging, not an official Nous Research or Runtipi store.
