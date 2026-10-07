# DeFleur Video API (0.3.0-testing)

HTTP service that runs the audio/edit half (piece 1 of 3) of James DeFleur's DeFleur Video workflow. James' plugin files ship unchanged in `defleur/` (installed at `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`, MIT per plugin.json, redistributed with the author's authorization; see [NOTICE](NOTICE)). Hermes or any HTTP client is the editor; the service never calls an LLM. Speech-to-text comes from the separate **Transcriber** store app (`TRANSCRIBER_URL`, default `http://transcriber:8000`); word alignment runs locally with stable-ts on CPU.

- Operator guide: [HERMES.md](HERMES.md). Stage map and measurements: [WORKFLOW-PARITY.md](WORKFLOW-PARITY.md). Release record: [RELEASE.md](RELEASE.md). The older 9:16 preview: [EDITING.md](EDITING.md).
- James' SKILL.md files and references are served read-only at `GET /v1/workflow/docs` and `GET /v1/workflow/docs/{name}` (`client.py docs`).
- Stages: `POST /v1/projects/{id}/stages/{source-audio|resolve-preset|preflight|asr|align|acoustic-ctc|pcm-assemble|speech-cut-audit|acoustic-scan|dialogue-gate|validate-project}`. Inputs are JSON and job ids only, never paths, shell commands or filters. Each job lists its artifacts with SHA-256; later stages re-check those hashes before they read anything.

## Run locally

For the workflow stages outside the image, set `DEFLEUR_ROOT` to `defleur/` and `VIDEO_HELPER_PYTHON` to a venv built from `requirements.lock`. The legacy preview requires Linux, Python 3.11+, FFmpeg/ffprobe with `fd` protocol, drawtext, libx264 and AAC, `prlimit`, and DejaVu Sans Mono. The image guarantees the caption font exists via `fonts-dejavu-core` when needed. Verified on Ubuntu 24.04 / FFmpeg 6.1.1. From this directory:

```sh
export VIDEO_API_TOKEN="$(openssl rand -hex 24)"
export VIDEO_DATA_DIR="$PWD/.local-data"
python3 service.py
```

Do not commit `.local-data` or credentials. The default listener is loopback port 8787. To use a container, build from this directory:

```sh
docker build -t wizard-defleur-video:0.3.0-testing .
```

Published amd64 image: `ghcr.io/humanitylabs-org/defleur-video:0.3.0-testing` (listed in the store as a testing app). It owns `/data` with no Hermes dependency, Docker socket or host agent directories. The workflow builds only this directory; its allowlisted context excludes vendor source, Git history, evidence and user data. Publication and public registry visibility are separate steps. Local tests are not a completed Runtipi dashboard install.

**Fresh-bind permissions:** Runtipi 4.8.0's actual translator is exercised by the lifecycle smoke. `uid`/`gid` metadata does not chown the bind. Runtipi runs `chmod -Rf a+rwx` on app data **after** Compose starts; initial permission failures can precede the translated `unless-stopped` restart. The resulting data root is broadly writable and lifecycle operations may also broaden existing file permissions. Keep this a private, single-owner host. For manual deployment, provision the bind for container UID/GID 1000 before starting, accounting for rootless user-namespace mapping. `exposable:false` is not a firewall: opening the app port can publish it on all host interfaces.

## Supported API v1

All routes except `GET /healthz` require `Authorization: Bearer <VIDEO_API_TOKEN>`. Token must contain at least 32 non-whitespace ASCII characters. No CORS or cookie authentication. Keep it on loopback/private networks behind appropriate TLS/access control. It is single-owner, not multi-tenant, and uses a development stdlib HTTP server, not an internet-hardened gateway.

| Method / route | Input | Output |
| --- | --- | --- |
| `GET /healthz` | None | Version/liveness only (not render-worker readiness) |
| `GET /v1/capabilities` | Bearer | Exact supported operations, budgets, missing delivery gates |
| `POST /v1/projects` | Raw `video/mp4`, one Content-Length | `201` project ID, hash, metadata, unmet gates |
| `GET /v1/projects/{id}` | Bearer | Persisted source metadata |
| `POST /v1/projects/{id}/previews` | `application/json` edit plan, Content-Length | `202` persistent job |
| `POST /v1/projects/{id}/stages/{operation}` | Stage JSON (≤1 MiB) | Durable piece-1 stage job (see HERMES.md) |
| `GET /v1/jobs/{id}/stage-artifacts/{name}` | Manifest-allowlisted name | Exact hashed stage JSON/WAV/PNG |
| `GET /v1/workflow/docs[/{name}]` | Allowlisted name | James' SKILL.md / references / NOTICE, read-only |
| `GET /v1/jobs/{id}` | Bearer | State, submitted plan, result checksum/evidence or error |
| `GET /v1/jobs/{id}/preview` | Bearer | Exact MP4 attachment once `needs_review`; otherwise `409` |
| `DELETE /v1/projects/{id}` | Bearer | Deletes original, previews and job rows; refuses active work |

Plan shape follows the recovered DeFleur project contract:

```json
{"segments":[{"start_s":0,"end_s":0.6,"reason":"Retain the premise"},{"start_s":1.1,"end_s":1.8,"reason":"Retain the conclusion"}]}
```

Submit real source-specific reasons; these intervals merely illustrate syntax. Segments must be ordered, nonoverlapping, within the actual source, at least 0.1 seconds long, and number one through eight. Unknown keys, strings as numbers, booleans, nonfinite numbers and arbitrary filter expressions are rejected. Human/AI editorial judgments remain the caller's responsibility; this API does not certify faithful meaning or phonetic cut safety.

Errors are JSON: `401` missing/wrong token, `404` absent target, `409` preview unavailable or artifact hash changed, `422` unsupported media, malformed input or exhausted quota, `500` internal failure. Limits are deliberately strict, not negotiated. Version 0.3 is experimental; incompatible changes require a new major route or an explicit migration before promotion. Preview JSON is limited to 64 KiB; stage JSON to 1 MiB. Chunked uploads and source URLs are not supported. Downloads currently return complete attachments, not byte-range streaming.

Example requests, after starting the service:

```sh
curl --fail -H "Authorization: Bearer $VIDEO_API_TOKEN" \
  -H 'Content-Type: video/mp4' --data-binary @source.mp4 \
  http://127.0.0.1:8787/v1/projects
# Use the returned project ID; edit-plan.json must refer to that source.
curl --fail -H "Authorization: Bearer $VIDEO_API_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @edit-plan.json \
  "http://127.0.0.1:8787/v1/projects/$PROJECT_ID/previews"
curl --fail -H "Authorization: Bearer $VIDEO_API_TOKEN" \
  "http://127.0.0.1:8787/v1/jobs/$JOB_ID"
curl --fail -H "Authorization: Bearer $VIDEO_API_TOKEN" \
  "http://127.0.0.1:8787/v1/jobs/$JOB_ID/preview" -o review-preview.mp4
```

## State and review contract

- SQLite transactions commit/rollback and always close. SQLite owns project metadata and immutable job plans/results; server-generated IDs alone form paths. Source bytes never change. One data-directory process lock prevents a second worker from resetting active jobs.
- Job states: `queued -> running -> needs_review | failed`. A process restart marks interrupted queued/running jobs failed rather than silently replaying them. Submit a new job explicitly. Completed receipts survive restart.
- Every successful encode has `delivery_approved: false`, a technical-only scope string and the complete list of unmet pilot gates. The service has **no approval or final-delivery route**. It cannot fabricate audio-lock receipts or declare creative success from an FFmpeg exit code.
- Output: 270×480, 24 fps, H.264/AAC MP4, full source letterboxed by default; optional externally asserted protected-region crop and timed caption burns are described in EDITING.md. Numeric duration check, first-frame decoding and full exact-file decoding are recorded with SHA-256. This legacy preview is not upstream motion/encode parity. Separately, the pcm-assemble stage executes the actual sample-accurate upstream helper for verified CFR; VFR picture custody remains unsupported.

## Resource and input boundaries

- Input <=512 MiB, <=300 seconds, <=1920 per axis and <=2,073,600 pixels. Exactly one H.264 video stream and one AAC mono/stereo audio stream. MP4 only; MOV, WebM, fragmented MP4 and external/reference/compressed movies are rejected.
- Structural MP4 inspection precedes native parsing: bounded box depth/count, self-contained data references, skipped payload bytes. Native input is a pinned private descriptor with forced MOV demuxer and **fd-only** protocol whitelist, not a caller pathname or URL.
- Native child: 1 GiB address-space limit, 90 CPU seconds, 32 MiB preview output file / 128 MiB workflow-stage output file, 256 KiB combined stdout/stderr, fixed wall deadlines, 64 descriptors, one codec/filter thread, minimal environment. No shell. Timeouts kill and reap the native process group.
- Service: one render worker, at most two active/queued jobs, eight retained projects, 32 retained jobs and 16 decisions/project. Upload admission reserves the upload size plus 256 MiB; preview admission reserves 256 MiB and workflow-stage admission 512 MiB. Legacy preview total output remains <=60s; source/PCM stages accept longer sources. Entire render/evidence chain shares a 180s deadline. Native upload probing may overlap a render; the container's total memory/CPU cap is the final aggregate limit. Quotas bound normal retained data but do not replace filesystem quotas or crash-orphan maintenance before production use.
- Container: 1536 MiB memory, equal memory+swap limit (no swap), two CPU equivalents, 64 processes, non-root, read-only root, all capabilities dropped, no-new-privileges. Native limits alone are **not** a security sandbox. API has no network-fetch operations; a deployment-level egress policy is still recommended.

## Verification

From repository root:

```sh
npm ci
npm test && npx tsc --noEmit
python3 -W error::ResourceWarning -m unittest discover -s images/defleur-video -v
sh images/defleur-video/test-container.sh
python3 scripts/smoke-video.py
```

`test-container.sh` builds locally then runs the real authenticated HTTP and FFmpeg tests as UID 1000 with `--network none`, read-only root and enforced resource limits. It prints actual cgroup limits and memory peak, and removes its test container. It does not deploy anything or use real customer footage.

Set `VIDEO_TEST_ARTIFACTS` to a new private absolute directory for host tests to retain synthetic sources, previews, receipts and `editing-review/index.html` with audio/PNG evidence. Test output is synthetic color and sine tones—not the original pilot fixture or a meaningful speech-quality assessment. The lifecycle smoke executes the pinned actual Runtipi builder and mirrors its verified permission step on disposable data, renders over real HTTP and verifies restart/stop-start/recreation persistence. It uses a disposable bridge and loopback port, not an owner deployment. Public translator sources are fetched into scratch for testing, never packaged. This is not a full Runtipi installation.

Remaining production work: crash-orphan reconciliation, filesystem quotas, ingress throttling/TLS, package/SBOM/security review, and meaningful speech/creative review. The base image is digest-pinned but apt versions are not locked; rebuilds are not byte-reproducible.
