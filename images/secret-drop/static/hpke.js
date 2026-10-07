/* HPKE base-mode seal (RFC 9180): DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-256-GCM.
 * Built only on the vendored, pinned @noble primitives (pure JS), so it works in
 * insecure contexts (plain http:// over the tailnet) where crypto.subtle is absent.
 * Randomness comes from crypto.getRandomValues, which browsers expose in insecure
 * contexts too. Tests check the KEM against the RFC 9180 A.1 X25519 vector and the
 * full seal against Python `cryptography`'s independent HPKE implementation. */
(function () {
  'use strict';
  const N = window.SecretDropCrypto;
  if (!N || !N.x25519 || !N.sha256 || !N.hkdfExtract || !N.hkdfExpand || !N.gcm) {
    throw new Error('vendored crypto missing');
  }
  const te = new TextEncoder();
  const concat = (...parts) => {
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  };
  const i2osp = (n, len) => { const b = new Uint8Array(len); for (let i = len - 1; i >= 0; i -= 1) { b[i] = n & 0xff; n >>>= 8; } return b; };
  const KEM_ID = 0x0020, KDF_ID = 0x0001, AEAD_ID = 0x0002; // X25519 / HKDF-SHA256 / AES-256-GCM
  const NK = 32, NN = 12, NH = 32;
  const HPKE_V1 = te.encode('HPKE-v1');
  const KEM_SUITE = concat(te.encode('KEM'), i2osp(KEM_ID, 2));
  const SUITE_ID = concat(te.encode('HPKE'), i2osp(KEM_ID, 2), i2osp(KDF_ID, 2), i2osp(AEAD_ID, 2));
  const labeledExtract = (suite, salt, label, ikm) => N.hkdfExtract(N.sha256, concat(HPKE_V1, suite, te.encode(label), ikm), salt);
  const labeledExpand = (suite, prk, label, info, len) => N.hkdfExpand(N.sha256, prk, concat(i2osp(len, 2), HPKE_V1, suite, te.encode(label), info), len);

  const randomBytes = (n) => {
    if (!window.crypto || typeof window.crypto.getRandomValues !== 'function') throw new Error('no CSPRNG');
    return window.crypto.getRandomValues(new Uint8Array(n));
  };

  function encap(pkR, ikmE) {
    // DeriveKeyPair(ikmE) when a test vector supplies ikmE; otherwise a fresh random key.
    let skE;
    if (ikmE) {
      const prk = labeledExtract(KEM_SUITE, new Uint8Array(0), 'dkp_prk', ikmE);
      skE = labeledExpand(KEM_SUITE, prk, 'sk', new Uint8Array(0), 32);
    } else {
      skE = randomBytes(32);
    }
    const pkE = N.x25519.getPublicKey(skE);
    const dh = N.x25519.getSharedSecret(skE, pkR); // throws on low-order / all-zero output
    skE.fill(0);
    const kemContext = concat(pkE, pkR);
    const eaePrk = labeledExtract(KEM_SUITE, new Uint8Array(0), 'eae_prk', dh);
    const shared = labeledExpand(KEM_SUITE, eaePrk, 'shared_secret', kemContext, NH);
    dh.fill(0);
    return { shared, enc: pkE };
  }

  function keySchedule(shared, info) {
    const empty = new Uint8Array(0);
    const pskIdHash = labeledExtract(SUITE_ID, empty, 'psk_id_hash', empty);
    const infoHash = labeledExtract(SUITE_ID, empty, 'info_hash', info);
    const context = concat(new Uint8Array([0]), pskIdHash, infoHash);
    const secret = labeledExtract(SUITE_ID, shared, 'secret', empty);
    const key = labeledExpand(SUITE_ID, secret, 'key', context, NK);
    const nonce = labeledExpand(SUITE_ID, secret, 'base_nonce', context, NN);
    return { key, nonce };
  }

  /** Single-shot seal with empty AAD, matching cryptography's hpke.Suite.encrypt. */
  function seal(pkR, info, plaintext, ikmE) {
    if (!(pkR instanceof Uint8Array) || pkR.length !== 32) throw new Error('bad public key');
    const { shared, enc } = encap(pkR, ikmE);
    const { key, nonce } = keySchedule(shared, info);
    shared.fill(0);
    const ct = N.gcm(key, nonce, new Uint8Array(0)).encrypt(plaintext);
    key.fill(0);
    return { enc, ct };
  }

  const b64uDecode = (s) => {
    if (typeof s !== 'string' || !/^[A-Za-z0-9_-]+$/.test(s)) throw new Error('bad encoding');
    const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
    return out;
  };
  const b64uEncode = (bytes) => {
    let bin = '';
    for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };
  const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  const fingerprint = (pk) => hex(N.sha256(pk).subarray(0, 8)).match(/.{4}/g).join('-');
  const sha256Hex = (text) => hex(N.sha256(te.encode(text)));

  window.SecretDropHPKE = Object.freeze({ seal, encap, b64uDecode, b64uEncode, fingerprint, sha256Hex, hex });
})();
