---
name: defleur-video-editing
description: Use when the owner asks you to edit a video with DeFleur Video. Runs the agent check, one combined cut + motion-plan approval, a motion-graphics render, and an honest report.
license: MIT
metadata:
  app: DeFleur Video (Wizard App Store)
  mcp: http://defleur-video:8787/mcp
  intended_setup: Hermes Agent with Claude Opus 5.5 (claude-opus-5-5)
---

# DeFleur Video editing

The app runs James DeFleur's short-form workflow on the owner's server. You are the editor and the motion author.
`workflow_guide` gives the exact tool order and the motion contract. This file gives the judgment behind it, and the two agree.
If they ever differ, follow `workflow_guide`: it ships with the running app version.

**The default edit** is a tight cut (every um, stutter, padding phrase and long pause gone), plus full-frame motion graphics
(your HTML/SVG/GSAP beats and any fullscreen inserts), plus James' house captions and the fixed 9:16 crop. Motion graphics are
the point of this editor. A one-sentence request like *Edit "my clip.mp4" from my Files with the DeFleur video editor* means
this full edit, in James' house style, with no style questions.

## James' house style (the default)

- **Tight audio.** A short has no dead air. Remove every filler (um, uh, erm), stutter and restart, comma-isolated padding
  ("..., you know, ...", "..., I mean, ...", "..., like, ...", "..., right, ..."), dead air at both ends, and every pause over 0.5 s
  (shortened to a natural ~0.15-0.25 s beat, not removed to zero). `start_edit` proposes all of these by default.
- **Open on the hook.** If the first seconds are warm-up ("Okay, so today I'm going to share..."), propose starting on the first
  strong line and say so.
- **Captions** (applied automatically from `defaults/james-preset.json`): heavy sans in ALL CAPS, 2-4 words per chunk, white
  words, the spoken word green only while it is spoken, black stroke and shadow, no boxes. Chunks break at sentence ends, real
  pauses and long words. Mark ONE key term per chunk in yellow by listing its edited-timeline second in
  `plan.caption_emphasis` (the claim word: the number, the named idea, the contrast) - a few per minute, not every chunk.
- **Visuals are full-frame storytelling, not a dashboard.** Each beat owns the whole 1080x1920 canvas (full-bleed background,
  illustration or diagram scaled to fill), then cuts back to the speaker full-frame. Never shrink the speaker into a corner tile or
  park one split-screen layout over most of the video. Speaker-only stretches between beats are part of the rhythm.
- **Captions stay on for the whole video**, beats included. Every beat uses `caption_treatment: 'show'` and `caption_suppress`
  stays empty; the app refuses plans that switch captions off. Graphics carry labels, numbers and diagrams in big type
  (labels >= 44 px, headline >= 72 px at 1080 wide), not a second copy of the spoken sentence.

## 0. Agent check (before anything else)

Call `workflow_guide(agent_harness=<your harness>, agent_model=<your exact model id>)` and report honestly.
- The app compares this with the intended setup: Hermes Agent with Claude Opus 5.5. It also reads the MCP client name your
  harness announced (`detected_client`). MCP does not carry the model, so the model is only what you report. A missing model counts as unknown.
- If `agent_check.requires_owner_confirmation` is true, show the owner `agent_check.warning` in plain words, for example:
  *"DeFleur Video is built for Hermes Agent with Claude Opus 5.5. You're using Hermes Agent with gpt-5. You can continue, but
  results may vary; you'll get the best results with the intended setup. Continue?"* Then wait for a yes before importing.

## 1. Prepare

- `capabilities`: the Transcriber must be ready. `motion_ready` must be true; if it is false, relay the Browser-app fix.
- Find the file with `list_files` (match the owner's name, ignoring case), call `import_file`, then `start_edit` and `get_status` until it is done.

## 2. One approval question: cuts + motion plan

Draft both from the transcript before asking anything:
- **Cuts:** `proposed_cuts` is the default tight edit - present it as a compact list grouped by kind (fillers, padding, stutters,
  pauses, with the total seconds saved) and invite the owner to strike any they want kept. Add the hook trim if the opening is
  warm-up. For each `untranscribed_sound` gap, give the time and the words around it and recommend cutting after a quick listen
  (it is usually an untranscribed "uh" or a breath); cut it only on the owner's yes, marked `owner_approved_sound: true`.
- **Motion plan:** 3-6 full-frame beats for a 1-3 minute video. For each beat give the source time range, the spoken words it
  explains, and what the viewer sees change (cause to effect, before and after, a growing count, a comparison), plus where it
  returns to the speaker. Add fullscreen inserts only with media you have. No static title cards.

Ask once: "Here are the cuts and the motion graphics I plan. Approve, or tell me what to change." Never apply cuts before the owner answers.

## 3. Cut, then author the motion

- `apply_cuts` with the approved cuts, then `get_status`.
  - `words_lost_near_cuts` non-empty, or a failed dialogue gate, means a cut clipped speech. Widen or drop that cut and apply again.
  - `asr_variance_far_from_cuts` lists words the second ASR pass missed in untouched audio. Mention them, but they are not lost words and they do not fail the gate.
- Convert the approved beat times to **edited** seconds with `time_map`, using `edited = edited_start_s + (source - source_start_s)`.
- Write the composition by following `motion_contract` exactly: `ledger.js` and `gsap.min.js` first, a full-canvas `#live`, and a
  synchronous `renderFrame(t)` built on a paused timeline with `seek`. Hide every scene outside its beat. Beat backgrounds fill
  the full canvas; keep written content inside x 120-960 and y 220-1180, because captions sit at y 1220-1460 for the whole video.
- Run `submit_motion`, then `capture_motion('smoke')`, and look at the frames. Fix and resubmit if needed. Then run
  `capture_motion('proof')` and look at the contact sheet and the beat frames **at phone size**: if a label is hard to read in
  the contact sheet, it is too small. Check that the speaker is full-frame between beats.
- Then call `render_final(project_id, {'motion': true})`.

**Render plain (`{}`) only** in these cases: the owner asked for no motion, the Browser app is missing, or capture still fails
after one reasonable fix-and-retry. Pass `plain_reason` and tell the owner why.

## 4. While it renders

`get_status` reports a live `elapsed_s`, the current `step`, a `sub_stage` (face audit, live frames or motion capture with a
frame count, captions and encode, verify, decode check, then re-transcription and the delivery gate), and `estimate_remaining_s`.
Motion capture takes about 0.25 s per output frame on 4 CPUs: a 2-minute video takes about 15 minutes at 30 fps and about 35 minutes
at 60 fps (iPhone 4K60 footage stays 60 fps). Tell the owner the expected time up front, and that it is progressing, not frozen.

## 5. Read the gates and report

- **Delivery gate:** pass or fail, with its reason. Words lost far apart are ASR variance. Clustered lost words are a real problem.
- **Framing flag** (faces near the margin or caption band): look at several frames across the whole video, at least the start,
  middle and end, before judging. One frame proves nothing. Tell the owner what you saw.
- **Report:** resolution, duration (and seconds tightened), the motion beats and inserts delivered (time and what each shows, from
  `beats_delivered`), caption count, key terms and suppressions, the crop and any flag, gate results, any words lost, and where the
  file is (Files -> Videos -> Edited, plus the `final_mp4` link). If it is plain, say why. Ask the owner to watch it on a phone
  before posting. Never call it approved: the gates check evidence, not taste.
