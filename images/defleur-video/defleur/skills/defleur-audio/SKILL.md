---
name: defleur-audio
description: "Use when making dialogue edits sample-precise and evidence-bound without claiming machine listening."
compatibility: "Python helpers use standard library for the gate; analysis helpers require declared local dependencies."
metadata:
  workflow: defleur-video
  role: audio-integrity
---

# DeFleur audio integrity

Audio lock is a mandatory production boundary. Work in source sample time, not a nominal video-frame grid. Use the actual source audio and preserve the original language; do not claim support for a language a selected model cannot identify or align.

## Preconditions and capability checks

1. Decode source audio to PCM s16 WAV without lossy intermediate encoding. Run `scripts/probe_source.py` in the orchestration skill and record the exact stream selection.
2. Run `scripts/preflight.py --source <source> --language <inferred-language>` on the intended worker. It reports missing binaries/modules; it does not download models or call providers.
3. Transcribe with `scripts/asr.py INPUT OUTPUT --language auto` first. The receipt records detected language and probability. Use an explicit language tag only after checking that the selected ASR/aligner model supports it. If confidence is low or alignment support is absent, require manual transcription/alignment rather than fabricating universal language coverage.
4. Align words only as navigation seeds. The align helper takes an explicit language and fails when the installed alignment route cannot serve it.

## Edit and first-draft scan

Create `edit-plan.json` only from full clauses or safely reviewed segments. `scripts/assemble_pcm.py` copies sample ranges and emits a cumulative audio-to-native-CFR-frame map. It accepts rational FPS such as `30000/1001`; its `--source-frames` count must come from the source probe. It is not a VFR mapper.

Immediately re-transcribe the assembled audio and perform an independent full-pass acoustic/filler scan. `filler-review.json` must cover every candidate: `removed` or `retained_with_reason`. Set `none_found: true` only after the completed scan. `edited-acoustic-scan.json` must cover the complete edited duration with overlapping/adjacent windows; a transcript alone cannot satisfy this scan.

## Every edge: waveform **and** spectrogram

For each retained segment start and end:

1. Declare source-time phonetic keep/drop regions.
2. Build a source-block manifest from the real edit map.
3. Run `scripts/speech_cut_audit.py`. It emits a separate waveform and a separate spectrogram around **each** edge, plus mathematical keep/drop coverage results.
4. Inspect both images and record an evidence item with exact hashes, a decision (`keep`, `move`, or `restore_clause`), and a specific acoustic finding. Low RMS or a zero crossing alone is not an acceptable decision.
5. If a tiny edit threatens a consonant, vowel, tail, fricative, or release, restore a continuous clause. Tiny de-click ramps belong only in reviewed quiet handles.

Optional `acoustic_ctc_window.py` is a local second opinion, never an auto-boundary picker. It requires an explicit model directory containing `model.onnx`, `vocab.json`, and `capabilities.json`; it fails unless the declared model supports the inferred language. Character peaks can be wrong and must be reconciled with spectrum and listening.

## Gates

Build `audio-gate.json` from actual files and SHA-256 values. `scripts/audio_gate.py PROJECT --stage dialogue` fails closed unless all required artifacts, complete filler coverage, mathematical cut checks, and **both waveform and spectrogram for every incoming/outgoing edge** are present and fresh. For a repair, the same phonetic regions must show a failed immutable baseline.

Before delivery, decode the exact MP4, rerun ASR and full acoustic scan, verify protected-source-region correlation and caption/picture-map evidence, bind final bytes, then run `--stage delivery`. Preserve the negative tests. A passing gate certifies evidence completeness and recorded thresholds; it never establishes human audible perfection. Report any listening defect as a failure even if the gate passes.

See `references/audio-contract.md` for receipt fields and `scripts/--help` for runnable commands.

## Evidence versus execution
The audio gate is an evidence-receipt validator: its green result never replaces actual media verification. Before delivery, also run defleur-motion/scripts/encode.py PROJECT --verify-only and retain media-verification.json plus the caption compositor record. Failed exact-file decode, dimensions, cadence or duration blocks delivery even when the audio receipt is complete.
