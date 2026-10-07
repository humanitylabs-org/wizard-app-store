# Operator guide for Hermes (piece 1: audio/edit workflow)

Hermes is the editor. It makes every editorial decision: what to cut, which fillers go, and whether an edge sounds clean. This app never calls an LLM. It runs James DeFleur's original helper scripts on files it owns and returns evidence bound to SHA-256 hashes. Never invent transcripts, timings, reviews or receipts. If a stage fails, report the error and stop.

## Before you start

1. Read James' skills exactly as shipped. They are the spec you follow:
   ```sh
   python3 client.py docs                    # list available docs
   python3 client.py docs defleur-edit       # SKILL.md
   python3 client.py docs defleur-audio
   python3 client.py docs defleur-audio-contract
   python3 client.py docs defleur-edit-contract
   ```
2. Set `VIDEO_API_URL` (e.g. `http://<tailscale-host>:8787`). Only if the admin set one, put `VIDEO_API_TOKEN` in the process environment. Never put it in chat, URLs or files.
3. Run `python3 client.py capabilities` and check that `workflow.transcriber.reachable` and `model_installed` are both true. If not, the **Transcriber** app must be installed on the same Runtipi server (the video app reaches it at `http://transcriber:8000`) and its model downloaded. Tell the user; do not work around it.

`client.py` uses only Python's standard library; copy it from this directory. Every stage command below accepts `--wait` (block until done) and `--bundle DIR` (download every artifact and verify its hash). Each prints the job id. Pass job ids to later stages, never file paths.

## Step by step (`$P` = project id)

| # | Command | James' helper | What you decide |
|---|---|---|---|
| 1 | `upload source.mp4` | — | the user authorized this file |
| 2 | `source-audio $P --wait --bundle b/src` | `probe_source.py` + 48 kHz PCM | nothing; check `constant_frame_rate` (VFR stops piece 1) |
| 3 | `preset $P preset.json --wait` | `preset.py` | owner/project preset JSON (optional) |
| 4 | `preflight $P --language en --wait` | `preflight.py` | `piece_1_blockers` must be `[]` |
| 5 | `asr $P $SRC_JOB --language en --wait --bundle b/asr` | `asr.py` schema via the Transcriber | read `asr.json`; ASR can miss fillers |
| 6 | `align $P $ASR_JOB --language en --wait --bundle b/align` | `align.py` (stable-ts, default model `base`) | word timings are navigation seeds |
| 7 | `assemble $P $SRC_JOB plan.json --wait --bundle b/edit` | `assemble_pcm.py` | **your cut list**: `{"segments":[{start_s,end_s,reason}]}` |
| 8 | `cut-audit $P $ASM_JOB regions.json --wait --bundle b/audit` | `speech_cut_audit.py` | keep/drop regions for every word and filler near a cut |
| 9 | `scan $P $ASM_JOB --wait --bundle b/scan` | window scan (written for this app) | inspect every edited-window PNG |
| 10 | `asr $P $ASM_JOB --language en --wait` | Transcriber on `edited.wav` | confirm removed fillers are gone and nothing else was lost |
| 11 | `dialogue-gate $P gate.json --wait --bundle b/gate` | `audio_gate.py --stage dialogue` | your written reviews (format below) |
| 12 | `validate-project $P project.json --wait` | `validate_project.py` | locked timeline, visual plan, crop ledger (planning only) |

Optional: `ctc` runs `acoustic_ctc_window.py`, but only if the admin supplied a CTC model bundle (`VIDEO_CTC_MODEL_DIR`). Otherwise the app reports it as unavailable.

### Cutting (step 7)
Follow the defleur-edit SKILL.md: cut on thought boundaries, keep clauses whole, and remove fillers only after review (preset `remove_fillers_only_after_review`). Use the aligned word `end`/`start` times to place each cut in silence, a little after the last kept word and before the next one. All times are **source** seconds. Segments must be in order, must not overlap, and must each be at least 10 ms. Give each segment a real reason.

### Regions (step 8)
Regions are a JSON list of `{"mode":"keep"|"drop","start_s","end_s","word"?,"reason"?}`. Mark every kept word near each cut as `keep` and every removed filler as `drop`. The helper fails the audit if a kept word is clipped or a dropped region survives. It also renders `N-start/end-waveform.png` and `-spectrogram.png` for every retained edge. Open and look at each one.

### Gate file (step 11)
```json
{"assemble_job":"…","audit_job":"…","scan_job":"…","edited_asr_job":"…",
 "filler_review":{"full_pass_reviewed":true,"candidates":[{"word":"um","source_start_s":2.84,"source_end_s":3.16,"action":"removed","reason":"…"}]},
 "acoustic_review":[{"window":0,"findings":"what you saw in window 0"}, "…one row per scan window…"],
 "reviewed_edges":[{"segment":0,"edge":"start","decision":"keep","findings":"…"}, "…every segment start and end…"]}
```
The app attaches each edge's waveform and spectrogram with their hashes, then builds `audio-gate.json` exactly as `audio_gate.py` expects. The gate fails if any edge or window lacks evidence or if the cut audit did not pass. `pass:true` means the evidence is complete and the hashes match. It is **not** proof that anyone listened. Say so.

## Rules
- A failed job is final. Read the error, fix the cause, then submit a new job. Don't retry blindly.
- `delivery_approved` is always false. Pieces 2–3 (face/crop audit, captions, 1080×1920 encode, motion graphics, delivery gate) are not built yet. Don't claim a finished video.
- Keep downloaded bundles private; they contain the source audio.
- `delete $P` removes the project's source, jobs and artifacts. Only run it when the user says so.
- The older 9:16 preview commands (`decision`, `render`, `review`) still work; see EDITING.md.
