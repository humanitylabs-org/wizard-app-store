# Release: 0.4.0-testing (piece 1 of 3, now agent-ready over MCP)

## What this release is
DeFleur Video bundles James DeFleur's DeFleur Video plugin files unchanged (`defleur/` → `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`; plugin.json declares MIT). They are redistributed with the author's authorization; see `NOTICE`. No copyright line is added, because the upstream files carry none. The app runs the audio/edit half of James' workflow as durable HTTP jobs. Speech-to-text comes from the separate Transcriber store app, and alignment runs locally with stable-ts. See WORKFLOW-PARITY.md for the stage-by-stage map.

New in 0.4.0:
- **MCP endpoint at `/mcp`** (Streamable HTTP) on the same port 8787. The official `mcp` Python SDK 2.0.0, hash-locked in `/opt/venv`, runs on loopback port 8788; `service.py` starts and supervises it and proxies `/mcp` to it. `VIDEO_API_TOKEN`, when set, applies as bearer auth on `/mcp` too. There are 8 self-describing tools: `workflow_guide`, `capabilities`, `create_upload`, `start_edit`, `apply_cuts`, `get_status`, `list_projects` and `delete_project`. They call the existing HTTP API on loopback, so no pipeline logic is duplicated. Long work runs as a background chain, and `get_status` waits up to ~55 s per call. The app still makes no LLM calls.
- **One-time upload URLs** (`POST /v1/uploads` → `POST /v1/uploads/<token>`, 30 min, single use) and a minimal page at `GET /upload` with no external assets.
- **Normalization on upload**: HEVC or variable-frame-rate sources are re-encoded to H.264 CFR (libx264 crf 18, AAC 48 kHz), scaled to fit 1080p if needed. The original's SHA-256, codec and frame-rate mode are recorded in the project's `original`/`normalization` provenance. The normalized file is the edit source; the original bytes are not kept.
- `GET /v1/projects` lists projects. The HTTP server is now threaded, because the MCP process calls back into it. Every existing route and `client.py` is unchanged.

Pieces 2–3 (face/crop audit, caption_layer, 1080×1920 encode, Chromium/GSAP motion capture, delivery gate) are not in this release.

## Image
- `ghcr.io/humanitylabs-org/defleur-video:0.4.0-testing` (amd64). It is built by `.github/workflows/video.yml` and pushed only after the unit tests, container tests, Runtipi lifecycle smoke, the two-app e2e and the MCP-only e2e all pass.
- The image has two layers: Ubuntu 24.04 (digest-pinned) with ffmpeg, fontconfig and DejaVu fonts, plus a separate `/opt/venv` installed with `uv pip install --require-hashes` from `requirements.lock`. The venv holds CPU-only torch 2.11.0, stable-ts 2.19.1, numpy, matplotlib, pillow, onnxruntime, and now mcp 2.0.0 with starlette/uvicorn/pydantic.
- Size: 2.25 GB on disk locally. The alignment checkpoint downloads on first use to `/data/models/whisper/` (139 MB for `base`).

## Settings (Runtipi form fields, optional)
- `TRANSCRIBER_URL`, default `http://transcriber:8000`.
- `TRANSCRIBER_MODEL`, default `Systran/faster-whisper-small`. It must be installed in the Transcriber.
- Environment-only options: `TRANSCRIBER_API_KEY`, `VIDEO_ALIGN_MODEL` (default `base`), `VIDEO_CTC_MODEL_DIR`, `VIDEO_API_TOKEN`, and `VIDEO_PUBLIC_URL`. The last one overrides the host used in upload/download links; by default they use the Host the agent connected to.

The compose limits are unchanged: 1536 MiB memory with no swap, 2 CPUs, 64 pids, read-only root, `cap_drop: ALL`, no-new-privileges, uid 1000.

## Verified locally (2026-10-07)
- `npm test` (36 pass) and `npx tsc --noEmit` pass.
- `test-container.sh`: 25 unit tests and James' `test_audio_gate.py` pass in the image. The new tests cover one-time upload URLs, the upload page, and HEVC/VFR normalization with provenance.
- Hermes' own client works: `hermes mcp add defleur-video --url http://127.0.0.1:<port>/mcp`, then `hermes mcp test defleur-video` reported "Connected" and "Tools discovered: 8". A token-protected container returned 401 on `/mcp` without the token and 200 with it.
- `scripts/e2e-video-mcp.py` (new) drives the translated Transcriber and video recipes only through MCP tool calls plus the curl command from `create_upload`. On the Kokoro speech fixture, `start_edit` proposed cutting the "um" plus the following pause, and the trailing silence. `apply_cuts` removed 1.62 s of 7.74 s. The edited re-ASR has no "um", there were 0 words lost and 0 added, the cut audit passed and the dialogue gate passed. An HEVC copy of the fixture was normalized to H.264 CFR (original SHA-256 recorded) and transcribed with nothing missing. MCP flow wall time was 35.5 s; the video container's cgroup peak was 1.08 GB of 1.5 GB.
- `scripts/smoke-video.py` and `scripts/e2e-video-audio.py` still pass.

## Gaps
- `apply_cuts` writes the per-edge and per-window review notes for the gate automatically from measurements (word distances, RMS, re-ASR). The gate therefore attests that the evidence is complete and fresh, not that a human listened. Tools and docs say so.
- `acoustic-ctc` needs a CTC model bundle; none is shipped.
- Normalization runs inside the upload request (one at a time). A long 4K HEVC clip may take minutes on 2 CPUs.
- apt package versions are not locked, so rebuilds are not byte-reproducible. Python packages are hash-locked.
