---
name: defleur-motion
description: "Use when creating deterministic semantic HTML/SVG/GSAP motion and burned captions for a locked edit."
compatibility: "Browser capture needs a project-local Puppeteer dependency and a Chromium executable on the media worker."
metadata:
  workflow: defleur-video
  role: motion-and-captions
---

# DeFleur motion and captions

Use after dialogue and picture timing lock. This skill contains a neutral renderer contract, not visual assets, a fixed color system, source media, or an answer for any particular clip.

## Semantic motion contract

Build project-local `index.html`, `visual-plan.json`, source-frame ledger, and original assets. The page must render the declared canvas and expose:

- `window.renderFrame(t)` — synchronous deterministic state reconstruction for a numeric second;
- `window.visualMode(t)` — optional declared mode for QA;
- `window.captionSuppressed(t)` — optional declared caption-suppression state;
- `#live` — the live-footage element where a declared live range exists;
- `window.sourceFrameForOutputFrame(frame)` — required source-frame ledger lookup for capture.

Use HTML and SVG primitives plus a local GSAP copy. A beat must make an explanatory change: route a cause to an effect, replace a state, accumulate a quantity that changes behavior, transform a topology, reveal a comparison, or return to the source with new meaning. Do not substitute static title cards or opacity-only labels for causal motion. Keep scene identities and initial hidden states explicit. Seeking backward after late scenes must not leave their nodes visible.

A `visual-plan.json` beat contains numeric `start`/`end`, `spoken_anchor`, `viewer_inference`, `visual_family`, `state_before`, `state_after`, `causal_action`, `caption_treatment`, and `speaker_return`. Fullscreen visual ranges are explicit exceptions to live crop policy. Give readable content dwell time and test it at phone size.

## Stable live footage and capture

Use the lock's source-frame map and fixed setup crop ledger. Do not animate a face-tracking crop. Capture uses the locked timeline's `fps` and `frames`; it does not assume 24 fps. The supplied capture helper renders a selected frame list and checks representative reverse seeks against previously captured hashes. It supports CFR timelines only; source VFR requires a project PTS-to-output-frame ledger before capture.

```sh
node scripts/capture.cjs PROJECT smoke
node scripts/capture.cjs PROJECT proof
node scripts/capture.cjs PROJECT full
```

`capture.cjs --help` describes the required project files and Chromium configuration. Run browser capture and full encode on the designated media worker.

## Neutral burned captions

Caption timing comes from the locked, post-edit word alignment. `scripts/caption_layer.py` uses `caption-style.json` from the resolved project preset. Style values are owner-configurable: font path, size, colors, outline, chunk size, and safe rectangle. The package ships no font files or branded palette. The default uses a readable white treatment with a dark outline; change it in an owner/project preset, not package code.

Keep captions short, stable, and inside the configured rectangle. Suppress them only for a declared visual range that independently communicates the same spoken words. Render captions onto captured frames before encode; an external subtitle file alone does not satisfy burned-caption delivery. Inspect bounds across all output frames and record the result in final audio/visual evidence.

See `references/motion-contract.md` for project file schemas and rendering/QA sequence.
