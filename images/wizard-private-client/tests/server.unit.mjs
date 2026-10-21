import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import http from 'node:http';
import { Identity } from 'ehbp';
import { AttestedRelay, configFromEnv, createServer } from '../server.mjs';

const cfg = { profile: 'tinfoil', relay: 'http://relay:8090', token: 'relay-token-only', cacheSecret: 'agent-cache-secret', models: ['gpt-oss-120b'] };
const chat = { model: cfg.models[0], messages: [{ role: 'user', content: 'unit probe' }] };
async function fixture(t, options = {}, config = cfg) {
  const server = createServer(config, options);
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const url = `http://127.0.0.1:${server.address().port}`;
  return (body = chat, headers = {}) => fetch(`${url}/v1/chat/completions`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body) });
}
const response = () => new Response('{"choices":[{"message":{"content":"ok"}}]}', { headers: { 'Content-Type': 'application/json' } });

test('health and static tinfoil models never contact relay', async t => {
  const server = createServer(cfg, { fetchImpl: () => assert.fail('unexpected network') });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.equal(await (await fetch(`${base}/healthz`)).text(), 'ok');
  assert.equal((await (await fetch(`${base}/v1/models`)).json()).data[0].id, cfg.models[0]);
  assert.equal((await fetch(`${base}/attestation`)).status, 404);
  assert.equal((await fetch(`${base}/v1/chat/completions?destination=https://example.com`)).status, 404);
});

test('nonstream passes tools, tool_choice, all unknown fields and int64 literally', async t => {
  let forwarded;
  const send = await fixture(t, { attested: { request: async raw => { forwarded = raw; return response(); } } });
  const raw = '{"model":"m","messages":[],"seed":9007199254740993,"tools":[{"type":"function","function":{"name":"f"}}],"tool_choice":"auto","extension":{"x":1}}';
  assert.equal((await send(raw, { Authorization: 'Bearer attacker', 'X-Tinfoil-Enclave-Url': 'https://evil.example' })).status, 200);
  assert.ok(forwarded.includes('9007199254740993'));
  assert.deepEqual(JSON.parse(forwarded).tools, JSON.parse(raw).tools);
  assert.equal(JSON.parse(forwarded).tool_choice, 'auto');
  assert.equal(JSON.parse(forwarded).user_cache_secret, cfg.cacheSecret);
});

test('cache namespace cannot be overridden by caller', async t => {
  const send = await fixture(t, { attested: { request: () => assert.fail('must reject before network') } });
  assert.equal((await send({ ...chat, user_cache_secret: 'shared' })).status, 400);
});

