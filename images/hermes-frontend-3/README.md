# Hermes Frontend 3 — Desktop browser proof of concept

This is packaging of [przbadu/hermes-ui](https://github.com/przbadu/hermes-ui),
MIT-licensed, at `1af684e2d6ce05e6d1da82d67bc671e15d2d2d96`.
It is a community extraction of the official Desktop renderer, not an official
Nous browser release. No upstream UI files are patched.

The image contains static UI assets and nginx only. `/api`, `/auth`, `/login`
and WebSockets are forwarded to one administrator-configured Hermes origin.
There is no agent process, Hermes data volume, provider secret or Docker socket.
Native Hermes login remains authoritative. Keep both services private.

Build: `npm ci`, `sh scripts/prepare-frontend.sh`, then
`docker build -t wizard-hermes-frontend-3:test images/hermes-frontend-3`.
Test: `uv run --with playwright python scripts/smoke-frontend.py` (Chrome or
Playwright Chromium required). Tests use disposable real Hermes state and no
model/provider credentials. The published workflow repeats this before push.

Runtime: set `HERMES_BACKEND_URL` to the existing backend's reachable HTTP(S)
origin, including port, without path or credentials. The frontend listens on
8080 as uid/gid 101; upstream TLS is verified and Docker DNS is re-resolved.
Recreating or removing this frontend does not delete backend state.

Limitations: the upstream welcome heading clips on narrow phones. Desktop is
the primary target. Login, session API and live WebSocket traffic are tested;
real model turns and all Desktop features are not certified. This package does
not make arbitrary Hermes versions compatible with this pinned renderer.

The source fetch and build require network access; runtime requires only access
to the configured backend. The inherited nginx base and upstream frontend keep
their own licenses; the UI MIT license is included at `/LICENSE.upstream`.
