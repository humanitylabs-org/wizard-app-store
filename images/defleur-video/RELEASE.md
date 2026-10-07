# Release: 0.5.0-testing (piece 2 of 3: finished vertical video)

## What this release is
DeFleur Video bundles James DeFleur's DeFleur Video plugin files unchanged (`defleur/` → `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`; plugin.json declares MIT; redistributed with the author's authorization, see NOTICE). The app runs them as hash-pinned stages; Hermes makes every editorial choice; the app never calls an LLM.

New in 0.5.0:
- **`render_final(project_id)` MCP tool**, run after `apply_cuts`. In the background it chains five new or extended stages and reports resolution, duration, crop summary, caption count, delivery-gate result, words lost, and download URLs for the final MP4 and its evidence.
- **`face-crop` stage** (`face_audit.py`, written for this app): OpenCV YuNet (`/opt/models/yunet.onnx`, opencv_zoo commit f12e127, MIT, pinned by sha256 `8f2383e4…` = upstream LFS oid) on sampled frames of every kept segment. It picks one fixed crop per setup, keeps the face inside with a 15% margin and above the caption band, and writes `crop-ledger.json` in James' contract shape, an audit per setup, and an evidence PNG. If no face is found it uses a centered crop and flags it.
- **`final-render` stage**: live picture frames from `edit-map.json` and the crop ledger (`final_render.py`, written for this app), with an explicit empty visual plan because there's no motion layer. Then James' **`encode.py`** runs **unchanged**, calling his **`caption_layer.py`** on every frame (cues from the edited-audio ASR words, neutral preset, DejaVu Sans Bold), followed by `encode.py --verify-only`. The app adds a full FFmpeg decode (framemd5 + PCM), decoded-pixel crop and caption checks, and per-segment source-region correlation.
- **Final ASR and acoustic scan:** the `asr` and `acoustic-scan` stages now also accept a `final-render` job and read the audio decoded from final.mp4.
- **`delivery-gate` stage**: builds the delivery `audio-gate.json` (`final`, `decoded_final`, `final_asr`, `final_acoustic_scan`, `final_integrity`) on top of the dialogue receipt, then runs James' **`audio_gate.py --stage delivery`** unchanged.
- Image: `opencv-python-headless==4.14.0.94` added to the hash lock; YuNet fetched with `ADD --checksum`.

Not in this release: motion graphics (James' `capture.cjs` + Chromium/GSAP; piece 3), fullscreen inserts and B-roll.

## Image
- `ghcr.io/humanitylabs-org/defleur-video:0.5.0-testing` (amd64). It is built by `.github/workflows/video.yml` and pushed only after the unit tests, container tests, Runtipi lifecycle smoke, the two-app e2e and the MCP-only e2e all pass.
- The image has two layers: Ubuntu 24.04 (digest-pinned) with ffmpeg, fontconfig and DejaVu fonts, plus a separate `/opt/venv` installed with `uv pip install --require-hashes` from `requirements.lock`. The venv holds CPU-only torch 2.11.0, stable-ts 2.19.1, numpy, matplotlib, pillow, onnxruntime, and now mcp 2.0.0 with starlette/uvicorn/pydantic.
- Size: 2.49 GB on disk locally (0.4.0 was 2.25 GB; OpenCV headless and YuNet account for the difference). The alignment checkpoint downloads on first use to `/data/models/whisper/` (139 MB for `base`).

## Settings (Runtipi form fields, optional)
- `TRANSCRIBER_URL`, default `http://transcriber:8000`.
- `TRANSCRIBER_MODEL`, default `Systran/faster-whisper-small`. It must be installed in the Transcriber.
- Environment-only options: `TRANSCRIBER_API_KEY`, `VIDEO_ALIGN_MODEL` (default `base`), `VIDEO_CTC_MODEL_DIR`, `VIDEO_API_TOKEN`, and `VIDEO_PUBLIC_URL`. The last one overrides the host used in upload/download links; by default they use the Host the agent connected to.

The compose limits are unchanged: 1536 MiB memory with no swap, 2 CPUs, 64 pids, read-only root, `cap_drop: ALL`, no-new-privileges, uid 1000.

## Verified locally (2026-10-07)
- `npm test` (36 pass) and `npx tsc --noEmit` pass.
- `test-container.sh`: 25 unit tests and James' `test_audio_gate.py` pass in the image under the recipe limits (cgroup memory peak 654 MB). The HTTP stage test now continues through face-crop (no-face testsrc, so a flagged centered crop), final-render (1080×1920, 34 frames, all checks true, helper hashes for encode/caption_layer), final ASR and scan, and delivery-gate (pass, no words lost), plus 422 rejections for cross-wired jobs.
- `scripts/e2e-video-mcp.py` now goes through `render_final` on a 1920×1080 real-face fixture (a public-domain NASA portrait, pinned by hash, panned and scaled, with Kokoro speech). Result: 1080×1920 H.264/AAC, 6.12 s / 184 frames, full decode; 1 setup, face in 15/15 samples, no flags; the crop matches the ledger in decoded pixels; an independent YuNet pass on the final MP4 found the face in 8/8 frames, above the captions; 5 caption cues / 21 words; delivery gate pass; 0 words lost; `render_final` 35 s; MCP flow 98 s; video cgroup memory peak 1.23 GB of 1.5 GiB.
- `scripts/smoke-video.py` and `scripts/e2e-video-audio.py` still pass.

## Gaps
- **Motion graphics are not built** (piece 3). James' encode.py has no special "no motion" mode; it reads `picture-frames/` + `capture-full.json`, which the app writes directly from live footage, and it accepts an empty `visual-plan.json`. No caption suppressions are used.
- The final-window findings in the delivery receipt are written by the app from measurements and the final transcript, not by a listener. The gate attests that the evidence is complete and its hashes match.
- `final-render` refuses to start with less than about `frames × 450 KB + 512 MiB` of free disk (JPEG frames before encoding).
- The face audit is sampled. With several speakers in one setup, the crop holds all of them only if they fit; otherwise the run is flagged.
- `apply_cuts` writes the per-edge and per-window review notes for the gate automatically from measurements (word distances, RMS, re-ASR). The gate therefore attests that the evidence is complete and fresh, not that a human listened. Tools and docs say so.
- `acoustic-ctc` needs a CTC model bundle; none is shipped.
- Normalization runs inside the upload request (one at a time). A long 4K HEVC clip may take minutes on 2 CPUs.
- apt package versions are not locked, so rebuilds are not byte-reproducible. Python packages are hash-locked.
