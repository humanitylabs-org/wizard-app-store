# Browser

A shared, headful Chromium for agents and apps. Agents automate through local CDP/MCP. When a page needs its owner, an expiring link opens the **same** browser on a phone, behind the Wizard owner's existing authentication.

The viewer has **Keyboard**, masked **Paste**, **Up**, **Down**, remote-page **Back**, and **Done, give it back**. Done revokes screen access and tells the agent it can continue in the same tab. Back never navigates the phone out of Wizard.

## Installation

The installer must mount `/browser/*` behind the existing owner-only gateway, including WebSocket upgrades, and strip `/browser` before proxying to the Browser app's loopback port. See the repository README and `ops/owner-route.py`. The optional **Wizard owner gateway Browser prefix** setting is an absolute authenticated prefix such as `https://your-wizard.example/browser`, not a direct CDP port. Without it, links are owner-relative `/browser/handoff/#...`.

Other Runtipi apps keep using CDP at `http://browser:9222` (resolve to an IP if Chromium rejects a hostname). Stock Hermes uses `browser.cdp_url` or `BROWSER_CDP_URL` pointing at the local app address. No Hermes core change is needed.

## Privacy and limits

- The owner gateway authenticates the owner; an expiring capability also gates each handoff. Do not expose the direct Browser port on the LAN or internet.
- Reverse-proxied DevTools **and MCP** are refused. Only the handoff page is remotely reachable.
- Links last 15 minutes by default. Done, expiry, replacement and agent revocation end existing VNC streams.
- The agent pauses page reads, screenshots and automation while the owner types. Credentials stay in the browser; they are never entered through chat.
- The profile is ephemeral: handoff and CDP disconnect preserve cookies, but app restart/replacement loses them.
- Engine: 6 GB memory, 2 GB shared memory, 4096-process limit, non-root/read-only/cap-drop container. Chromium uses `--no-sandbox`; do not treat this as a complete sandbox for untrusted pages.
- Fonts include Liberation, DejaVu and Noto Color Emoji.

## Licenses

Packaging and patches: repository license. Chromium: BSD-3-Clause and bundled third-party licenses. noVNC 1.3.0: MPL-2.0 with bundled licenses; x11vnc: GPL-2.0; websockify: LGPL-3.0; Xvfb: MIT/X11. Upstream packages are unmodified; the noVNC phone controls and Wizard chrome are build-time patches.
