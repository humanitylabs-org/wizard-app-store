#!/usr/bin/env python3
"""Create separate waveform and spectrogram evidence for every retained edge.

Requires numpy and matplotlib. The checks are mathematical coverage checks, not
human audition; inspect each emitted pair before recording the receipt.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def coverage(blocks: list[dict], regions: list[dict]) -> list[dict]:
    results = []
    for region in regions:
        if not isinstance(region, dict) or region.get("mode") not in {"keep", "drop"}:
            raise ValueError("regions need mode keep or drop")
        start, end = float(region["start_s"]), float(region["end_s"])
        if start >= end:
            raise ValueError("region start must precede end")
        overlaps = sorted((max(start, float(block["source_start_s"])), min(end, float(block["source_end_s"]))) for block in blocks if float(block["source_start_s"]) < end and float(block["source_end_s"]) > start)
        merged: list[list[float]] = []
        for low, high in overlaps:
            if merged and low <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        retained = sum(high - low for low, high in merged)
        wanted = end - start if region["mode"] == "keep" else 0.0
        results.append({**region, "retained_s": retained, "pass": abs(retained - wanted) < 1e-6})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-wav", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path, help="JSON {blocks:[{id,source_start_s,source_end_s}]} from the real edit map")
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, help="Optional immutable baseline block manifest for a repair")
    args = parser.parse_args()
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plot
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Install numpy and matplotlib on the media worker.") from exc
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    blocks = manifest.get("blocks") if isinstance(manifest, dict) else None
    regions = json.loads(args.regions.read_text(encoding="utf-8"))
    if not isinstance(blocks, list) or not blocks or not isinstance(regions, list) or not regions:
        raise SystemExit("manifest blocks and reviewed regions must be nonempty")
    with wave.open(str(args.source_wav), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise SystemExit("source WAV must be PCM s16")
        sample_rate, channels = reader.getframerate(), reader.getnchannels()
        samples = np.frombuffer(reader.readframes(reader.getnframes()), np.int16).reshape(-1, channels).mean(axis=1) / 32768.0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence = []
    for block_index, block in enumerate(blocks):
        if not (0 <= float(block["source_start_s"]) < float(block["source_end_s"]) <= len(samples) / sample_rate):
            raise ValueError("Invalid source block bounds")
        for edge in ("start", "end"):
            time = float(block[f"source_{edge}_s"])
            low, high = max(0.0, time - 0.8), min(len(samples) / sample_rate, time + 0.8)
            chunk = samples[round(low * sample_rate):round(high * sample_rate)]
            stem = f"{block_index}-{edge}"
            waveform = args.output_dir / f"{stem}-waveform.png"
            spectrogram = args.output_dir / f"{stem}-spectrogram.png"
            figure, axis = plot.subplots(figsize=(10, 2.5))
            axis.plot(np.arange(len(chunk)) / sample_rate + low, chunk, linewidth=0.6)
            axis.axvline(time, color="#cc3344", linestyle="--")
            axis.set(title=f"source waveform: {block['id']} {edge}", xlabel="seconds", ylabel="amplitude")
            figure.tight_layout(); figure.savefig(waveform, dpi=140); plot.close(figure)
            figure, axis = plot.subplots(figsize=(10, 3))
            axis.specgram(chunk, NFFT=256, Fs=sample_rate, noverlap=224, xextent=(low, high))
            axis.axvline(time, color="white", linestyle="--")
            axis.set(title=f"source spectrogram: {block['id']} {edge}", xlabel="seconds", ylabel="Hz")
            figure.tight_layout(); figure.savefig(spectrogram, dpi=140); plot.close(figure)
            evidence.append({"segment": block["id"], "edge": edge, "source_s": time, "waveform": waveform.name, "spectrogram": spectrogram.name})
    receipt = {"basis": "Reviewed keep/drop regions plus separate waveform and spectrogram at every retained edge; not human-audition proof.", "candidate": coverage(blocks, regions), "edges": evidence}
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        receipt["baseline"] = coverage(baseline.get("blocks", []), regions)
    receipt["pass"] = all(row["pass"] for row in receipt["candidate"])
    (args.output_dir / "cut-regression.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if receipt["pass"] else 1)


if __name__ == "__main__":
    main()
