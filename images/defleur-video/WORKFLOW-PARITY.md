# Original agent-operated workflow: implementation map

**Incomplete port, not an accepted preview-only product.** The target is James/DeFleur's existing workflow, with Hermes making editorial decisions and the standalone service owning media, jobs and bounded execution. An autonomous creative-director daemon or another LLM is not required. `0.2.0-review-1` is a private development tag; the store stays disabled.

## Recovered contract and current implementation

The private snapshot at `30768288eb1308b18216a5df5eb4648fbce3e55b` includes SETUP, all three skills, all three reference contracts, defaults and the helpers below. Originals are preserved privately, unchanged; this map does not redistribute their instructions or code.

| Source contract/helpers | Required operation and evidence | Current API status |
| --- | --- | --- |
| SETUP; defleur-edit skill/project-contract | Task-local creative model routing, project ownership, bounded resources; agent owns editorial judgment | Service independent of Hermes; fixed authenticated operations, SQLite jobs, immutable source/decisions, hashes and deletion. No global agent changes. Original task-local model policy remains client-side, not an extra daemon. |
| `probe_source.py` | Source metadata, full frame timestamps, cadence and decoded 48k PCM | Original safe adapter `source-audio`: descriptor-only FFprobe/FFmpeg, source-probe.json and source.wav/PCM receipt. CFR verified over every frame; VFR recognized but PCM picture mapping rejected until PTS ledger implemented. Native input is not an arbitrary helper path. |
| `preset.py`, neutral defaults | Defaults < explicitly supplied owner < project, source hashes and font resolution | **Actual pinned upstream helper executed** by `resolve-preset` when an administrator provides an authorized read-only snapshot. Accepts JSON, never reads owner Hermes state. Current font allowlist is DejaVu Sans Mono only; other owner fonts require safe packaging/configuration work. |
| defleur-audio skill/audio-contract; `preflight.py` | Dependency/model/resource evidence | Capabilities reports supported stages and missing helpers; not equivalent to full upstream preflight. No models downloaded. Full media budget from SETUP is not provisioned on this constrained host. |
| `asr.py` | Full transcript and word timing from real local faster-whisper inference | **Not exposed**. Dependency/models absent; no fake transcript. Requires safe model-bound adapter and supplied/authorized compatible weights. |
| `align.py` | Forced alignment of reviewed text with stable-ts | **Not exposed**. Dependency/models absent; externally authored timestamps are not alignment proof. |
| `acoustic_ctc_window.py` | Language-supported local ONNX acoustic inspection | **Not exposed**. Optional model/vocabulary/capabilities bundle and onnxruntime unavailable. |
| `speech_cut_audit.py` | Phonetic keep/drop regions, mathematical coverage, separate per-edge waveform/spectrogram and review | Legacy preview produces real edge WAV/PNG evidence but **does not execute this helper or implement its full coverage contract**. Needs numpy/matplotlib runtime and bounded adapter. |
| `assemble_pcm.py` | Sample-accurate concatenation, cumulative CFR picture indices and edit-map | **Actual pinned upstream helper executed** by `pcm-assemble`; source decoded at 48k, output sample count verified against edit-map, hash-bound artifacts. CFR only. This is mechanics, not dialogue approval. |
| `audio_gate.py`, `test_audio_gate.py` | Versioned dialogue lock bound to source/edited/map/phonetic/filler/acoustic evidence, reviewed edge findings | **Not exposed**. No route can synthesize a lock from successful encoding or caller's unsupported approval assertion. Need exact receipt adapters/negative tests and real review workflow. |
| defleur-edit skill; `validate_project.py` | Locked audio, semantic visual plan, crop/face and VFR ledgers | **Not exposed**. Existing fixed protected-region crop validates geometry only, not actual face detection/tracking or per-setup portrait review. Hermes must inspect actual source frames; frame-selection/review-ledger API remains work. |
| defleur-motion skill/motion-contract; `capture.cjs` | Authored semantic scenes, source-frame mapping, deterministic browser frames/reverse hashes | **Not exposed**. Requires a separately bounded offline browser stage. Upstream arbitrary authored HTML/JS and `--no-sandbox` must not be put behind a generic shell endpoint. Chromium existing on host is not a packaged safe implementation. |
| `caption_layer.py`, `encode.py` | Upstream Unicode captions, full frame render, PCM/cadence/source-custody verification | **Not exposed**. Existing ASCII drawtext/270x480 preview is retained only as regression tooling, not equivalent. Requires Pillow/fonts and safe adapters; upstream scripts trust project paths. |
| audio delivery gate | Exact final MP4 plus decoded-final acoustic/ASR/integrity evidence and correlation threshold | **Not exposed**. Downloads verify SHA-256, but every result remains delivery_approved:false. Final delivery needs real reviewed evidence, not an exit-code approval. |

