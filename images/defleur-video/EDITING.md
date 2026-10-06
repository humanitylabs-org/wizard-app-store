# Retained preview contract — not original-workflow parity

See [WORKFLOW-PARITY.md](WORKFLOW-PARITY.md) for the intended complete agent-operated workflow and actual source/PCM/preset stages. This legacy preview is not an accepted substitute.

Externally authored editing, not autonomous creativity or delivery approval. No Hermes, models, extra Python packages or paid calls. See README for startup, input safety and deployment limits.

## Standalone client

Use the same `VIDEO_API_TOKEN` as the service; never put it in a URL. Default URL is loopback; override with `VIDEO_API_URL` or `--url`. Use HTTPS except on loopback/trusted protected networks.

```sh
python3 client.py upload source.mp4
# Set PROJECT_ID to returned id; author decision.json for this exact source.
python3 client.py decision "$PROJECT_ID" decision.json
python3 client.py decisions "$PROJECT_ID"
# Set DECISION_ID to saved revision id.
python3 client.py render "$PROJECT_ID" --decision "$DECISION_ID"
# Set JOB_ID to returned job id.
python3 client.py status "$JOB_ID" --wait
python3 client.py review "$JOB_ID" ./my-review
# Open my-review/index.html locally; MP4/WAV/PNG/JSON are downloaded.
# Delete only after the server's original/project are no longer needed:
python3 client.py delete "$PROJECT_ID"
```

Client verifies download hashes, reads back mutations, refuses existing review directories and never embeds the token in HTML. Bundles contain private media: keep them private. No redirects/source URL fetching. `render --plan edit-plan.json` supports simple plan-only jobs. The API has no hosted GUI: HTML is generated locally, so the app entry remains `no_gui:true`.

## Decision schema

Immutable decision = `{transcript,plan}`. Illustrative syntax only; supply actual wording/timings and editorial reasons:

```json
{
  "transcript": {
    "language": "en",
    "provenance": "Human transcription; estimated timings, not forced-aligned",
    "words": [
      {"start_s": 0.1, "end_s": 0.3, "word": "Keep"},
      {"start_s": 0.3, "end_s": 0.5, "word": "this"},
      {"start_s": 0.5, "end_s": 1.0, "word": "thought."}
    ]
  },
  "plan": {
    "segments": [{"start_s": 0, "end_s": 1.8, "reason": "Keep complete thought after listening"}],
    "captions": [{"start_s": 0.1, "end_s": 1.0, "text": "Keep this thought."}],
    "framing": {"mode": "contain"}
  }
}
```

- Transcript uses **source seconds**, 1–1000 ordered/nonoverlapping nonempty words within source duration. Language/provenance required. Persistence is not accuracy, filler disposition or forced-alignment approval.
- Segments retain the existing 1–8 ordered/nonoverlapping spans, >=0.1s, source seconds, nonempty reasons.
- Optional captions use **output seconds after concatenation**, not source seconds. 1–64 ordered/nonoverlapping cues within summed retained duration, >=1/24s; half-open `[start_s,end_s)` at 24fps. No automatic transcript remapping/alignment.
- Caption renderer supports printable ASCII only, 1–2 nonempty lines of <=24 columns, fixed 16px DejaVu Sans Mono, white/black backing in lower safe band. Private text files with `expansion=none` make punctuation literal rather than FFmpeg expressions. Unsupported languages/long lines fail validation. Not upstream word-highlight rendering.
- Default `framing:{"mode":"contain"}` letterboxes the whole source. Optional fixed crop for a **320×180** source:

```json
{"mode":"crop","crop":{"x":20,"y":10,"width":90,"height":160},"protected_region":{"x":40,"y":30,"width":40,"height":110}}
```

Crop uses even integer coordinates/dimensions and exact 9:16; source is unrotated/square-pixel. Rectangles remain within source; protected region stays inside crop with >=5% margins and, with captions, above the caption band. One crop across all spans avoids jitter. **Caller must mark a region containing the face/head throughout retained footage. Geometry validation is not face detection/tracking/audit.** Contain does not certify captions avoid important source content.

Unknown fields, booleans as numbers, nonfinite timestamps, caller fonts/filters fail. Decisions bind source SHA-256 plus compact JSON decision hash. Jobs retain immutable plans and optional decision IDs. Max 16 revisions/project; save a new decision/job to revise. Additive SQLite tables preserve v0.1 state; old receipts do not retroactively acquire artifacts. Older projects lacking rotation/pixel-aspect metadata can still use contain mode; reupload the source before requesting a crop rather than guessing its geometry.

## Added API routes

All require bearer authentication. POST JSON requires application/json, one Content-Length, <=64KiB.

| Route | Response |
| --- | --- |
| `GET /v1/projects/{id}/source` | Exact hash-checked original attachment |
| `POST /v1/projects/{id}/decisions` | `{transcript,plan}` → 201 immutable revision |
| `GET /v1/projects/{id}/decisions` | `{decisions:[...]}` oldest first |
| `POST /v1/projects/{id}/previews` | Accepts plan **or** `{"decision_id":"..."}` |
| `GET /v1/jobs/{id}/artifacts/{manifest-name}` | Allowlisted PNG/WAV at needs_review |

Job response adds decision ID, plan/source/output hashes, burned-caption/framing summary and `result.review`: artifact names, hashes, byte counts/MIME types, edges, exact-preview decoded audio and caveats. No arbitrary filesystem access. Downloads are no-store complete attachments, not range streams; offline files allow seeking. Hash mismatch returns 409. Delete removes source, outputs, decisions and jobs.

## Evidence is not approval

Each retained start/end has a source +/-0.8s window clipped to duration, separate 640×200 waveform/spectrogram PNGs and a 16kHz mono PCM WAV. Manifest records cut marker/time bounds, frequency axes and hashes. Waveforms normalize independently; spectrograms have log magnitude and linear 0–8000Hz vertical scale. Not calibrated loudness or phonetic classification.

Window selection follows recovered `speech_cut_audit.py`. Its numpy/matplotlib CLI is **not executed**: a native FFmpeg adapter uses the existing bounded fd-only decoder, without dependency downloads. Upstream keep/drop coverage receipts and audio gate are not integrated. Recovered vendor source is unchanged.

The exact encoded preview is also decoded to 48kHz stereo PCM for audition. This is downstream AAC-decoded audio, not a sample-locked master. Edges remain `unreviewed`, `audio_lock:false`, `human_audition:false`. Evidence generation must finish before needs_review. Failure removes partial files; restart fails interrupted jobs instead of silently replaying. All stages share a 180s deadline. Render admission also reserves 256MiB disk. Preview output remains <=60s; source admission is now 512MiB/300s, and separate source/PCM stages support longer media within the documented bounds.

Every output still has `delivery_approved:false` and all unmet upstream quality gates. No approval endpoint. Coherent selection, phonetic/filler cleanup, word alignment, sample/PTS lock, face audit, semantic animation, phone-size review and final integrity receipt remain unfinished. Mechanics do not clear review gates. Captions require FFmpeg drawtext and `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf`, present in the tested cached image.

Reproducible tests and actual measurements are described in [RELEASE.md](RELEASE.md) and [WORKFLOW-PARITY.md](WORKFLOW-PARITY.md). Original-workflow completion, registry publication, Runtipi installation, license notice and production hardening remain blockers. Do not enable the app-store entry.
