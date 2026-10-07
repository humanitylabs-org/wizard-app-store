# Audio evidence receipt contract

All paths in a receipt are relative to the project root and hash-bound with SHA-256.

## Dialogue stage (receipt version 3)

Required artifact fields: `source`, `edited`, `edit_map`, `phonetic_regions`, `cut_regression`, `filler_review`, and `edited_acoustic_scan`. Each is an object: `{"path":"relative/path","sha256":"..."}`.

`edit_map.json` contains a positive `duration` and nonempty `segments`. `cut_regression.json` contains nonempty `candidate` entries, all with `pass:true`; a repair receipt includes `repair_of` and a nonempty `baseline` with at least one failed entry. `filler-review.json` has `full_pass_reviewed:true`, and either nonempty dispositioned candidates or `none_found:true`. Candidate actions are `removed` or `retained_with_reason` and must have a nonempty reason.

`edited-acoustic-scan.json` is a nonempty array of `{start,end,...}` intervals that cover 0 through edit duration, allowing a maximum 30 ms gap.

`reviewed_edges` has exactly one `start` and one `end` item for every segment. Each item has `segment`, `edge`, `decision` (`keep`, `move`, `restore_clause`), nonempty `findings`, plus `waveform_path`, `waveform_sha256`, `spectrogram_path`, and `spectrogram_sha256`. The validator requires both independent image files and their hashes.

## Delivery additions

Also bind `final`, `decoded_final`, `final_acoustic_scan`, `final_asr`, and `final_integrity`. The integrity record requires `full_decode_pass:true`, `caption_bounds_pass:true`, `picture_map_verified:true`, and nonempty `source_regions` whose `correlation` values are at least 0.90. This numerical floor is custody evidence, not a perceptual guarantee.

Run `python audio_gate.py PROJECT --stage dialogue` before graphics and `--stage delivery` after exact-final decode. The standard-library gate fails on missing or stale evidence. It does not perform human listening, semantic editorial review, or a claim of audible perfection.
