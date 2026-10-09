# Release: 0.6.5-testing (motion graphics by default, live render progress, agent check, SKILL.md)

From the owner's one-sentence test on 0.6.4: Hermes (with GPT) delivered a clean edit with NO motion graphics, because the guide
called them optional ("skip this for a plain captioned talking-head video"). get_status also looked frozen for about 15 minutes during render_final.

- **Motion graphics by default.** GUIDE (`default_edit` and steps 0-10), the MCP `instructions`, and the start_edit, apply_cuts,
  submit_motion and render_final descriptions now define a DeFleur edit as: approved cuts + motion graphics + captions + crop.
  Right after start_edit, the agent drafts a motion plan (beats with source times, the spoken words each explains, and what changes) and
  shows it with the cut list in ONE approval question. apply_cuts returns `time_map` (source to edited seconds), because
  submit_motion's plan is in edited seconds, so the order is: approve, then apply_cuts, then author and submit, then smoke, then proof, then `render_final({'motion': true})`.
  The agent renders plain only when the owner asks, the Browser app is missing, or capture keeps failing. `render_final({})` then returns a
  `plain_note` (optional `plain_reason`) telling the agent to explain why. The report lists `beats_delivered` and `inserts_delivered`.
  Tests: `test_guide_defaults_to_motion_with_one_combined_approval`.
- **Live progress.** Cause: get_status computed `elapsed_s` from the run file's last save, and the file was only saved between app
  stages, so a 15-minute final-render froze at 48.9 s. Now `elapsed_s` is computed when status is read. Each workflow stage writes a
  `<job>.progress` sub-stage file (prepare, face-audit-crop, motion-capture with a live frame count, live-frames-crop,
  captions-encode, motion-pixel-check, encode-verify, live-pixel-check, decode-check). The job API returns it and the MCP run
  mirrors it, so get_status shows `step`, `step_elapsed_s`, `sub_stage`, `stages_left` and a rough `estimate_remaining_s`.
  Tests: `test_render_status_elapsed_is_live_with_sub_stage` and `test_job_progress_file_is_live_and_cleared`.
- **Agent check (step 0).** `workflow_guide(agent_harness, agent_model)` returns `agent_check` {intended, detected_client, claimed,
  match: true|false|"unknown", warning, requires_owner_confirmation}. The intended setup (Hermes Agent with Claude Opus 5.5,
  `claude-opus-5-5`) lives in one constant, `INTENDED`, and accepts `[1m]`, provider-prefixed and dated ids. The app's /mcp proxy remembers
  each peer's MCP initialize `clientInfo`. The server is stateless, so tool calls never see initialize themselves. Hermes Agent
  sends the Python SDK default `mcp/0.1.0`, which is reported as "consistent with Hermes, not proof". Known other clients
  (claude-code, cursor, ...) make the result a mismatch. The model is only what the agent reports, and a missing model counts as unknown.
  Tests: `test_agent_check_match_mismatch_unknown` and `test_proxy_remembers_mcp_client_info`.
- **SKILL.md** (Agent Skills format, `name: defleur-video-editing`): the agent check, the combined approval, how to read the gates
  (`words_lost_near_cuts` versus `asr_variance_far_from_cuts`), framing flags (look at several frames), and what to report. It is served at
  `GET /SKILL.md` (no token, like /healthz; `X-Content-SHA256`) and as the MCP resource `defleur-video://SKILL.md`. GUIDE and the MCP
  instructions point to it, and it defers to workflow_guide if they ever differ. Test: `test_skill_md_served_and_agent_skills_format`.
- **Motion delivery gate bug (found only by the real-file run).** A motion plan with NO `caption_suppress` failed
  `captions_suppressed_where_declared` because the check required at least one sampled suppressed frame. That also failed
  `motion_check_pass` and `picture_map_verified`, so every motion edit without suppression failed delivery. The e2e fixture always
  declared a suppression, which hid it. Now no declared range means nothing to check; a declared range must be sampled and caption-free.
  Test: `test_motion_check_passes_plans_without_caption_suppression`.
- **Framing flag, now specific.** On the owner's file (portrait 4K, so the crop is the full frame), 201 of 244 sampled face
  boxes plus the 15% margin reach the caption top (y 1240), and only 9 touch the side margin. The flag now gives counts and how far
  (median and max px below the caption top: the chin and neck area sit under the captions) and says when no fixed crop can avoid it,
  instead of the vague "faces near safety margin or caption band". The check itself is correct: the face box bottom sits
  around 65% of the height, and that is where captions go. Test: `test_framing_flag_says_how_far_into_the_caption_band`.

# Release: 0.6.4-testing (first real edit: false lost words, padded filler cuts, preview 422, no way back to uncut)

Found by the owner's first real edit (121.7 s iPhone 4K60 HEVC HLG, natural speech). Each fix has a failing-first unit test.

