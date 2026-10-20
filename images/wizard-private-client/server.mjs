import http from 'node:http';
import { readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';
import { Verifier } from 'tinfoil';
import { Identity, Transport } from 'ehbp';

const MAX_BODY = 8 * 1024 * 1024;
const MAX_REPLY = 32 * 1024 * 1024;
const CONFIG_REPO = 'tinfoilsh/confidential-model-router';
const PUBLIC_ERROR = { error: { message: 'Private inference relay or attestation failed', type: 'private_provider_error', code: 'relay_failed' } };

function secretFile(path) {
  const value = readFileSync(path, 'utf8').trim();
  if (!value || /[\r\n]/.test(value)) throw new Error('Invalid secret file');
  return value;
}

export function configFromEnv(env = process.env) {
  const profile = env.PROFILE;
  if (!['tinfoil', 'passthrough'].includes(profile)) throw new Error('Invalid PROFILE');
  const relay = new URL(env.RELAY_URL);
  if (!['http:', 'https:'].includes(relay.protocol) || relay.username || relay.password || relay.search || relay.hash || relay.pathname !== '/') throw new Error('RELAY_URL must be an HTTP(S) origin');
  const port = Number(env.LISTEN_PORT ?? 3301);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid LISTEN_PORT');
  return {
    profile, relay: relay.origin, port,
    token: secretFile(env.RELAY_TOKEN_FILE ?? '/run/wizard/relay-token'),
    cacheSecret: env.CACHE_SECRET_FILE ? secretFile(env.CACHE_SECRET_FILE) : randomBytes(32).toString('hex'),
    models: [...new Set((env.MODELS ?? '').split(',').map(s => s.trim()).filter(Boolean))],
  };
}

async function boundedBody(body, max, status = 502) {
  const chunks = [];
  let size = 0;
  for await (const chunk of body ?? []) {
    size += chunk.length;
    if (size > max) throw Object.assign(new Error('Body too large'), { status });
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function enclaveOrigin(domain) {
  // Bundle domain is verified against the attested enclave certificate by the SDK.
  const url = new URL(`https://${domain}`);
  if (url.hostname !== domain || !domain.endsWith('.tinfoil.sh') || url.port || url.pathname !== '/' || url.username || url.password || url.search || url.hash) throw new Error('Invalid enclave domain');
  return url.origin;
}

export class AttestedRelay {
  constructor(config, { fetchImpl = fetch, verifierFactory = () => new Verifier({ configRepo: CONFIG_REPO }), transportFactory = async (key, host) => new Transport(await Identity.fromPublicKeyHex(key), host) } = {}) {
    this.config = config;
    this.fetchImpl = fetchImpl;
    this.verifierFactory = verifierFactory;
    this.transportFactory = transportFactory;
  }
  async ready() {
    if (this.verified && Date.now() < this.expires) return this.verified;
    if (!this.pending) {
      this.pending = this.initialize().then(value => {
        this.verified = value;
        this.expires = Date.now() + 5 * 60_000;
        return value;
      }).finally(() => { this.pending = undefined; });
    }
    return this.pending;
  }
  async initialize() {
    // SecureClient's high-level bundle fetch has no auth hook and requires HTTPS.
    // Use the SDK's public offline Verifier API for this authenticated relay route.
    // No transport downgrade, patched SDK, or unverified key discovery is used.
    const response = await this.fetchImpl(`${this.config.relay}/attestation`, {
      headers: { Authorization: `Bearer ${this.config.token}` },
      redirect: 'error', signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) throw new Error('Attestation relay failed');
    const bundle = JSON.parse((await boundedBody(response.body, MAX_REPLY)).toString('utf8'));
    const enclave = enclaveOrigin(bundle.domain);
    const verifier = this.verifierFactory();
    const result = await verifier.verifyBundle(bundle);
    const doc = verifier.getVerificationDocument();
    if (!doc?.securityVerified || doc.enclaveHost !== bundle.domain || !result.hpkePublicKey || !/^(?:[a-f0-9]{2})+$/i.test(result.hpkePublicKey)) throw new Error('Attestation not verified');
    const transport = await this.transportFactory(result.hpkePublicKey, new URL(this.config.relay).host);
    return { enclave, transport };
  }
  async request(raw, signal) {
    try {
      const { enclave, transport } = await this.ready();
      return await transport.request(`${this.config.relay}/v1/chat/completions`, {
        method: 'POST', body: raw, redirect: 'error', signal,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.config.token}`, 'X-Tinfoil-Enclave-Url': enclave },
      });
    } catch (error) {
      this.verified = undefined;
      throw error; // Never retry a chat request, and never send a plaintext request.
    }
  }
}

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

export function createServer(config, { fetchImpl = fetch, attested = new AttestedRelay(config) } = {}) {
  return http.createServer(async (req, res) => {
    const abort = new AbortController();
    res.on('close', () => abort.abort());
    const signal = AbortSignal.any([abort.signal, AbortSignal.timeout(180_000)]);
    try {
      if (req.method === 'GET' && req.url === '/healthz') {
        res.writeHead(200, { 'Content-Type': 'text/plain' }); res.end('ok'); return;
      }
      if (req.method === 'GET' && req.url === '/v1/models' && config.profile === 'tinfoil') {
        json(res, 200, { object: 'list', data: config.models.map(id => ({ id, object: 'model', owned_by: 'tinfoil' })) }); return;
      }
      const isChat = req.method === 'POST' && req.url === '/v1/chat/completions';
      const isModels = req.method === 'GET' && req.url === '/v1/models';
      if (!isChat && !isModels) { json(res, 404, { error: { message: 'Not found' } }); return; }
      let raw;
      let streaming = false;
      if (isChat) {
        if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] ?? '')) { json(res, 415, { error: { message: 'Expected application/json' } }); return; }
        raw = (await boundedBody(req, MAX_BODY, 413)).toString('utf8');
        let body;
        try { body = JSON.parse(raw); } catch { json(res, 400, { error: { message: 'Invalid JSON' } }); return; }
        if (!body || typeof body !== 'object' || Array.isArray(body) || typeof body.model !== 'string' || !Array.isArray(body.messages) || (body.stream !== undefined && typeof body.stream !== 'boolean')) { json(res, 400, { error: { message: 'Invalid chat completion request' } }); return; }
        streaming = body.stream === true;
        if (config.profile === 'tinfoil') {
          if (Object.hasOwn(body, 'user_cache_secret') && body.user_cache_secret !== config.cacheSecret) { json(res, 400, { error: { message: 'Cache namespace is managed by this client' } }); return; }
          if (!Object.hasOwn(body, 'user_cache_secret')) {
            // Splice, don't re-serialize: int64 seed/tool values must survive exactly.
            const end = raw.lastIndexOf('}');
            raw = raw.slice(0, end) + `,"user_cache_secret":${JSON.stringify(config.cacheSecret)}` + raw.slice(end);
          }
        }
      }
      const upstream = config.profile === 'tinfoil'
        ? await attested.request(raw, signal)
        : await fetchImpl(`${config.relay}${req.url}`, {
          method: req.method, body: raw, redirect: 'error', signal,
          headers: { Authorization: `Bearer ${config.token}`, ...(isChat ? { 'Content-Type': 'application/json' } : {}) },
        });
      if (!upstream.ok) { await upstream.body?.cancel(); throw new Error('Relay rejected request'); }
      if (!streaming) {
        const body = await boundedBody(upstream.body, MAX_REPLY);
        // Read/decrypt the complete body before committing a success status.
        JSON.parse(body.toString('utf8'));
        res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
        res.end(body);
      } else {
        if (!upstream.headers.get('content-type')?.startsWith('text/event-stream') || !upstream.body) throw new Error('Invalid SSE response');
        const reader = upstream.body.getReader();
        // Initial decryption/network errors are still a 502 JSON, not a false 200.
        const first = await reader.read();
        if (first.done) throw new Error('Empty SSE response');
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
        const stream = Readable.from((async function* () {
          try {
            yield first.value;
            while (true) { const next = await reader.read(); if (next.done) break; yield next.value; }
          } finally { await reader.cancel().catch(() => {}); }
        })());
        // pipeline applies backpressure. A late fault destroys the socket; never emit DONE.
        await pipeline(stream, res, { signal });
      }
    } catch (error) {
      if (res.headersSent) { res.destroy(); return; }
      json(res, error.status === 413 ? 413 : 502, error.status === 413 ? { error: { message: 'Request too large' } } : PUBLIC_ERROR);
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const config = configFromEnv();
    const server = createServer(config);
    server.listen(config.port, '0.0.0.0');
    for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => { server.close(); server.closeAllConnections(); });
  } catch {
    console.error('Private client configuration invalid');
    process.exitCode = 1;
  }
}
