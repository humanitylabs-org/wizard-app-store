# Multi-account lifecycle candidate

Dockerfile now starts `pool_server.py`; `.dockerignore` includes its bridge and UI.
Add/reconnect/remove call the authenticated Wizard plugin's stock-CLI broker.
This is a tested local candidate, not a public release or live deployment.

See `docs/MULTI_ACCOUNT_HANDOFF.md` in this repository for configuration,
verification, safety semantics, deployment order, and owner-only gates.
