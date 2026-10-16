# Multi-account provider candidate — NOT release-ready

This directory contains an isolated read-only multi-account prototype. Production
`server.py`, `Dockerfile`, login volumes and app packaging are deliberately unchanged.

Run `WIZARD_POOL_PROVIDER=chatgpt WIZARD_POOL_PORT=18801 python3 pool_server.py`
(or `claude`) from the provider image directory. The process binds loopback by
 default. It requires the provider-prefixed `WIZARD_*_HERMES_URL`, `_HERMES_USER`
and `_HERMES_PASSWORD` already supported by the ChatGPT bridge, plus the new
Wizard OS plugin `/api/plugins/wizard-os/provider-accounts/{provider}` route.
Do not copy user subscription tokens into this process or image.

`pool-static/` is the compact candidate UI. Add/Reconnect/Remove currently open
explicit Hermes instructions, NOT an implemented browser mutation flow. Removal
asks confirmation before showing instructions; no account is removed. These are
release blockers, not completed lifecycle controls. API writes return 409.

The installed stock Hermes browser OAuth start endpoint writes the provider
singleton; it cannot safely be treated as `auth add` into a multi-account pool.
Stock pool DELETE uses a mutable 1-based index. The supported Hermes CLI has
stable-id targeting and source cleanup, but a safe CLI-backed lifecycle adapter
still needs implementation and isolated tests. Claude's existing connection-app
volume login must remain untouched; it is not a Hermes pool row.

Synthetic UI test (Playwright dependency location supplied by caller):
`PLAYWRIGHT_MODULE=/path/to/playwright node tests/provider-pool-ui.cjs`
from the app-store root. Tests do not log into, add or remove real accounts.
