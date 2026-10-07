# Release: 0.6.0-testing (piece 3 of 3: motion graphics, inserts, multi-setup reframing)

## What this release is
DeFleur Video bundles James DeFleur's DeFleur Video plugin files unchanged (`defleur/` → `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`; plugin.json declares MIT; redistributed with the author's authorization, see NOTICE). With 0.6.0 every stage of his workflow is mapped (see WORKFLOW-PARITY.md). Hermes is the editor and motion author; the app never calls an LLM.

New in 0.6.0:
- **Motion graphics (James' defleur-motion).** MCP tools `submit_motion`, `create_asset_upload`, `capture_motion` ('smoke' | 'proof') and `render_final(project_id, {'motion': true})`. Hermes uploads a project-local HTML/SVG/GSAP composition and James' visual plan; the app generates `defleur/ledger.js` (window.sourceFrameForOutputFrame from the locked source-frame map) and vendors GSAP 3.15.0 (`defleur/gsap.min.js`, exact npm pin; Webflow standard no-charge license, commercial use allowed). `workflow_guide.motion_contract` gives Hermes the condensed contract: renderFrame(t), #live, sourceFrameForOutputFrame, visualMode, captionSuppressed, explanatory-beat rules, smoke → proof → full sequence.
- **Capture through the shared Browser app.** James' `capture.cjs` minimally adapted (`capture/capture-remote.cjs`, diff and hashes in NOTICE): `puppeteer.connect` to `BROWSER_URL` (default `http://browser:9222`), project served on a per-capture random-token URL on the internal network only, every non-project request aborted and recorded. His frame selection and reverse-seek determinism check are unchanged. Node 22 + puppeteer-core 25.12.0 from a pinned lockfile; no Chromium in this image.
- **Fullscreen inserts / B-roll** (`plan.inserts`, media via one-time asset upload URLs, recorded as crop-ledger `fullscreen_exceptions`).
- **Multi-setup reframing:** `preview_framing` + `framing` option: forced setup breaks and per-segment speaker targets (largest/left/right/center), one fixed crop and face audit per setup.
- **Motion pixel checks** (`motion_frames.py check`): motion only inside planned windows, inserts replace the live frame, captions burned exactly where caption_layer draws a cue and absent where suppressed; failures named in the delivery report.
- **Limits:** mem 8 GB (was 1.5 GB), no CPU cap, 2048 pids, 1 GB shm; uploads up to 20 min / 8 GiB / 4K (normalized to 1080p with provenance); output up to 6 min. Jobs check free disk and app memory first and fail with a plain message. `capabilities` reports host RAM, free disk, per-job estimates and Browser reachability with the exact fix. Frame directories are deleted right after encode.
- **Settings:** new optional `BROWSER_URL` (default `http://browser:9222`) next to `TRANSCRIBER_URL`.
- Without a motion submission `render_final` works exactly as in 0.5.0 and needs no Browser.

## Verification (local, 2026-10-07)
MEASURED_BLOCK
