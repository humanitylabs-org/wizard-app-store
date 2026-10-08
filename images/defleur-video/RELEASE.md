# Release: 0.6.3-testing (portrait 1080p fix)

- Fix: every portrait 1080x1920 H.264 source was rejected with "native media processing failed", including the app's own conversion of a 4K iPhone recording. H.264 pads 1080 to 1088 coded columns, which exceeded the decoder's 2,073,600 max_pixels. The decoder limit now allows only that block padding; the 1080p display-area limit in probe() is unchanged.
- Regression test: a 1080x1920 H.264 upload passes probe and creates a project.
- Verified on the owner's real file: 121.7 s iPhone 4K60 HEVC HLG MP4, 9 streams, 812 MB.

# Release: 0.6.1-testing (iPhone uploads)

- Uploads now accept iPhone `.mov` files (QuickTime brand `qt`, up to 8 tracks, self-reference `alis` drefs). They are always converted to a plain MP4 edit source; the edit source itself stays MP4-only.
- iPhone HDR (HLG/PQ) video is tone-mapped to SDR BT.709 during that conversion, and the extra timecode/metadata tracks are dropped. If several audio tracks exist, AAC is preferred.
- `POST /v1/projects` accepts `Content-Type: video/quicktime` as well as `video/mp4`.
- Upload page: the token field no longer overflows on phones.
- New unit test: an iPhone-style HEVC HLG `.mov` with rotation and a timecode track uploads and converts to H.264 SDR MP4. 36/36 unit tests pass in the image.

# Release: 0.6.0-testing (piece 3 of 3: motion graphics, inserts, multi-setup reframing)

## What this release is
DeFleur Video bundles James DeFleur's DeFleur Video plugin files unchanged (`defleur/` → `/opt/defleur`; upstream commit `30768288eb1308b18216a5df5eb4648fbce3e55b`; plugin.json declares MIT; redistributed with the author's authorization, see NOTICE). With 0.6.0 every stage of his workflow is mapped (see WORKFLOW-PARITY.md). Hermes is the editor and motion author; the app never calls an LLM.

