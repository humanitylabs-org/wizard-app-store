# Workflow parity: James DeFleur's DeFleur Video → this app

James' plugin is bundled unchanged at `/opt/defleur`: upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`, licensed MIT per its plugin.json, and redistributed with the author's authorization (see NOTICE). Each script's SHA-256 is pinned in `workflow.py`, checked before every run and recorded in every job. Hermes is the operator. The app runs helpers only on paths it owns; clients never supply paths.

The port is split into three pieces. **Piece 1 (audio/edit) is done (0.3.0-testing). 0.4.0-testing adds an MCP endpoint whose `start_edit`/`apply_cuts` tools chain these stages for an agent, plus H.264/CFR normalization of HEVC/VFR uploads. Piece 3 (motion graphics, inserts, multi-setup reframing) is done in 0.6.0-testing. Piece 2 (0.5.0-testing) adds the face audit and fixed crop, captions, the 1080×1920 encode and the delivery gate, chained by the `render_final` MCP tool. Piece 3, motion graphics, is not built.**

| James' step | Helper | Stage | Status |
|---|---|---|---|
| Source probe, CFR/VFR check | `probe_source.py` | `source-audio` | Done. VFR uploads are normalized to CFR on upload (0.4.0), so the edit source is CFR; a VFR file that reaches PCM assembly some other way is still refused. |
| Lossless 48 kHz source PCM | ffmpeg decode | `source-audio` | Done |
| Preset resolution | `preset.py` + `defaults/neutral-preset.json` | `resolve-preset` | Done. The font must be under `/usr/share/fonts/truetype/dejavu/`. |
| Dependency check | `preflight.py` | `preflight` | Done. `faster_whisper` shows as missing by design (Transcriber app); `node` is bundled at /usr/bin/node for capture. |
| ASR | `asr.py` | `asr` | Done through the shared **Transcriber** app (Speaches, faster-whisper-small by default). Output uses asr.py's exact schema plus provenance. Differences: Speaches does not report `language_probability` (it is null), and decoding options are the Transcriber's, not asr.py's `beam_size=5, vad_filter=True`. |
| Forced alignment | `align.py` | `align` | Done with local stable-ts 2.19.1 on CPU torch 2.11. Default model is `base` (139 MB, downloaded once to `/data/models`). Choose another with `VIDEO_ALIGN_MODEL` or the request's `model` field (tiny…large-v3-turbo). James' default is large-v3-turbo (~1.6 GB). |
| Acoustic CTC window | `acoustic_ctc_window.py` | `acoustic-ctc` | Runs only if an admin supplies a model bundle via `VIDEO_CTC_MODEL_DIR`; otherwise reported unavailable. |
| PCM assembly + frame map | `assemble_pcm.py` | `pcm-assemble` | Done (CFR only) |
| Per-edge evidence + keep/drop coverage | `speech_cut_audit.py` | `speech-cut-audit` | Done. Optional `baseline_job` for repairs. |
| Full-pass acoustic scan of the edit | (an operator task in SKILL.md) | `acoustic-scan` | `scan_windows.py`, written for this app, renders a waveform and spectrogram per window; the operator writes findings. |
| Dialogue audio gate | `audio_gate.py --stage dialogue` | `dialogue-gate` | Done. The app builds `audio-gate.json` v3 from hash-bound jobs. |
| Gate self-test | `test_audio_gate.py` | — | Runs at image build and in `test-container.sh` |
| Project validation | `validate_project.py` | `validate-project` | Done (planning records) |
| Portrait face audit / crop ledger ("fixed crop per setup") | none in James' bundle (his contract: `crop-ledger.json`) | `face-crop` | **Done (0.5.0).** `face_audit.py`, written for this app, runs OpenCV YuNet (opencv_zoo 2023mar, MIT, hash-pinned) on about 2 sampled frames per second of every kept segment. It picks one fixed crop per setup, with the face inside plus a 15% margin and above the caption band (`safe_rect` top), and writes `crop-ledger.json` plus a per-setup audit and evidence PNG. With no face it uses a centered crop and flags it. Kept segments share a setup while one crop still fits all their faces. |
| Live picture frames for the encode | `capture.cjs` (Chromium) | `final-render` | **Done.** With no motion composition, `final_render.py` (app-original) writes the frames in capture.cjs's output shape, so no Browser is needed. With motion, capture.cjs writes them through the Browser app (next rows). |
| Captions | `caption_layer.py` | `final-render` | **Done, unchanged.** encode.py calls it on every frame. Cue words come from the Transcriber's ASR of the edited audio (apply_cuts' job), in James' neutral preset style with DejaVu Sans Bold (fc-match). |
| 1080×1920 encode + verification | `encode.py` and `encode.py --verify-only` | `final-render` | **Done, unchanged.** libx264 crf 18, AAC, with edited.wav as the audio. The app then runs a full FFmpeg decode (framemd5 + PCM) and decoded-pixel checks: the ledger crop beats crops shifted by ±4 px and ±w/8 outside the caption band, and the band changes only while caption_layer draws a cue. |
| Final ASR + full final acoustic scan | `asr.py` schema (Transcriber) + `scan_windows.py` | `asr` / `acoustic-scan` on the final-render job | **Done.** The final audio is decoded from final.mp4 and diffed word by word against the edited-audio transcript. |
| Delivery audio gate | `audio_gate.py --stage delivery` | `delivery-gate` | **Done, unchanged.** The receipt binds `final`, `decoded_final`, `final_asr`, `final_acoustic_scan` and `final_integrity`. `source_regions` gives each kept segment's correlation between source.wav and the decoded final audio (James' floor is 0.90). |
| Semantic motion composition (index.html, visual-plan.json, #live, renderFrame, sourceFrameForOutputFrame, visualMode, captionSuppressed) | James' SKILL.md + motion-contract.md (authored per project) | `submit_motion` (MCP) | **Done (0.6.0).** Hermes authors the page; the app validates paths, sizes, file magic and James' beat schema, generates `defleur/ledger.js` (source-frame ledger) and vendors GSAP 3.15.0 as `defleur/gsap.min.js`. The contract is condensed in `workflow_guide.motion_contract`. |
| Project validation for motion | `validate_project.py` | inside `motion-capture` / `final-render` | **Done, unchanged.** Runs on every capture project (timeline, beats, crop ledger). |
| Smoke / proof / full capture with reverse-seek determinism | `capture.cjs` | `motion-capture` (smoke, proof) and `final-render` (full) | **Done, minimally adapted** (NOTICE, diff hash pinned): `puppeteer.connect` to the shared **Browser** app instead of `launch`, a per-capture random-token project URL, and all non-project requests blocked. James' frame selection, renderFrame/#live/ledger checks and reverse-seek byte comparison are unchanged. Smoke/proof return frame images and a contact sheet for Hermes to look at. |
| Fullscreen inserts / B-roll | contract: crop-ledger `fullscreen_exceptions`, preset `allow_fullscreen_insert_ranges` | `create_asset_upload` + `plan.inserts` | **Done (0.6.0).** Insert media (MP4 or image) replaces the live base frame through `#live` during its window (cover/contain to 1080×1920); recorded as `fullscreen_exceptions` in the crop ledger; audio stays the speaker's. |
| Fixed crop per setup, more than one setup, speaker choice | contract: `crop-ledger.json` ranges with `setup` | `face-crop` via `preview_framing` / `framing` option | **Done (0.6.0).** Greedy setups plus operator `new_setup_at` breaks and per-segment `targets` (largest/left/right/center) for two-person shots; each setup has its own face audit and evidence PNG. Crops never animate. |
| Caption suppression for a declared visual range | `encode.py` + `caption_layer.py` (`caption_suppress` in visual-plan) | `final-render` | **Done, unchanged scripts.** The plan's `caption_suppress` reaches encode.py through `visual-plan.json`; suppression outside a `suppress` beat is rejected at submit (James' rule). |
| Motion-window and caption pixel checks | (operator review in James' SKILL.md) | `final-render` (`motion_frames.py check`) | **Done (machine evidence).** Capture vs plain base frame (motion only inside beat/insert windows) and final.mp4 vs capture (captions exactly where caption_layer draws a cue, clean where suppressed). Not a perceptual review. |

## Measured in the local e2e (2026-10-07)
Setup: two translated Runtipi recipes on one shared network, with 7.7 s of real Kokoro-synthesized speech containing a filler "Um," and a 0.9 s pause.
- **ASR:** the Transcriber found all 22 words, including "Um," at 2.78–2.96 s (the fixture's known position is 2.761–3.138 s).
- **Alignment** (`base`) placed "Um," at 2.84–3.16 s.
- **Cut:** 2.82→3.90 s, removing 1.08 s.
- **Cut audit** passed: the drop region retained 0 s, and 4 edges produced 8 hashed PNGs.
- **Re-transcribing the edit** found no "um" and no lost words.
- **Dialogue gate** passed. An incomplete gate (one edge missing) was rejected.
- **Cost:** 33 s wall time with cached models. Video container cgroup memory peak was 896 MB of 1536 MB, during alignment.

### Piece 2 through MCP only (2026-10-07, `scripts/e2e-video-mcp.py`)
Fixture: a 1920×1080, 30 fps talking head built from a public-domain NASA portrait (slowly panned and scaled) muxed with the same Kokoro speech. Hermes-style calls: `create_upload` → curl → `start_edit` → `apply_cuts` (the proposed cuts) → `render_final` → `get_status`.
- **Final:** 1080×1920, H.264 + AAC 48 kHz, 184 frames / 6.12 s. An independent ffprobe and an `ffmpeg -xerror` full decode both pass.
- **Crop:** 1 setup, crop `[653, 0, 606, 1080]` at full height, face detected in 15/15 samples, no flags. In the decoded pixels the ledger crop beats ±4 px and ±w/8 shifted crops. An independent YuNet pass on 8 frames of the final MP4 found the face in all 8, inside the canvas and above the caption band (y ≤ 1240).
- **Captions:** 21 words in 5 cues, shown on 169 of 184 frames, DejaVu Sans Bold. The caption band changes only while a cue is drawn.
- **Delivery gate** (`audio_gate.py --stage delivery`) passed. Final ASR lost and added no words compared with the edited audio. The minimum source-region correlation was 0.99998.
- **Cost:** `render_final` took 35 s wall time (face-crop, final-render, final ASR, final scan, delivery-gate). The whole MCP flow took 98 s, including a second HEVC project. The video container's cgroup memory peak was 1.23 GB of the 1.5 GiB limit.

See RELEASE.md for the full verification record.

### Piece 3, varied 3-minute source (2026-10-07, `scripts/e2e-video-motion.py --long 180`, local only)
A non-repetitive 130.7 s Kokoro script (5 ums, 4 one-second pauses) on the real-face 1080p picture, run through the full MCP flow with a GSAP beat, a B-roll insert and two crop setups. **Pass.**
- 25 cuts removed 11.17 s (to 119.54 s), all measured near-silent (0.04 s of speech-like audio in total). 0 content words lost; dialogue and delivery gates pass (1 ASR spelling variant, trellis/trellies, reported separately).
- 1080x1920 H.264/AAC, 3587 frames, full decode. 79 caption cues; captions suppressed exactly where declared; motion only in planned windows; 2 setups with faces in crop.
- Memory peaks: video app 2.97 GiB (limit 10 GiB), Browser 0.70 GiB (limit 6 GiB). Time: 1159 s in total. render_final took 971 s: Browser capture 679 s (~0.19 s per frame), `encode.py` 130 s, checks ~80 s.
- On the earlier *looped* fixture, 11 of 31 transcript-gap "pauses" held speech (32.7 s; Whisper skipped repeated sentences). That's why pauses are now proposed only when measured silent, gaps with sound go to `untranscribed_sound`, and `apply_cuts` measures every cut (`cut_sound_check`).

## Known limits
- Silence is judged by an energy threshold (speech level - 15 dB, word tails at - 30 dB), not a trained VAD. Noise in a gap is listed for review, not cut; very quiet speech could still look like a pause. The owner listening to the edit is the final check.
- Motion graphics are authored by Hermes; the app checks mechanics (determinism, windows, suppression), not whether a beat explains well. Phone-size readability and continuous playback stay a human review (James' contract says so too).
- Crops are fixed per setup (James' rule); there are no animated pans. A speaker change inside one kept segment needs a cut there first.
- Remaining named gap: VFR sources are re-encoded to CFR on upload instead of carrying a PTS-to-output-frame ledger (James' `vfr-ledger` source mode).
- `final-render` writes one JPEG per output frame before encoding (about 0.3 MB each at 1080×1920; a 5-minute 30 fps video needs about 3 GB of free disk at peak) and deletes them after the encode.
- The face audit is sampled (about 2 frames per second), and a face the detector misses isn't audited.
- Alignment memory grows with model size. `base` peaked at 896 MB (limit now 10 GiB). `small` is untested. `medium` and `large-v3-turbo` would need a higher memory limit; also untested.
- The Transcriber runs ASR at about real time on CPU, so a long source takes about as long as it plays. ASR and alignment stages each have a 30-minute limit.
- VFR is handled by re-encoding to CFR on upload (0.4.0). Frame-exact editing of the original VFR timeline would need the PTS picture ledger from piece 2.
- Through MCP, `apply_cuts` writes the gate's edge/window review notes automatically from measurements. The gate then proves the evidence is complete, not that anyone listened.
