Browser reads public articles inside Wizard. It keeps agent Chrome automation private and uses isolated, disposable Reader contexts. Source images pass through a guarded bitmap proxy. Open the original in your own browser for sign-ins and site checks.

**License**
- Packaging (Containerfile and scripts): MIT, Copyright (c) 2016-2026 Kenneth Shaw (chromedp).
- Chromium / headless-shell: BSD-3-Clause (The Chromium Authors) plus the third-party licenses bundled with Chromium. The chromedp build reports Chrome's user agent and has minor embedding changes made upstream; this store does not modify the image.
- Chosen over browserless/chromium, which is dual-licensed SSPL-1.0 or a paid commercial license and so does not fit a store whose apps are sold to customers.

Reader dependencies retain their upstream notices: Mozilla Readability (Apache-2.0), DOMPurify (Apache-2.0 or MPL-2.0), jsdom (MIT), Playwright (Apache-2.0), ipaddr.js (MIT).
