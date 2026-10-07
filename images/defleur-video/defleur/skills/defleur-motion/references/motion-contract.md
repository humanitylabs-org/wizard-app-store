# Motion and caption contract

## Required renderer inputs

The project-local renderer consumes `locked-timeline.json`, `visual-plan.json`, and generated `base_frames/`. `locked-timeline.json` must provide positive `duration`, positive integer `frames`, positive rational/string `fps`, and optional `canvas` defaulting to `[1080,1920]`. Its source-frame map must already reflect the locked audio and CFR/VFR mapping policy. `index.html` must expose `window.sourceFrameForOutputFrame(frame)`, which returns the nonnegative integer base-frame number from that ledger; capture fails without it.

`visual-plan.json` follows the semantic beat shape in the editorial project contract. Every beat has an explicit state-before/state-after and causal action. The renderer's source code must define `window.renderFrame(t)` as direct state reconstruction rather than relying on monotonic playback. It must reset or gate all scene nodes at each seek.

## Capture and review

`capture.cjs PROJECT smoke|proof|full` serves only the project root, captures a selected list of exact output frames, and writes `capture-<mode>.json`. `proof` samples starts, mids, ends, and beat boundaries. It compares selected forward frame bytes to re-rendered backward-seek bytes, so a mismatch blocks capture. This check does not judge whether the animation is meaningful; review continuous playback and phone-sized readability separately.

## Caption file

`caption-style.json` comes from the resolved preset. It requires `font_path` pointing to a font available to the project/worker, positive `font_size_px`, `text_color`, `active_color`, `outline_color`, nonnegative `outline_width_px`, positive `max_words`, positive `max_chars`, and a four-number `safe_rect`. The package does not distribute a font.

`caption_layer.py` is a reusable Pillow adapter: `caption_engine(project, style_path=None)` returns a function `(image, t) -> image`, and `--help` documents its CLI. Apply it after browser capture to burn pixels into every delivery frame. Check actual bounds from rendered frames; the style rectangle is a constraint, not proof of legibility.

## Executable encoding and exact-file gate

After full capture, run `python scripts/encode.py PROJECT`. It composites burned captions on every captured frame, rejects overflow and undeclared suppression, records frame/style/timeline hashes, and streams H.264/AAC to final.mp4. Preserve prior final.mp4 before a repair; it refuses overwrite. Run `python scripts/encode.py PROJECT --verify-only` again on the exact delivery bytes: ffprobe checks dimensions, frame count, cadence and audio duration, and FFmpeg decodes every stream with error failure. Keep media-verification.json and caption-composite.json alongside audio evidence.

Both the executable media check and the audio evidence-receipt validator are required. The audio receipt alone does not parse video, establish burned-caption pixels or certify perception. Review representative decoded final frames and continuous playback independently; compare the source picture ledger, cropped live frames and final timing. Media decode is technical validity, not a claim that an edit sounds or looks good.
