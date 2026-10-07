# Browser

A shared headless Chromium for your Wizard server. Install it once; DeFleur Video (motion-graphics capture) and any other app that needs a real browser connect to it instead of each bundling its own. It has no web page, no settings and no agent switch: stopping the app in Runtipi is the off switch.

This is the unmodified [chromedp/headless-shell](https://github.com/chromedp/docker-headless-shell) image (Chrome's `headless-shell`, version 155.0.8059.40), pinned by digest.

**From other Runtipi apps:** `http://browser:9222` (Chrome DevTools Protocol). With Puppeteer: `puppeteer.connect({browserURL: "http://<browser IP>:9222"})`.

**Notes**
- Chrome only accepts DevTools requests whose `Host` is an IP address or `localhost`, so resolve the name `browser` to its IP first (`http://browser:9222` itself returns HTTP 500 to `/json/version`). DeFleur Video does this for you.
- DevTools has no password and can open any page the server can reach. The port is published on the server's loopback only (`127.0.0.1:8793`); other apps reach it over the private Runtipi network. Keep it that way.
- Limits: 6 GB memory, 2 GB shared memory, 4096 processes. Each open page uses roughly 100-300 MB; a 1080x1920 capture page about 200 MB.
- Ships no fonts beyond what the image includes; pages should bring their own web fonts.

**License**
- Packaging (Containerfile and scripts): MIT, Copyright (c) 2016-2026 Kenneth Shaw (chromedp).
- Chromium / headless-shell: BSD-3-Clause (The Chromium Authors) plus the third-party licenses bundled with Chromium. The chromedp build reports Chrome's user agent and has minor embedding changes made upstream; this store does not modify the image.
- Chosen over browserless/chromium, which is dual-licensed SSPL-1.0 or a paid commercial license and so does not fit a store whose apps are sold to customers.
