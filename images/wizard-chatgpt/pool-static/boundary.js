/* Browser boundary (draft, default-off): only inside Wizard's opaque frame (origin null) this page loads Wizard's
 * opaque-frame client and WizardApp, in order, before app.js runs. Same-origin and standalone pages load neither,
 * so they behave exactly as before. */
(() => {
  'use strict';
  let opaque = false;
  try { opaque = window.parent !== window && globalThis.origin === 'null'; } catch (e) { opaque = true; }
  if (!opaque) return;
  for (const src of ['/wizard-os-home/core/browser-boundary-client.js', '/wizard-os-home/core/app-client.js']) {
    const s = document.createElement('script'); s.src = src; s.async = false; document.head.appendChild(s);
  }
})();
