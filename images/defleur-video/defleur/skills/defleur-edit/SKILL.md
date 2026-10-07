---
name: defleur-edit
description: "Use when editing arbitrary source footage into a coherent, faithful short with DeFleur."
compatibility: "Requires an owner project and a designated media worker for production rendering."
metadata:
  workflow: defleur-video
  role: editorial-orchestrator
---

# DeFleur editorial orchestration

Use this skill to direct an arbitrary-source edit. It supplies a neutral workflow, not a pre-solved clip, visual identity, asset pack, or target duration.

## Start cleanly

1. Create or open an owner-controlled project outside the plugin. Keep source, derivatives, plans, output, and evidence in that project.
2. Resolve the preset in this order: explicit project preset / `defleur-preset.json`; active `${HERMES_HOME}/data/wizard-modules/defleur-video/presets/<name>.json`; module `defaults/neutral-preset.json`. Record the resolved preset and its hashes. Do not alter global provider settings.
3. Probe the actual source with `scripts/probe_source.py`. Preserve source duration, display dimensions, frame-rate mode, time base, audio layout, rotation, and frame count when available. The supplied PCM/picture mapper supports constant-frame-rate sources; for VFR footage, build a PTS ledger and use an explicitly tested VFR mapper rather than pretending frame arithmetic is exact.
4. Before creative work, task-local Hermes orchestration selects the owner-authorized Claude Opus creative-director route as the default. Check availability without entering credentials or changing global provider configuration. Record the resolved model identifier, client, effort, date, and capability result in project provenance. If the route is unavailable, stop for an owner-authorized alternative; do not silently substitute a model.

## Editorial lock

- Watch and transcribe the actual material. Infer language from ASR; ask the owner when confidence is low. Preserve claims, context, speaker meaning, and sentence syntax.
- Draft a short selection around a complete thought: premise, development, consequence or useful close. Make every deletion explicit in `edit-plan.json`, with a truthful reason. Do not invent facts or stitch together a change in meaning.
- On the **first draft and every material audio revision**, run a full assembled-audio filler/restart/pause scan. Record every candidate and either remove it safely or retain it with a concrete continuity reason. Ordinary ASR omissions are not evidence that no filler exists.
- Hand audio locking to `defleur-audio`; no visual timing is authoritative until its dialogue gate passes. An evidence gate checks coverage and custody. It does not prove perceptual perfection or replace actual listening.

## Picture, visual and caption planning

After audio lock, create a `locked-timeline.json` with the final duration, exact FPS representation, frame count, transcript and word timing. Build a cumulative source-picture ledger—never independently round each speech cut to a frame.

For every live range, identify camera/setup and calibrate a stable crop from real frames. Audit face containment across the full range. A crop is fixed per setup; detector-driven pans/zooms are not a substitute. Fullscreen art or a deliberate visual replacement is allowed only as a named range with a semantic reason and planned return to the speaker.

Write a beat plan before drawing. Each beat must name its spoken anchor, viewer inference, visual family, state before/after, causal action, readable copy, caption handling, and return behavior. Select varied neutral media families according to explanatory job (for example documentary evidence, a mechanism diagram, a photographed metaphor, typography, or an original illustration). Do not force one named aesthetic across the edit.

Delegate composition mechanics to `defleur-motion`. It must use actual HTML/SVG/GSAP state changes, not a sequence of static cards: objects must retain identity where meaning persists, and action must explain a causal relationship. It must expose deterministic `renderFrame(t)` that reconstructs the same scene on forward and backward seeks. Captions are burned after visual capture using the resolved neutral typography and safe rectangle; suppress them only in declared ranges where the visual conveys the same words.

## Required project records

Keep these human-authored records alongside machine output: source probe; transcript and alignment; edit plan; filler review; phonetic keep/drop regions; locked timeline; crop ledger; visual plan; creative-review/repair log; provider/model provenance; and delivery report. The schemas and tool contracts are in `references/project-contract.md`.

Production runs on the owner-authorized machine (including a suitable VPS); honor that owner’s placement rules and resource budget. Installation does no rendering. Read the package SETUP.md before beginning. Use scripts/preset.py to resolve defaults and detect an available sans font without asking the owner to design a style.