## Implemented stage contract

`POST /v1/projects/{project}/stages/{operation}` takes JSON with bearer authentication; returns a durable job (202). Poll `GET /v1/jobs/{job}`. Success is `needs_review`, not delivery approval. Download only manifest names from `GET /v1/jobs/{job}/stage-artifacts/{name}`. Source/PCM/preset receipts include exact hashes. Paths, shell commands, source URLs, arbitrary filters and executable/model names are never accepted from clients.

- `source-audio`: `{}`. Source probe and 48k signed-16 PCM. No original helper needed.
- `pcm-assemble`: `{"segments":[{"start_s":0,"end_s":1,"reason":"Actual caller-reviewed reason"}]}`. Real upstream assembler, <=8 ordered spans; use source-specific values, not this example blindly. No 60s total-output limit on this stage.
- `resolve-preset`: `{"owner":{...},"project":{...}}`, both optional. Explicit JSON only. Defaults and two helper files must match pinned hashes. Unknown fields may be rejected by the original preset validator.

Adapters share one bounded worker, durable state, resource limits and cleanup. Upstream side-load is admin-controlled, read-only and hash-verified; absent helpers fail closed. The ordinary public image intentionally contains none of the unclear-license upstream code. Therefore publishing it alone cannot deliver original-workflow parity.

## Capacity evidence, not original-footage acceptance

Admission is now **512 MiB / 300 seconds**, H.264/AAC self-contained MP4, <=1920 per axis / 2,073,600 pixels. Uploads stream in 64 KiB chunks. Source/PCM stages permit 128 MiB per output file, source cadence <=60fps; legacy preview still caps concatenated output at 60s. Upload reserve includes the incoming byte count plus 256 MiB; stages require 512 MiB free. One native child has 1 GiB address-space/90 CPU-second bounds; entire job deadline 180s. Container remains 1536 MiB, no swap, two CPUs.

An actual network-disabled/read-only UID1000 container uploaded a **270 MiB, 184-second synthetic** source over HTTP and ran the actual upstream PCM assembler: 920 frames at 5fps, 8,832,000 stereo samples, 0.628s stage / 4.678s total, cgroup peak **417,062,912 bytes**. File size uses a padding `free` box; picture content is 160x90 color/tone. This verifies streaming byte/duration capacity, **not original fixture codec complexity, speech quality, full-resolution browser render or ASR sizing**. Test source and measurements are reproducible with `test_workflow_scale.py`; no real owner footage was accessed. The original fixture itself remains untested.

## Remaining decisions and engineering

1. **Redistribution:** obtain the actual copyright/license notice and permission for the recovered helpers/instructions, or explicitly choose an authorized private read-only side-load. Metadata says MIT but the notice is absent. Do not publish the private branch/history. Side-loading does not itself complete the missing adapters.
2. **Models/runtime:** authorize/provide compatible local ASR/alignment weights (and optional CTC bundle) and a host with sufficient RAM/disk. No paid inference or large downloads occurred. The original SETUP media budget is 8 GiB capped without swap; this host had only about 7.5 GB available and near-full swap/disk during checks, so no full runtime was provisioned here.
3. **Validation inputs:** explicitly supply the intended source and owner preset/font assets through approved inputs. No owner state was read. Original-footage end-to-end review remains required.
4. **Implementation:** ASR/alignment, full acoustic evidence and lock, frame/portrait ledger, isolated semantic browser capture, original caption/encode and final gate adapters still need implementation and negative tests. These are engineering gaps, not a request for the user to invent editorial logic or authorize a new autonomous daemon.

Keep the listing disabled and publication gated until the intended original workflow—not a separately showcased synthetic demo—is usable and verified.
