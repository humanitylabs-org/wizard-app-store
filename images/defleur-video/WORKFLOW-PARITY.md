# Workflow parity: James DeFleur's DeFleur Video → this app

James' plugin is bundled unchanged at `/opt/defleur`: upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`, licensed MIT per its plugin.json, and redistributed with the author's authorization (see NOTICE). Each script's SHA-256 is pinned in `workflow.py`, checked before every run and recorded in every job. Hermes is the operator. The app runs helpers only on paths it owns; clients never supply paths.

The port is split into three pieces. **Piece 1 (audio/edit) is done (0.3.0-testing). 0.4.0-testing adds an MCP endpoint whose `start_edit`/`apply_cuts` tools chain these stages for an agent, plus H.264/CFR normalization of HEVC/VFR uploads.**

| James' step | Helper | Stage | Status |
|---|---|---|---|
| Source probe, CFR/VFR check | `probe_source.py` | `source-audio` | Done. VFR uploads are normalized to CFR on upload (0.4.0), so the edit source is CFR; a VFR file that reaches PCM assembly some other way is still refused. |
| Lossless 48 kHz source PCM | ffmpeg decode | `source-audio` | Done |
| Preset resolution | `preset.py` + `defaults/neutral-preset.json` | `resolve-preset` | Done. The font must be under `/usr/share/fonts/truetype/dejavu/`. |
| Dependency check | `preflight.py` | `preflight` | Done. `faster_whisper` and `node` show as missing by design; the app explains why. |
| ASR | `asr.py` | `asr` | Done through the shared **Transcriber** app (Speaches, faster-whisper-small by default). Output uses asr.py's exact schema plus provenance. Differences: Speaches does not report `language_probability` (it is null), and decoding options are the Transcriber's, not asr.py's `beam_size=5, vad_filter=True`. |
| Forced alignment | `align.py` | `align` | Done with local stable-ts 2.19.1 on CPU torch 2.11. Default model is `base` (139 MB, downloaded once to `/data/models`). Choose another with `VIDEO_ALIGN_MODEL` or the request's `model` field (tiny…large-v3-turbo). James' default is large-v3-turbo (~1.6 GB). |
| Acoustic CTC window | `acoustic_ctc_window.py` | `acoustic-ctc` | Runs only if an admin supplies a model bundle via `VIDEO_CTC_MODEL_DIR`; otherwise reported unavailable. |
| PCM assembly + frame map | `assemble_pcm.py` | `pcm-assemble` | Done (CFR only) |
| Per-edge evidence + keep/drop coverage | `speech_cut_audit.py` | `speech-cut-audit` | Done. Optional `baseline_job` for repairs. |
| Full-pass acoustic scan of the edit | (an operator task in SKILL.md) | `acoustic-scan` | `scan_windows.py`, written for this app, renders a waveform and spectrogram per window; the operator writes findings. |
| Dialogue audio gate | `audio_gate.py --stage dialogue` | `dialogue-gate` | Done. The app builds `audio-gate.json` v3 from hash-bound jobs. |
| Gate self-test | `test_audio_gate.py` | — | Runs at image build and in `test-container.sh` |
| Project validation | `validate_project.py` | `validate-project` | Done (planning records) |
| Portrait face audit / crop ledger | — | — | **Piece 2, not built** |
| Captions | `caption_layer.py` | — | **Pieces 2–3, not built** |
| 1080×1920 encode | `encode.py` | — | **Piece 3, not built** |
| Motion capture (Chromium/GSAP) | `capture.cjs` | — | **Piece 3, not built** |
| Delivery audio gate | `audio_gate.py --stage delivery` | — | **Piece 3, not built** |

## Measured in the local e2e (2026-10-07)
Setup: two translated Runtipi recipes on one shared network, with 7.7 s of real Kokoro-synthesized speech containing a filler "Um," and a 0.9 s pause.
- **ASR:** the Transcriber found all 22 words, including "Um," at 2.78–2.96 s (the fixture's known position is 2.761–3.138 s).
- **Alignment** (`base`) placed "Um," at 2.84–3.16 s.
- **Cut:** 2.82→3.90 s, removing 1.08 s.
- **Cut audit** passed: the drop region retained 0 s, and 4 edges produced 8 hashed PNGs.
- **Re-transcribing the edit** found no "um" and no lost words.
- **Dialogue gate** passed. An incomplete gate (one edge missing) was rejected.
- **Cost:** 33 s wall time with cached models. Video container cgroup memory peak was 896 MB of 1536 MB, during alignment.

See RELEASE.md for the full verification record.

## Known limits
- Alignment memory grows with model size. `base` fits the 1.5 GB limit (896 MB peak measured). `small` is untested. `medium` and `large-v3-turbo` would need a higher memory limit; also untested.
- The Transcriber runs ASR at about real time on CPU, so a long source takes about as long as it plays. ASR and alignment stages each have a 30-minute limit.
- VFR is handled by re-encoding to CFR on upload (0.4.0). Frame-exact editing of the original VFR timeline would need the PTS picture ledger from piece 2.
- Through MCP, `apply_cuts` writes the gate's edge/window review notes automatically from measurements. The gate then proves the evidence is complete, not that anyone listened.