New in 0.6.0:
- **Motion graphics (James' defleur-motion).** MCP tools `submit_motion`, `create_asset_upload`, `capture_motion` ('smoke' | 'proof') and `render_final(project_id, {'motion': true})`. Hermes uploads a project-local HTML/SVG/GSAP composition and James' visual plan; the app generates `defleur/ledger.js` (window.sourceFrameForOutputFrame from the locked source-frame map) and vendors GSAP 3.15.0 (`defleur/gsap.min.js`, exact npm pin; Webflow standard no-charge license, commercial use allowed). `workflow_guide.motion_contract` gives Hermes the condensed contract: renderFrame(t), #live, sourceFrameForOutputFrame, visualMode, captionSuppressed, explanatory-beat rules, smoke → proof → full sequence.
- **Capture through the shared Browser app.** James' `capture.cjs` minimally adapted (`capture/capture-remote.cjs`, diff and hashes in NOTICE): `puppeteer.connect` to `BROWSER_URL` (default `http://browser:9222`), project served on a per-capture random-token URL on the internal network only, every non-project request aborted and recorded. His frame selection and reverse-seek determinism check are unchanged. Node 22 + puppeteer-core 25.12.0 from a pinned lockfile; no Chromium in this image.
- **Fullscreen inserts / B-roll** (`plan.inserts`, media via one-time asset upload URLs, recorded as crop-ledger `fullscreen_exceptions`).
- **Multi-setup reframing:** `preview_framing` + `framing` option: forced setup breaks and per-segment speaker targets (largest/left/right/center), one fixed crop and face audit per setup.
- **Motion pixel checks** (`motion_frames.py check`): motion only inside planned windows, inserts replace the live frame, captions burned exactly where caption_layer draws a cue and absent where suppressed; failures named in the delivery report.
- **Limits:** mem 10 GiB (was 1.5 GB; 3x the measured 2.97 GiB peak of a 2-minute motion render), no CPU cap, 2048 pids, 1 GB shm; uploads up to 20 min / 8 GiB / 4K (normalized to 1080p with provenance); output up to 6 min. Jobs check free disk and app memory first and fail with a plain message. `capabilities` reports host RAM, free disk, per-job estimates and Browser reachability with the exact fix. Frame directories are deleted right after encode.
- **Settings:** new optional `BROWSER_URL` (default `http://browser:9222`) next to `TRANSCRIBER_URL`.
- **Safer cut proposals:** pauses are proposed only when measured near-silent; gaps with sound go to `untranscribed_sound` (review, never proposed); `apply_cuts` measures every cut (`cut_sound_check`, override `owner_approved_sound: true`); fillers and ASR spelling variants are reported separately from lost words. `render_final` reports `stage_seconds` and `final_render_phase_seconds`.
- Without a motion submission `render_final` works exactly as in 0.5.0 and needs no Browser.

## Verification (local, 2026-10-07)
Host: 4 vCPU, 15 GiB RAM, no GPU. All runs are MCP-only against the translated Runtipi recipes (Transcriber + Browser + DeFleur Video on one network).

**Unit and container tests:** `npm test` 42/42, `npx tsc --noEmit` clean. `sh images/defleur-video/test-container.sh`: 35/35 unit tests and James' `test_audio_gate.py` pass inside the image at 10 GiB / 2048 pids. Lifecycle smoke, `e2e-video-audio.py`, `e2e-video-mcp.py` and the short `e2e-video-motion.py` pass (CI runs these four).

**Bug found and fixed on long sources.** On the old looped 180 s fixture, `apply_cuts` removed 68.2 s where about 38 s was expected. We measured every applied cut against the file's speech level (median aligned-word loudness, −23.2 dBFS; a 10 ms frame louder than level − 15 dB counts as speech-like, transcribed filler spans excluded):
- 11 of the 31 proposed "pause" cuts contained speech-like audio, 32.7 s in total. The worst was the 40.5 s "trailing silence": the source transcript stopped at 138.9 s while speech went on to 180 s. Whisper had skipped repeated sentences, and the app treated the gap as silence.
- The lost-word list on that looped fixture was mostly re-transcription variance on repetitive audio. Only 9 of the 44 "lost" words were within 0.4 s of a cut. The real damage was speech that was never transcribed, so a transcript-based word check can never see it.

The fixes:
- `start_edit` proposes a pause only after measuring it near-silent (10 ms RMS envelope from `energy.py`). Gaps with sound go to a separate `untranscribed_sound` list for the owner to review and are never proposed.
- Pause cuts keep at least 0.15 s from aligned words and 0.1 s past any audible tail or onset (level − 30 dB, or noise floor + 6 dB). The first varied run had clipped the quiet "ts" of "pots" and the soft onset of "Write".
- `apply_cuts` measures every cut, including hand-written ones (`cut_sound_check`). A cut with more than 0.06 s of unexplained speech-like audio fails the reported dialogue gate with a plain message ("cut 12.40-13.90 s contains about 1.2 s of speech-like audio…") unless the cut carries `owner_approved_sound: true`.
- Fillers (um/uh/er/oh/ah…) are diffed separately (`fillers_heard_in_edit_only`, `fillers_in_source_only`). Near-identical ASR spellings (e.g. trellis/trellies; both words at least 4 letters and edit distance ≤ 0.34 or the same phonetic key) go to `asr_spelling_variants`. Any other lost content word still fails both gates. James' `audio_gate.py` is unchanged.

**Varied 3-minute run (local only, `e2e-video-motion.py --long 180`).** The fixture is a non-repetitive 130.7 s Kokoro (af_heart) script (`scripts/fixtures/video-long-script.json`) with 5 "Um," fillers and 4 pauses of 1 s, muxed with the real-face 1080p picture. It is synthesized once and cached. Result: **pass**.
- **Edit:** 25 proposed cuts removed 11.17 s, leaving 119.54 s. Every cut is near-silent: the loudest 20 ms frame in a non-filler cut is −61 dBFS, 0.04 s of speech-like audio in total, and `cut_sound_check` passes. `untranscribed_sound` was empty. 0 content words were lost. The cut audit and dialogue gate pass.
- **Removed vs expected:** the harness's rough estimate was 5.4 s (silencedetect −45 dB silences ≥ 0.5 s, each shortened to 0.5 s, plus the fillers). The app removed 11.2 s because it also trims shorter TTS gaps between aligned words that measure silent. We accept this as a faithful edit: no cut contains speech.
- **Fillers:** 3 of the 5 scripted ums were transcribed and cut. One um was heard only in the re-transcribed edit: the source ASR omitted it, so it stayed in, which is the safe direction. It is reported under `fillers_heard_in_edit_only`, not as an added word.
- **Added words:** `words_added_vs_source` listed 7 common words (good, today, the, a, never, on, there). The edit only removes audio, and every cut measures silent, so these come from the Transcriber transcribing the source and the edit differently. The edit inserted no new speech. The script itself has these words at the same counts as the source ASR, so the extras are alignment/segmentation variance between the two ASR passes, not content. The final MP4 from this run was not kept, so no third, independent transcription of the final video was made; the delivery gate's own final-vs-edited comparison found 0 lost or added words.
- **Final:** 1080×1920 H.264 + AAC, 3587 frames, 119.54 s, 59.3 MB. Independent ffprobe and an `ffmpeg -xerror` full decode pass. The delivery gate passes with 0 words lost vs the edited audio (1 spelling variant, trellis/trellies).
- **Picture:** 2 fixed-crop setups ([649,0,606,1080] and [637,0,606,1080]) with faces inside the crop on all samples. 79 caption cues (355 words) show on 3435 frames. 1 GSAP explanatory beat with captions suppressed exactly where declared, and 1 fullscreen B-roll insert (an independent face check finds no face mid-insert and a face on live frames). The motion pixel check passes: no motion outside planned windows, and the encode matches the capture. The capture made 0 non-local requests, and 12 reverse-seek frames were byte-identical.
- **Memory (cgroup memory.peak):** video app 2.97 GiB, Browser 0.70 GiB. The limits are now video 10 GiB (≥ 3× peak; it was 8 GiB) and Browser 6 GiB (already above 3× its peak).
- **Wall time:** 1159 s in total. Upload 1.3 s, start_edit 35 s, apply_cuts 39 s, preview_framing 9 s, capture smoke 53 s, capture proof 20 s, render_final 971 s.
- **render_final breakdown:** full motion capture in the Browser 679 s (3587 frames, about 0.19 s per frame, single page), James' `encode.py` (captions + x264 `medium` CRF 18, 4 threads) 130 s, motion pixel check 41 s, `encode.py --verify-only` 20 s, full decode + framemd5 + audio regions 17 s, setup 62 s, final ASR 12 s, final acoustic scan 9 s, delivery gate 0.4 s.
- **Expected time:** with motion, render_final takes about 8 min per output minute on this 4-vCPU host, and about 70% of that is the frame-by-frame Browser capture. Without motion (live footage + captions) there is no capture, so expect about 1.5–2 min per output minute. We found no cheap fix: capture.cjs's one-page sequential seek is James' determinism contract, and `encode.py` is his unchanged helper.

## Remaining gaps (honest)
- VFR sources are re-encoded to CFR on upload instead of James' PTS-to-output-frame ledger (`vfr-ledger` mode).
- The silence check is an energy threshold, not a trained VAD: loud room noise or music in a gap shows up as `untranscribed_sound` (safe: not cut), and very quiet speech under level - 15 dB could still be proposed as a pause. The owner listening to the edit remains the final check.
- ASR (faster-whisper small) can still omit fillers; an omitted filler stays in the edit and is reported, not cut.
- Full motion capture is ~0.19 s per frame in one Browser page (~8 min of render per output minute with motion on 4 vCPU). The 3-minute run is local only; CI runs the short e2e scripts.
- Taste (does a beat explain well, phone readability) is not checked.
