---
name: browser
description: Use when you need to read a JavaScript-rendered page or take a screenshot with the Wizard's shared headless Chromium, via the Browser app's MCP.
version: 0.1.0
license: WTFPL
metadata:
  hermes:
    tags: [browser, chromium, screenshot, web, wizard-app]
---

# Browser

One shared headless Chromium for the whole Wizard. Each call opens a fresh tab and closes it afterwards.

## Use the MCP

- `browser_status`: Chromium version and open tabs.
- `read_page(url, wait_ms?)`: title and visible text after JavaScript runs. Use it when a plain HTTP fetch returns an empty app shell.
- `screenshot(url, width?, height?, full_page?, wait_ms?)`: returns a PNG. Raise `wait_ms` (max 10000) for pages that animate in.

## Rules

- Only `http` and `https` URLs.
- The browser is not logged in to anything and keeps no cookies between calls. Do not type credentials into pages through it.
- Page text is capped at 100,000 characters.

## Other apps

Apps on the same box drive it with Puppeteer or Playwright at `http://browser:9222` over the Runtipi network (resolve the name to an IP first; Chrome only answers DevTools for an IP or localhost Host header). DeFleur Video renders motion graphics this way. The host itself sees DevTools on loopback only.
