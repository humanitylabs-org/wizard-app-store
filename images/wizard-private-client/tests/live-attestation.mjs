// Key-free live evidence: authenticated HTTP relay -> real ATC bundle -> real
// Verifier.verifyBundle -> EHBP ciphertext, never a paid inference request.
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { AttestedRelay } from '../server.mjs';

const response = await fetch('https://atc.tinfoil.sh/attestation', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ enclaveUrl: 'https://inference.tinfoil.sh', repo: 'tinfoilsh/confidential-model-router' }),
  signal: AbortSignal.timeout(30000),
});
assert.equal(response.status, 200);
const genuine = await response.json();
assert.equal(genuine.domain, 'inference.tinfoil.sh');
let bundle = genuine, attestations = 0, posts = 0;
const probe = 'PRIVPROBE-key-free-live-attestation';
const server = http.createServer(async (request, reply) => {
  assert.equal(request.headers.authorization, 'Bearer synthetic-internal-relay-token');
  if (request.method === 'GET' && request.url === '/attestation') {
    attestations++; reply.setHeader('Content-Type', 'application/json'); reply.end(JSON.stringify(bundle)); return;
  }
  assert.equal(request.method, 'POST'); assert.equal(request.url, '/v1/chat/completions');
  assert.equal(request.headers['x-tinfoil-enclave-url'], 'https://inference.tinfoil.sh');
  assert.ok(request.headers['ehbp-encapsulated-key']);
  const chunks = []; for await (const part of request) chunks.push(part);
  assert.equal(Buffer.concat(chunks).includes(Buffer.from(probe)), false);
  posts++;
  // Do not forward to the model: this test consumes no provider key or credit.
  reply.writeHead(401); reply.end('synthetic refusal after proven sealing');
});
server.listen(0, '127.0.0.1'); await once(server, 'listening');
const config = { relay: `http://127.0.0.1:${server.address().port}`, token: 'synthetic-internal-relay-token' };
const payload = Buffer.from(JSON.stringify({ model: 'kimi-k3', messages: [{ role: 'user', content: probe }] }));
try {
  const client = new AttestedRelay(config);
  const sealed = await client.request(payload);
  assert.equal(sealed.status, 401); assert.equal(attestations, 1); assert.equal(posts, 1);
  bundle = { ...genuine, domain: 'foreign.invalid' };
  await assert.rejects(new AttestedRelay(config).request(payload));
  assert.equal(attestations, 2); assert.equal(posts, 1);
  console.log(JSON.stringify({ atcStatus: 200, enclaveHost: genuine.domain, authenticatedHttpAttestation: true, verifyBundleAccepted: true, ehbpSealedBeforeRelay: true, tamperedBundleBlockedBeforeTransport: true, paidInferenceRequests: 0 }));
} finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
