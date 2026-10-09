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

**The default edit** is the owner's approved cuts, plus motion graphics (your HTML/SVG/GSAP beats and any fullscreen
inserts), plus burned captions and the fixed 9:16 crop. Motion graphics are the point of this editor. A one-sentence request
like *Edit "my clip.mp4" from my Files with the DeFleur video editor* means this full edit.

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
- **Cuts:** the proposed cuts (time, the words around each one, and the reason), plus any `untranscribed_sound` gaps. Those gaps
  stay in unless the owner listens and asks for the cut.
- **Motion plan:** 3-6 beats for a 1-3 minute video. For each beat give the source time range, the spoken words it explains, and
  what the viewer sees change (cause to effect, before and after, a growing count, a comparison). Add fullscreen inserts only with
  media you have. No static title cards.

Ask once: "Here are the cuts and the motion graphics I plan. Approve, or tell me what to change." Never apply cuts before the owner answers.

## 3. Cut, then author the motion

- `apply_cuts` with the approved cuts, then `get_status`.
  - `words_lost_near_cuts` non-empty, or a failed dialogue gate, means a cut clipped speech. Widen or drop that cut and apply again.
  - `asr_variance_far_from_cuts` lists words the second ASR pass missed in untouched audio. Mention them, but they are not lost words and they do not fail the gate.
- Convert the approved beat times to **edited** seconds with `time_map`, using `edited = edited_start_s + (source - source_start_s)`.
- Write the composition by following `motion_contract` exactly: `ledger.js` and `gsap.min.js` first, a full-canvas `#live`, and a
  synchronous `renderFrame(t)` built on a paused timeline with `seek`. Hide every scene outside its beat. Keep text inside x 120-960
  and y 220-1180, because captions sit at y 1240-1430.
- Run `submit_motion`, then `capture_motion('smoke')`, and look at the frames. Fix and resubmit if needed. Then run
  `capture_motion('proof')` and look at the contact sheet and the beat frames.
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
- **Report:** resolution, duration, the motion beats and inserts delivered (time and what each shows, from `beats_delivered`),
  caption count and suppressions, the crop and any flag, gate results, any words lost, and where the file is (Files -> Videos ->
  Edited, plus the `final_mp4` link). If it is plain, say why. Ask the owner to watch it on a phone before posting.
  Never call it approved: the gates check evidence, not taste.
