#!/usr/bin/env python3
"""Probe source media and reject unsupported CFR assumptions explicitly."""
from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path


def fraction_or_none(value: object) -> str | None:
    if not isinstance(value, str) or value in {"", "0/0", "N/A"}:
        return None
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return str(parsed) if parsed > 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit("source file does not exist")
    command = ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(args.source)]
    probe = subprocess.run(command, capture_output=True, text=True)
    if probe.returncode:
        raise SystemExit(f"ffprobe failed: {probe.stderr.strip()}")
    raw = json.loads(probe.stdout)
    video = next((stream for stream in raw.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in raw.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise SystemExit("source has no video stream")
    nominal, average = fraction_or_none(video.get("r_frame_rate")), fraction_or_none(video.get("avg_frame_rate"))
    stamps = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(args.source)], text=True))['frames']
    pts = [float(row['best_effort_timestamp_time']) for row in stamps if 'best_effort_timestamp_time' in row]
    tick = float(Fraction(video.get('time_base', '1/1000000')))
    step = 1 / float(Fraction(nominal)) if nominal else 0
    cfr = bool(step and len(pts) == len(stamps) and len(pts) >= 2 and abs(pts[0]) <= tick * 1.1 and all(abs((t - pts[0]) - i * step) <= max(tick * 1.1, 0.000002) for i, t in enumerate(pts)))
    result = {"source": args.source.name, "duration": raw.get("format", {}).get("duration"), "video": {key: video.get(key) for key in ("codec_name", "width", "height", "rotation", "time_base", "nb_read_frames", "nb_frames")}, "audio": ({key: audio.get(key) for key in ("codec_name", "sample_rate", "channels", "channel_layout")} if audio else None), "fps": {"r_frame_rate": nominal, "avg_frame_rate": average, "constant_frame_rate": cfr}, "mapping_support": "cfr-frame-map" if cfr else "requires-pts-picture-ledger", "limitation": None if cfr else "Variable or ambiguous frame cadence: do not use frame = time × fps mapping; author and verify a PTS ledger."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
