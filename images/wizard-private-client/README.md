# Wizard Private Client · 0.1.0

A per-agent, in-seal OpenAI-compatible sidecar. Hermes calls this container, never the provider app directly. The provider app owns the real provider API key; this container receives only a revocable relay token. Implements [Private providers](https://github.com/humanitylabs-org/wizard-os/pull/86).

## HTTP contract

- `GET /healthz`: `200 ok`, process liveness only (not a successful-attestation claim).
- `GET /v1/models`: static `MODELS` list for `tinfoil`; relay-proxied list for `passthrough`.
- `POST /v1/chat/completions`: OpenAI JSON or `stream:true` SSE. Unknown fields, tools, tool choice, structured-output settings and int64 JSON literals survive unchanged.
- Attestation, network, upstream HTTP and initial decryption failures return **502 JSON** with a fixed, content-free error. No provider fallback, plaintext retry, redirect following or inference retry.
- Once an SSE response has begun, an error terminates the connection; HTTP cannot retroactively change a 200 into a 502. The client must treat a truncated stream as failed. No synthetic `[DONE]` is emitted.
- Invalid requests: 400; wrong content type: 415; request larger than 8 MiB: 413; unknown route: 404. Buffered replies/attestation bundles are capped at 32 MiB; requests time out after 180 seconds.

## Attestation and encryption

Pinned official `tinfoil@1.2.2` SDK, using its public `Verifier.verifyBundle` API; official `ehbp@0.3.3` transport, the same transport used by the SDK. Fetch `/attestation` from `RELAY_URL` with the relay bearer token. Verification checks the AMD report chain/signature, Sigstore provenance for the hardcoded `tinfoilsh/confidential-model-router` repository, matching measurements, and the domain-bound enclave certificate. Require `securityVerified`, a matching domain and a nonempty attested HPKE key. Construct EHBP from **only that verified key**. No unverified key endpoint, bespoke crypto or TLS-only inference path.

The SDK high-level `SecureClient` cannot directly express this build contract: it requires an HTTPS bundle URL and its bundle fetch has no bearer-token hook. The shared relay contract is an authenticated HTTP origin on a Docker-internal network. Rather than downgrading/patching the SDK or allowing direct public access, this sidecar uses its supported offline bundle verifier plus EHBP transport. Both attestation and inference remain relay-only; there is **no relay HTTP interface change**. HTTPS relay origins also work using the platform's normal CA trust.

Verification is single-flight and refreshed at least every five minutes before a new request. Any failed inference initialization discards cached verification. An expired bundle is not used after refresh fails. The verifier's own provenance/attestation policy remains authoritative; this adapter does not invent a separate freshness policy or promise that attestation removes every hardware/metadata risk.

`X-Tinfoil-Enclave-Url` is derived from the SDK-verified certificate domain, restricted to `.tinfoil.sh`. Caller auth and enclave headers are ignored. EHBP seals every inference body before network transmission and authenticates/decrypts response frames incrementally, including SSE. Relay headers, endpoint/model metadata, lengths, timing, and the relay token are not encrypted by EHBP. Keep this HTTP hop on the restricted internal network, never across an untrusted LAN or the public internet.

### Prompt-cache isolation

The current official SDK and `tinfoil-proxy --user-cache-secret` use an encrypted JSON **`user_cache_secret` body field**, not a plaintext HTTP header. This client injects that field before EHBP. `CACHE_SECRET_FILE` pins it per agent across restarts; without a mount a random 256-bit process-lifetime secret scopes the cache. Caller attempts to override the per-agent namespace are rejected. No writable home/cache directory is needed.

## Agent Service deployment contract

Image intended for first publication on merge: **`ghcr.io/humanitylabs-org/wizard-private-client:0.1.0`**. PRs test but do not publish. Add the multi-architecture digest after the main workflow publishes; don't reuse the version for later code.

| Environment | Value |
|---|---|
| `PROFILE` | `tinfoil` for attested-relay; `passthrough` for local provider |
| `RELAY_URL` | `http://wizard-tinfoil-relay:8090` or local app's relay origin (no path, query, userinfo or trailing `/v1`) |
| `RELAY_TOKEN_FILE` | `/run/wizard/relay-token` (default) |
| `LISTEN_PORT` | `3301` (default) |
| `CACHE_SECRET_FILE` | Optional `/run/wizard/cache-secret`; recommended persistent per-agent random secret |
| `MODELS` | Comma-separated model IDs advertised by the provider, e.g. `llama3-3-70b,gpt-oss-120b`; required to advertise tinfoil models (empty otherwise) |

Example compose fragment (Agent Service must set the host-file paths and network names):

```yaml
services:
  agent-example-client:
    image: ghcr.io/humanitylabs-org/wizard-private-client:0.1.0
    user: "1000:1000"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    environment:
      PROFILE: tinfoil
      RELAY_URL: http://wizard-tinfoil-relay:8090
      RELAY_TOKEN_FILE: /run/wizard/relay-token
      CACHE_SECRET_FILE: /run/wizard/cache-secret
      LISTEN_PORT: "3301"
      MODELS: llama3-3-70b,gpt-oss-120b
    volumes:
      - ${AGENT_RUNTIME}/relay-token:/run/wizard/relay-token:ro
      - ${AGENT_RUNTIME}/cache-secret:/run/wizard/cache-secret:ro
    networks: [agent-internal, provider-relay]
    # No host ports, writable volumes, internet/egress network, or provider API key.
networks:
  agent-internal:
    external: true
    name: ${AGENT_INTERNAL_NETWORK}
  provider-relay:
    external: true
    name: wizard-relay-wizard-tinfoil
```

Both mounted files must be **0400 and owned by container UID 1000** (host UID 1000 without user-namespace remapping); a root-owned 0400 bind is unreadable by this non-root image. Place them outside the Hermes-visible home. Do not mount the runtime directory as a whole. The client needs no tmpfs or writable filesystem.

Hermes: `provider: custom`, `base_url: http://agent-<id>-client:3301/v1`, `api_key: none`. Only its own Hermes container may reach port 3301. Attach the client only to its agent's internal network and `wizard-relay-<provider-app-id>` (internal, one `/24` in `10.252.0.0/16`). Only the provider relay has egress. Network creation, peer restrictions and the no-internet firewall are the Agent Service's responsibility, not a property a Dockerfile alone can enforce.

## Tests

```sh
cd images/wizard-private-client
npm ci --ignore-scripts
npm test
npm audit --omit=dev
# No API key; builds disposable test images and verifies both profiles' HTTP paths.
python3 tests/run.py
# Authorized live proof; reads the key directly into process env, never copies/prints it.
python3 tests/run.py --live --key-env-file /path/to/tinfoil.env
```

Live default: documented `llama3-3-70b`; override with `--model`. The stand-in relay in `tests/relay.py` checks the internal peer subnet and bearer token, forwards attestation from ATC, forwards ciphertext to the attested enclave, adds the real provider key there only, and preserves EHBP headers. **TEST ONLY**: it captures encrypted request bytes; production relays must never capture bodies. Its mock mode supports offline passthrough CI without contacting a model.

The runner uses `pp-test-client` (internal, `10.252.251.0/24`) and `pp-test-client-egress`; only the relay joins egress. It checks non-root/read-only/capabilities, blocks direct internet, probes both live response modes, scans the exact forwarded bytes for a random codeword and cache secret, then checks tampered attestation, a wrong certificate domain, a wrong forwarded enclave, invalid token, stopped relay, static models and passthrough SSE/JSON. All test containers, networks, tagged images and capture/token scratch are removed in `finally`. Run one instance at a time. Docker's build cache/base images may remain; no model downloads or production state are touched.

The unit suite additionally tests real EHBP sealing and rejection of a successful *plaintext* upstream response, exact field/number preservation, cache namespace ownership, invalid inputs, single-flight verification, sanitized errors and incremental SSE before upstream EOF.

CI builds on PRs without secrets or publication. Main/manual workflow runs the same checks, publishes amd64+arm64, then rechecks the published runtime. Live provider verification is intentionally operator-triggered, not a credentialed PR job.