- **Dialogue gate: ASR variance is no longer "lost words".** apply_cuts compares the source-aligned kept words with a second
  Transcriber pass over the edited WAV. On real speech the second pass segments differently (the source had 16 words
  aligned to one instant, 22.98-22.98 s), so words far from any cut were reported lost. The editor now keeps each kept
  word's source timing (`cut_regions(..., timed=True)`) and locates every lost token (`editing.edit_word_review`):
  - lost within **0.5 s of a cut edge**, crossing a cut, or with unusable timing -> `words_lost_near_cuts`, **fails** the gate;
  - lost but wholly inside one assembled block and >= 0.5 s from every cut edge -> `asr_variance_far_from_cuts` (with
    timings), **does not fail**. Principle: assemble_pcm copies sample ranges, so such a word is byte-identical audio in
    the edit; the edit cannot have removed it. Collapsed (zero-length) alignments are located by their nearest timed
    neighbours (the bounded span must be inside one block and 0.5 s from cuts) and are now kept in the expected list.
  - Every word is still reported (`words_lost_vs_source`, `words_added_vs_source`). James' audio_gate.py is unchanged.
- **Delivery gate (render_final): edited audio vs final video.** The final audio is the edited WAV re-encoded and its
  custody is proven separately (source-region correlation >= 0.90, James' gate). Scattered lost words are ASR variance
  (`asr_variance`, located in edited time). The words check fails only when more than **max(3, 5% of words)** are lost or
  **3 lost words fall within 2 s** (a dropout looks like a cluster; ASR variance does not). `editing.delivery_word_review`.
  Older gate summaries without the new fields keep the strict rule.
- **Filler/repeat cuts never eat neighbours.** The +-0.02 s padding is clamped to [previous word end + 0.01, next word
  start - 0.01]; with adjacent words the cut trims the filler's own edge instead (owner's 'means' 38.12-38.38 | 'um'
  38.38-39.18 | 'right' 39.18 -> cut 38.39-39.17, was 38.36-39.20). Fillers separated by a real word are not merged.
- **Preview 422 "out-of-source span".** start_edit's duration is the audio length (121.728 s); the project's video is
  121.726 s. edit_plan and workflow segments now accept an end up to **0.05 s** past the duration and clamp it
  (`editing.DURATION_TOLERANCE_S`, same rule in both places). The preview shows the first 60 s of longer edits instead of failing.
- **apply_cuts(segments=[]) = no cuts.** Keeps the whole source (captions/framing only); the way back to an uncut edit.
  Tool description and workflow_guide say so.
- **Near-cut lost words get a focused second opinion.** On the owner's file the full 2-minute edited ASR heard
  "means a friend of a friend" where the source is "means [um cut] right a friend": 'right' starts 0.01 s after the cut,
  so it is (correctly) treated as possibly clipped. A focused Transcriber pass on the SAME edited audio, 4 s each side
  (`asr` stage now takes optional `start_s`/`end_s`, max 60 s), heard "that mean right friend of a friend". A near-cut word is
  cleared only when the focused pass hears it **in place** (aligned to its own position, not merely somewhere in the window);
  cleared words are listed under `words_near_cuts_heard_on_local_recheck` with the job id. Otherwise the gate still fails.
  Measured on the source audio: the removed 38.39-39.17 span alone transcribes as noise ("Thanks."), the kept 39.17-40.08
  span alone as "Right.".
- **Preview ENOMEM on 1080x1920 60 fps.** The low-res preview trimmed full-size frames and scaled after concat; concat
  queues the later segment's frames while the first plays, so ffmpeg peaked at 5.1 GB RSS and failed under its 1 GiB
  address-space limit ("native media processing failed"). It now scales to 270x480 once, then splits and trims
  (85 MB peak, same output).
- Tests: test_filler_cut_never_overlaps_adjacent_words, test_near_cut_word_cleared_only_when_local_recheck_hears_it_in_place,
  test_portrait_preview_scales_before_segment_trims, test_edit_asr_variance_far_from_cuts_does_not_fail_the_gate,
  test_edit_real_lost_word_next_to_a_cut_fails_the_gate, test_collapsed_alignment_words_are_kept_and_bounded_by_neighbours,
  test_delivery_asr_variance_passes_but_many_or_clustered_losses_fail, test_edit_plan_tolerates_audio_slightly_longer_than_video,
  test_empty_cut_list_keeps_the_whole_source. 51/51 in the image; test_audio_gate.py passes.
- Upgrading: projects and start_edit/apply_cuts runs live in the app data volume and survive the update. Re-run start_edit
  to get the fixed (unpadded) proposals; the import does not need repeating.
- Real file: verified with `scripts/e2e-real-source.py --real-source` (owner's exact 812 MB bytes; Files + real
  Speaches Transcriber + this image, translated Runtipi recipes, 4 CPUs, MCP only). import_file 484 s; start_edit 114 s
  (420 words; proposals 33.42-33.59 and 38.39-39.17, no neighbour overlap); apply_cuts(proposed) 63 s: 0.95 s removed,
  dialogue gate **pass** ('right' cleared by the focused re-check; 10 far-from-cut words listed as ASR variance), preview
  rendered; apply_cuts([]) 56 s, gate pass; render_final({}) 779 s (final-render phase 710 s): 1080x1920 H.264 60 fps,
  121.73 s, saved to `Videos/Edited/hormozi advice 7-edited-e19abd4f.mp4`, delivery gate **pass** (2 scattered ASR-variance
  words, limit 21; min source-region correlation 0.99954). Container memory.peak 3.68 GB (10 GiB limit).

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
