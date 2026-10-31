---
wizard: 0.2
id: browser
name: Browser
type: service
category: system
tags: [research, automation]
version: 2.0.0
summary: A shared Chrome for agents and apps; hands the live browser to you on your phone for CAPTCHAs, codes and logins.
icon: metadata/logo.jpg
license: WTFPL
source: https://github.com/humanitylabs-org/browser
runtime:
  kind: runtipi
  config: config.json
  compose: docker-compose.yml
mcp:
  path: /mcp
  port: 9222
  transport: streamable-http
skill: SKILL.md
view:
  path: /handoff/
  port: 9222
health: /handoff/health
provides:
- browser
---

# Browser

One shared Chromium for the whole Wizard. Agents use it through MCP; other apps (DeFleur Video) drive it with Puppeteer or Playwright over the Chrome DevTools Protocol at `http://browser:9222`, as before.

It runs headful on a virtual display, so it can be handed to a person. When a page needs a human (CAPTCHA, one-time code, login, consent, payment) the agent calls `start_handoff` and sends the owner a private link. The link opens this same live browser on a phone through a pinned noVNC 1.3.0 viewer with **Keyboard**, **Paste**, **Up** and **Down** controls. The owner finishes the step, says done, and the agent carries on with the same tabs, cookies and session.

- The link carries a capability in its `#fragment`; it expires (default 15 minutes) and `end_handoff` revokes it.
- The VNC stream exists only while a handoff is open, behind that capability.
- DevTools has no password and stays box-only: requests that arrive through a reverse proxy (Tailscale Serve, the Wizard gateway) get 403; only `/handoff/` is meant for the owner's devices.
