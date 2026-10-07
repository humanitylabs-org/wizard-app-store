/* Secret Drop page. Reads the one-time capability from the URL fragment, shows who is
 * asking, encrypts the typed value to the agent's X25519 key (HPKE) and submits only
 * ciphertext. There is no plaintext fallback, no listing, no prefill and no reveal of
 * anything except what is typed locally. Adapted from hermes-tailnet-secret-drop (MIT). */
(function () {
  'use strict';
  const HEADER = 'X-Secret-Drop-Capability';
  const SUITE = 'HPKE-base/DHKEM-X25519-HKDF-SHA256/HKDF-SHA256/AES-256-GCM';
  const INFO_PREFIX = 'wizard-secret-drop/v1';
  const te = new TextEncoder();
  const $ = (id) => document.getElementById(id);
  const heading = $('heading'), feedback = $('feedback'), form = $('secret-form'), input = $('value');
  const submit = $('submit'), countdown = $('countdown'), reveal = $('reveal');
  const found = /^#c=([A-Za-z0-9_-]{43})$/.exec(window.location.hash || '');
  const capability = found ? found[1] : '';
  if (window.history && window.history.replaceState) window.history.replaceState(null, '', window.location.pathname);
  let finished = false;
  let request = null;

  const say = (message, ok) => {
    feedback.textContent = message || '';
    feedback.hidden = !message;
    feedback.classList.toggle('ok', !!ok);
  };
  const finish = (title, message, ok) => {
    finished = true;
    input.value = '';
    form.hidden = true;
    countdown.hidden = true;
    heading.textContent = title;
    say(message, ok);
  };

  // Eye icon built with DOM APIs only (Trusted Types forbid HTML string sinks).
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8'); svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('aria-hidden', 'true');
  const mk = (tag, attrs) => { const el = document.createElementNS(NS, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); svg.appendChild(el); return el; };
  mk('path', {d: 'M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z'});
  mk('circle', {cx: '12', cy: '12', r: '2.7'});
  const slash = mk('path', {d: 'm4 4 16 16'});
  slash.style.display = 'none';
  reveal.appendChild(svg);
  reveal.addEventListener('click', () => {
    const showing = input.type === 'password';
    input.type = showing ? 'text' : 'password';
    reveal.setAttribute('aria-label', showing ? 'Hide value' : 'Show value');
    reveal.setAttribute('title', showing ? 'Hide value' : 'Show value');
    slash.style.display = showing ? '' : 'none';
    input.focus({preventScroll: true});
  });

  const startCountdown = (seconds) => {
    const deadline = performance.now() + Math.max(0, seconds) * 1000;
    countdown.hidden = false;
    const tick = () => {
      if (finished) return;
      const left = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
      countdown.textContent = (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
      if (left <= 0) { finish('Expired', 'This link is no longer valid. Ask the agent for a new one.'); return; }
      window.setTimeout(tick, 500);
    };
    tick();
  };

  const api = (path, options) => {
    const settings = Object.assign({cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer'}, options || {});
    settings.headers = Object.assign({}, settings.headers || {}, {[HEADER]: capability});
    return window.fetch(path, settings).then((r) => r.json().catch(() => ({})).then((data) => ({ok: r.ok, data: data || {}})));
  };

  if (!capability) {
    finish('Not found', 'Open the whole Secret Drop link, including the part after the # symbol.');
    return;
  }
  if (!window.crypto || typeof window.crypto.getRandomValues !== 'function' || !window.SecretDropHPKE) {
    finish('Encryption unavailable', 'This browser cannot encrypt the value here. Nothing was sent. Use a current browser.');
    return;
  }
  const H = window.SecretDropHPKE;

  api('/api/request', {method: 'GET'}).then(({ok, data}) => {
    if (!ok) { finish(data.title || 'Not found', data.message || ''); return; }
    if (data.suite !== SUITE) throw new Error('suite');
    const pk = H.b64uDecode(data.public_key);
    if (pk.length !== 32) throw new Error('key');
    // Bind to what this browser knows, not to what the server claims.
    const requestId = H.sha256Hex(capability);
    const info = INFO_PREFIX + '|' + requestId + '|' + data.key;
    if (data.request_id !== requestId || data.info !== info) throw new Error('binding');
    request = {pk, info, max: Number(data.max_value_bytes) || 32768};
    heading.textContent = data.label;
    document.title = data.label + ' \u00b7 Secret Drop';
    $('requester').textContent = data.requester;
    $('key').textContent = data.key;
    $('fingerprint').textContent = H.fingerprint(pk);
    $('value-label').textContent = data.label;
    input.setAttribute('aria-label', data.label);
    $('meta').hidden = false;
    form.hidden = false;
    input.focus({preventScroll: true});
    startCountdown(Number(data.expires_in_seconds || 0));
  }).catch(() => finish('Unavailable', 'A secure Secret Drop session could not be established. Nothing was sent.'));

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (finished || !request) return;
    const value = input.value.trim();
    if (!value) { say('Enter the value to send.'); return; }
    if (/[\r\n\0]/.test(value)) { say('Enter one value without line breaks.'); return; }
    let plaintext = te.encode(value);
    if (plaintext.length > request.max) { plaintext.fill(0); say('That value is too large.'); return; }
    submit.disabled = true;
    say('Encrypting\u2026', true);
    let envelope;
    try {
      const sealed = H.seal(request.pk, te.encode(request.info), plaintext);
      envelope = {version: 1, suite: SUITE, enc: H.b64uEncode(sealed.enc), ct: H.b64uEncode(sealed.ct)};
    } catch (_e) {
      submit.disabled = false;
      say('The value could not be encrypted. Nothing was sent.');
      return;
    } finally {
      plaintext.fill(0);
      plaintext = null;
    }
    input.value = '';
    input.type = 'password';
    api('/api/submit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(envelope)})
      .then(({ok, data}) => {
        if (ok) { finish('Sent', 'Encrypted and handed to ' + (data.requester || 'the agent') + '. You can close this page.', true); return; }
        finish(data.title || 'Not sent', data.message || 'The value was not accepted.');
      })
      .catch(() => { submit.disabled = false; say('The encrypted value could not be sent. Type it again and retry.'); });
  });
})();