test('SSE bytes and DONE are forwarded without buffering the full reply', async t => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const send = await fixture(t, { attested: { request: async () => new Response(new ReadableStream({ async start(controller) {
    controller.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'));
    await gate; controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n')); controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } }) } });
  const reply = await send({ ...chat, stream: true });
  assert.equal(reply.status, 200);
  const reader = reply.body.getReader();
  const first = new TextDecoder().decode((await reader.read()).value);
  assert.ok(first.includes('hi')); assert.ok(!first.includes('[DONE]'));
  release(); assert.ok(new TextDecoder().decode((await reader.read()).value).includes('[DONE]'));
});

for (const [name, upstream] of [
  ['relay 401', () => new Response('secret echoed by upstream', { status: 401 })],
  ['relay 500', () => new Response('provider key or prompt', { status: 500 })],
  ['redirect', () => new Response(null, { status: 302, headers: { Location: 'https://evil.example' } })],
  ['attestation failure', () => { throw new Error('sensitive attestation error details'); }],
  ['bad decrypted JSON', () => new Response('invalid')],
  ['initial stream decryption failure', () => new Response(new ReadableStream({ start(c) { c.error(new Error('bad AEAD tag')); } }), { headers: { 'Content-Type': 'text/event-stream' } })],
]) test(`${name}: one call, sanitized 502 JSON, no fallback`, async t => {
  let count = 0;
  const send = await fixture(t, { attested: { request: async () => { count++; return upstream(); } } });
  const reply = await send({ ...chat, stream: name.includes('stream') });
  assert.equal(reply.status, 502);
  assert.deepEqual(await reply.json(), { error: { message: 'Private inference relay or attestation failed', type: 'private_provider_error', code: 'relay_failed' } });
  assert.equal(count, 1);
});

for (const body of ['{bad', 'null', '[]', '{}', JSON.stringify({ ...chat, stream: 'true' })]) test(`reject invalid body ${body.slice(0, 30)}`, async t => {
  const send = await fixture(t, { attested: { request: () => assert.fail('invalid body sent') } });
  assert.equal((await send(body)).status, 400);
});

test('body size limit and content type', async t => {
  const send = await fixture(t);
  assert.equal((await send('x', { 'Content-Type': 'text/plain' })).status, 415);
  assert.equal((await send('x'.repeat(8 * 1024 * 1024 + 1))).status, 413);
});

test('passthrough forwards bearer, preserves raw chat body and proxies models', async t => {
  const calls = [];
  const server = createServer({ ...cfg, profile: 'passthrough' }, { fetchImpl: async (url, init) => { calls.push({ url, init }); return response(); } });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const raw = JSON.stringify({ ...chat, tools: [], stream: false });
  assert.equal((await fetch(`${base}/v1/chat/completions`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer caller', 'X-Tinfoil-Enclave-Url': 'evil' }, body: raw })).status, 200);
  assert.equal(calls[0].init.body, raw);
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${cfg.token}`);
  assert.equal(calls[0].init.headers['X-Tinfoil-Enclave-Url'], undefined);
  assert.equal(calls[0].init.redirect, 'error');
  assert.equal((await fetch(`${base}/v1/models`)).status, 200);
  assert.equal(calls[1].url, `${cfg.relay}/v1/models`);
});

test('attestation GET is authenticated, verification precedes transport, requests are relay-bound', async () => {
  const events = [];
  const bundle = { domain: 'inf.test.tinfoil.sh' };
  const relay = new AttestedRelay(cfg, {
    fetchImpl: async (url, init) => { events.push('fetch'); assert.equal(url, `${cfg.relay}/attestation`); assert.equal(init.headers.Authorization, `Bearer ${cfg.token}`); assert.equal(init.redirect, 'error'); return Response.json(bundle); },
    verifierFactory: () => ({ verifyBundle: async b => { events.push('verify'); assert.deepEqual(b, bundle); return { hpkePublicKey: 'ab12' }; }, getVerificationDocument: () => ({ securityVerified: true, enclaveHost: bundle.domain }) }),
    transportFactory: async (key, host) => { events.push('transport'); assert.equal(key, 'ab12'); assert.equal(host, 'relay:8090'); return { request: async (url, init) => { assert.equal(url, `${cfg.relay}/v1/chat/completions`); assert.equal(init.redirect, 'error'); assert.equal(init.headers['X-Tinfoil-Enclave-Url'], 'https://inf.test.tinfoil.sh'); return response(); } }; },
  });
  await Promise.all([relay.request('{}'), relay.request('{}')]);
  assert.deepEqual(events, ['fetch', 'verify', 'transport']);
});

for (const kind of ['tampered', 'unverified', 'no-key', 'wrong-host', 'foreign-domain']) test(`attestation ${kind} never creates an EHBP transport`, async () => {
  const domain = kind === 'foreign-domain' ? 'evil.example' : 'inf.test.tinfoil.sh';
  const relay = new AttestedRelay(cfg, {
    fetchImpl: async () => Response.json({ domain }),
    verifierFactory: () => ({ verifyBundle: async () => { if (kind === 'tampered') throw new Error('signature mismatch'); return { hpkePublicKey: kind === 'no-key' ? '' : 'ab12' }; }, getVerificationDocument: () => ({ securityVerified: kind !== 'unverified', enclaveHost: kind === 'wrong-host' ? 'other.tinfoil.sh' : domain }) }),
    transportFactory: () => assert.fail('must not instantiate transport'),
  });
  await assert.rejects(relay.request('{}'));
});

test('failed attestation can recover only through fresh verification', async () => {
  let calls = 0;
  const relay = new AttestedRelay(cfg, { fetchImpl: async () => { calls++; return new Response('', { status: 503 }); } });
  await assert.rejects(relay.ready()); await assert.rejects(relay.ready()); assert.equal(calls, 2);
});

test('real EHBP transport seals bodies before network and does not accept plaintext success', async t => {
  const hpkePublicKey = await (await Identity.generate()).getPublicKeyHex();
  const captures = [];
  const fakeRelay = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    captures.push({ headers: req.headers, body: Buffer.concat(chunks) });
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"choices":[]}');
  });
  fakeRelay.listen(0, '127.0.0.1'); await once(fakeRelay, 'listening');
  t.after(() => { fakeRelay.closeAllConnections(); fakeRelay.close(); });
  const relay = new AttestedRelay({ ...cfg, relay: `http://127.0.0.1:${fakeRelay.address().port}` }, {
    fetchImpl: async () => Response.json({ domain: 'router-0.tinfoil.sh' }),
    verifierFactory: () => ({ verifyBundle: async () => ({ hpkePublicKey }), getVerificationDocument: () => ({ securityVerified: true, enclaveHost: 'router-0.tinfoil.sh' }) }),
  });
  const raw = '{"codeword":"PRIVPROBE-unit-transport"}';
  await assert.rejects(relay.request(raw), /Missing Ehbp-Response-Nonce/);
  assert.equal(captures.length, 1);
  assert.ok(captures[0].headers['ehbp-encapsulated-key']);
  assert.equal(captures[0].headers.authorization, `Bearer ${cfg.token}`);
  assert.equal(captures[0].headers['x-tinfoil-enclave-url'], 'https://router-0.tinfoil.sh');
  assert.ok(!captures[0].body.includes(Buffer.from('PRIVPROBE-unit-transport')));
});

test('environment validates configuration, mounted secrets and generated cache scope', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pp-test-unit-'));
  try {
    const file = join(dir, 'token'); writeFileSync(file, 'test-token\n', { mode: 0o400 });
    const env = { PROFILE: 'tinfoil', RELAY_URL: cfg.relay, RELAY_TOKEN_FILE: file, MODELS: 'a,b,a' };
    const a = configFromEnv(env); const b = configFromEnv(env);
    assert.equal(a.port, 3301); assert.equal(a.token, 'test-token'); assert.notEqual(a.cacheSecret, b.cacheSecret); assert.deepEqual(a.models, ['a', 'b']);
    for (const RELAY_URL of ['ftp://relay', 'http://user:pass@relay', 'http://relay/path', 'http://relay?key=x']) assert.throws(() => configFromEnv({ ...env, RELAY_URL }));
    assert.throws(() => configFromEnv({ ...env, PROFILE: 'unknown' }));
    assert.throws(() => configFromEnv({ ...env, LISTEN_PORT: '0' }));
    assert.equal(configFromEnv({ ...env, LISTEN_HOST: '10.251.0.3' }).host, '10.251.0.3');
    for (const LISTEN_HOST of ['::', 'localhost', '10.252.0.999']) assert.throws(() => configFromEnv({ ...env, LISTEN_HOST }));
    assert.throws(() => configFromEnv({ ...env, CACHE_SECRET_FILE: join(dir, 'missing') }));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
