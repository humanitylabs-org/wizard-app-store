// Runs the exact browser files (static/noble-crypto.js + static/hpke.js) in Node's vm,
// checks the KEM against RFC 9180 A.1 (X25519) and emits sealed fixtures for Python.
// Usage: node hpke_node.mjs <recipient_pk_b64url> <info> <plaintext>...
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const dir = new URL('../static/', import.meta.url);
const ctx = { TextEncoder, Uint8Array, atob, btoa, crypto: { getRandomValues: (a) => webcrypto.getRandomValues(a) } };
ctx.window = ctx;
vm.createContext(ctx);
for (const f of ['noble-crypto.js', 'hpke.js']) vm.runInContext(readFileSync(new URL(f, dir), 'utf8'), ctx, { filename: f });
const H = ctx.window.SecretDropHPKE;
const fromHex = (h) => Uint8Array.from(h.match(/../g).map((b) => parseInt(b, 16)));

// RFC 9180 A.1.1: DHKEM(X25519, HKDF-SHA256) shared_secret and enc for fixed ikmE.
const v = {
  ikmE: '7268600d403fce431561aef583ee1613527cff655c1343f29812e66706df3234',
  pkRm: '3948cfe0ad1ddb695d780e59077195da6c56506b027329794ab02bca80815c4d',
  enc: '37fda3567bdbd628e88668c3c8d7e97d1d1253b6d4ea6d44c150f741f1bf4431',
  shared: 'fe0e18c9f024ce43799ae393c7e8fe8fce9d218875e8227b0187c04e7d2ea1fc',
};
const kem = H.encap(fromHex(v.pkRm), fromHex(v.ikmE));
const kemOk = H.hex(kem.enc) === v.enc && H.hex(kem.shared) === v.shared;

let lowOrderRejected = false;
try { H.seal(new Uint8Array(32), new TextEncoder().encode('x'), new Uint8Array([1])); } catch { lowOrderRejected = true; }

const [pk, info, ...plaintexts] = process.argv.slice(2);
const sealed = plaintexts.map((p) => {
  const s = H.seal(H.b64uDecode(pk), new TextEncoder().encode(info), new TextEncoder().encode(p));
  return { enc: H.b64uEncode(s.enc), ct: H.b64uEncode(s.ct) };
});
process.stdout.write(JSON.stringify({ kemOk, lowOrderRejected, sealed,
  fingerprint: pk ? H.fingerprint(H.b64uDecode(pk)) : null, sha256: H.sha256Hex('abc') }));
