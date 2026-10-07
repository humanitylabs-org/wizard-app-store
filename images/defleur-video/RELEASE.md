# Release: 0.3.0-testing (piece 1 of 3)

## What this release is
DeFleur Video now bundles James DeFleur's DeFleur Video plugin files unchanged (`defleur/` → `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`; plugin.json declares MIT). They are redistributed with the author's authorization; see `NOTICE`. No copyright line is added, because the upstream files carry none. The app runs the audio/edit half of James' workflow as durable HTTP jobs. Speech-to-text comes from the separate Transcriber store app. Alignment runs locally with stable-ts. See WORKFLOW-PARITY.md for the stage-by-stage map.

Pieces 2–3 (face/crop audit, caption_layer, 1080×1920 encode, Chromium/GSAP motion capture, delivery gate) are not in this release.

## Image
- `ghcr.io/humanitylabs-org/defleur-video:0.3.0-testing` (amd64). It is built by `.github/workflows/video.yml` and pushed only after the unit tests, container tests, Runtipi lifecycle smoke and the two-app e2e all pass.
- The image has two layers: Ubuntu 24.04 (digest-pinned) with ffmpeg, fontconfig and DejaVu fonts, plus a separate `/opt/venv`. The venv is installed with `uv pip install --require-hashes` from `requirements.lock`: CPU-only torch 2.11.0, stable-ts 2.19.1, numpy, matplotlib, pillow, onnxruntime. torch headers and tests are removed. faster-whisper is not included.
- Size: 2.21 GB on disk locally (522 MB compressed). The alignment checkpoint is not baked in; it downloads on first use to `/data/models/whisper/` (139 MB for `base`).
- James' `test_audio_gate.py` runs during the build, so a failing gate test fails the build.

## Settings (Runtipi form fields, optional)
- `TRANSCRIBER_URL`, default `http://transcriber:8000`. Inside Runtipi both apps join `runtipi_tipi_main_network`, where the compose service name resolves.
- `TRANSCRIBER_MODEL`, default `Systran/faster-whisper-small`. It must be installed in the Transcriber.
- Environment-only options: `TRANSCRIBER_API_KEY`, `VIDEO_ALIGN_MODEL` (default `base`), `VIDEO_CTC_MODEL_DIR`, `VIDEO_API_TOKEN`.

The compose limits are unchanged: 1536 MiB memory with no swap, 2 CPUs, 64 pids, read-only root, `cap_drop: ALL`, no-new-privileges, uid 1000. The measured peak with alignment model `base` is 896 MB.

## Verified locally (2026-10-07)
- `npm test` (21 pass) and `npx tsc --noEmit` pass. The tests check every pinned helper hash against the bundled bytes.
- `test-container.sh`: 23 unit tests and James' `test_audio_gate.py` pass in the image, with no network, a read-only root, uid 1000 and the 1.5 GB limit. ASR is tested against a fake Transcriber that runs on loopback inside the test.
- `scripts/smoke-video.py` uses the real Runtipi 4.8.0 compose translation and the fresh-bind permission step. It checks the HTTP lifecycle and that the preview plus the source-audio, pcm-assemble and speech-cut-audit jobs and artifacts survive restart, stop/start and recreate. With no Transcriber installed, ASR fails with an "Install the Transcriber app" message.
- `scripts/e2e-video-audio.py` runs the translated Transcriber and video recipes on one shared network. The video app reached `transcriber:8000` by DNS alias. All 11 stages ran on real Kokoro-synthesized speech. Results are summarized in WORKFLOW-PARITY.md, and the full report is in the CI artifact `video-review-verification`.

## Gaps
- `acoustic-ctc` needs a CTC model bundle; none is shipped.
- VFR sources stop at `pcm-assemble`; that needs the piece-2 PTS ledger.
- apt package versions are not locked, so rebuilds are not byte-reproducible. Python packages are hash-locked.
