# Project contract

A DeFleur project is owner-owned and lives outside the plugin. Suggested shape:

```text
project/
  source/                    # original media; never copied into the plugin
  work/                      # decoded PCM, maps, evidence
  plans/                     # editorial, visual, crop, and review records
  assets/                    # newly authorized project assets only
  render/                    # captured frames and candidate encodes
  result/                    # final MP4, captions, report, provenance
  defleur-preset.json        # optional project override
```

## Preset resolution

Resolve one JSON object: explicit project preset or `project/defleur-preset.json`, then `${HERMES_HOME}/data/wizard-modules/defleur-video/presets/<name>.json`, then `defaults/neutral-preset.json` in the package. Merge objects recursively with nearer project values winning. Record the resolved object and source hashes in `plans/preset-resolution.json`. Presets are owner configuration, never generated source or brand assets.

## Core record shapes

`edit-plan.json`: `{"segments":[{"start_s":number,"end_s":number,"reason":"truthful editorial reason"}]}`. It names decisions but is not proof that a cut is acoustically safe.

`locked-timeline.json`: `{"duration":number,"fps":"30000/1001","frames":integer,"words":[...],"transcript":"...","canvas":[1080,1920]}`. FPS can be any positive rational. The bundled PCM mapper requires CFR source cadence. A VFR project must instead include `pts-picture-ledger.json` mapping source PTS to output frames.

`crop-ledger.json`: `{"source_mode":"cfr"|"vfr-ledger","ranges":[{"start":number,"end":number,"setup":"id","crop":[x,y,w,h],"face_audit":"path/to/receipt.json"}],"fullscreen_exceptions":[{"start":number,"end":number,"reason":"semantic visual replacement"}]}`. Live ranges may not have animated detector-derived crops.

`visual-plan.json`: `{"beats":[{"start":number,"end":number,"spoken_anchor":"...","viewer_inference":"...","visual_family":"...","state_before":"...","state_after":"...","causal_action":"...","caption_treatment":"show"|"suppress","speaker_return":"..."}],"caption_suppress":[{"start":number,"end":number,"reason":"visual directly carries same words"}]}`. Every suppression range must correspond to a beat and must not be used merely to hide an unreadable layout.

`model-provenance.json`: record task-local creative-director requested route, actual resolved model, client, effort, capability result, timestamps, and errors. Record only identifiers and outcomes; never credentials. The default is an owner-authorized Claude Opus route, mediated by Hermes; provider changes need owner authorization and must not modify global selection.

A delivery report separates machine checks from creator viewing/listening. It must state unresolved issues plainly.
