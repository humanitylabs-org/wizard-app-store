#!/usr/bin/env python3
"""Assemble reviewed PCM spans and emit a cumulative native-CFR picture map.

This intentionally supports constant-frame-rate source mapping only. `--fps` is
the native source/output cadence; supply a rational such as 30000/1001 and a
probed --source-frames count.
"""
from __future__ import annotations

import argparse
import json
import math
import wave
from fractions import Fraction
from pathlib import Path


def rate(value: str) -> Fraction:
    try:
        result = Fraction(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("fps must be a positive integer, decimal, or rational") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("fps must be positive")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--fps", required=True, type=rate)
    parser.add_argument("--source-frames", required=True, type=int)
    parser.add_argument("--plan", default="edit-plan.json")
    parser.add_argument("--source-wav", default="source.wav")
    args = parser.parse_args()
    if args.source_frames < 1:
        raise SystemExit("--source-frames must be positive")
    root = args.project.resolve()
    plan = json.loads((root / args.plan).read_text(encoding="utf-8"))
    requested = plan.get("segments") if isinstance(plan, dict) else None
    if not isinstance(requested, list) or not requested:
        raise SystemExit("edit plan needs nonempty segments")
    source = root / args.source_wav
    with wave.open(str(source), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise SystemExit("source WAV must be PCM s16")
        channels, sample_rate = reader.getnchannels(), reader.getframerate()
        frames = reader.getnframes()
        pcm = reader.readframes(frames)
    bytes_per_sample = 2 * channels
    parts, segments, output_samples = [], [], 0
    for index, segment in enumerate(requested):
        if not isinstance(segment, dict) or not all(isinstance(segment.get(key), (int, float)) for key in ("start_s", "end_s")):
            raise SystemExit(f"segment {index} needs numeric start_s/end_s")
        start, end = round(float(segment["start_s"]) * sample_rate), round(float(segment["end_s"]) * sample_rate)
        if not 0 <= start < end <= frames:
            raise SystemExit(f"segment {index} lies outside source audio")
        begin_byte, end_byte = start * bytes_per_sample, end * bytes_per_sample
        parts.append(pcm[begin_byte:end_byte])
        size = end - start
        segments.append({"start_s": start / sample_rate, "end_s": end / sample_rate, "start_sample": start, "end_sample": end, "output_start_sample": output_samples, "output_end_sample": output_samples + size, "output_start": output_samples / sample_rate, "output_end": (output_samples + size) / sample_rate, "reason": str(segment.get("reason", ""))})
        output_samples += size
    with wave.open(str(root / "edited.wav"), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"".join(parts))
    duration = output_samples / sample_rate
    output_frames = math.ceil(Fraction(output_samples, sample_rate) * args.fps)
    indices = []
    for frame in range(output_frames):
        output_sample = Fraction(frame * sample_rate, 1) / args.fps
        source_segment = next(segment for segment in segments if segment["output_start_sample"] <= output_sample < segment["output_end_sample"])
        source_sample = Fraction(source_segment["start_sample"], 1) + output_sample - source_segment["output_start_sample"]
        source_index = math.floor(source_sample * args.fps / sample_rate)
        indices.append(min(args.source_frames - 1, max(0, source_index)))
    result = {"duration": duration, "frames": output_frames, "fps": str(args.fps), "sample_rate": sample_rate, "channels": channels, "samples": output_samples, "segments": segments, "source_frame_indices": indices, "limitation": "CFR mapping only. For variable-frame-rate source, use a verified PTS ledger instead of this map."}
    (root / "edit-map.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"seconds": duration, "frames": output_frames, "fps": str(args.fps), "segments": len(segments)}))


if __name__ == "__main__":
    main()
