#!/usr/bin/env python3
"""Validate lightweight project planning records without rendering media."""
from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def ordered_ranges(rows: object, label: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{label} must be nonempty")
    previous = 0.0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("start"), (int, float)) or not isinstance(row.get("end"), (int, float)) or row["start"] >= row["end"] or row["start"] < previous:
            raise ValueError(f"invalid {label} range")
        previous = float(row["end"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    root = args.project
    timeline, visual, crops = (load(root / name) for name in ("locked-timeline.json", "visual-plan.json", "crop-ledger.json"))
    fps = Fraction(str(timeline.get("fps")))
    if fps <= 0 or not isinstance(timeline.get("frames"), int) or timeline["frames"] <= 0 or not isinstance(timeline.get("duration"), (int, float)) or timeline["duration"] <= 0:
        raise ValueError("invalid locked timeline")
    ordered_ranges(visual.get("beats"), "visual beat")
    for beat in visual["beats"]:
        missing = [key for key in ("spoken_anchor", "viewer_inference", "visual_family", "state_before", "state_after", "causal_action", "caption_treatment", "speaker_return") if not isinstance(beat.get(key), str) or not beat[key].strip()]
        if missing:
            raise ValueError(f"beat missing semantic fields: {', '.join(missing)}")
    ordered_ranges(crops.get("ranges"), "crop")
    if crops.get("source_mode") not in {"cfr", "vfr-ledger"}:
        raise ValueError("crop ledger needs source_mode")
    if crops["source_mode"] == "vfr-ledger" and not (root / "pts-picture-ledger.json").is_file():
        raise ValueError("VFR crop ledger requires pts-picture-ledger.json")
    print(json.dumps({"pass": True, "fps": str(fps), "beats": len(visual["beats"]), "crop_ranges": len(crops["ranges"])}))


if __name__ == "__main__":
    main()
