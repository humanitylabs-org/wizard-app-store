#!/usr/bin/env python3
"""App-original helper (not part of James DeFleur's plugin).

Cut a PCM s16 WAV into adjacent, slightly overlapping windows covering the whole
file and emit a separate waveform and spectrogram PNG plus RMS/peak numbers per
window. It is evidence for an operator's full-pass acoustic/filler scan; it does
not decide anything and is not a listening test.
"""
from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--window", type=float, default=5.0)
    parser.add_argument("--overlap", type=float, default=0.25)
    args = parser.parse_args()
    if not 1.0 <= args.window <= 20.0 or not 0 <= args.overlap < args.window / 2:
        raise SystemExit("window must be 1..20 s and overlap smaller than half a window")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plot
    import numpy as np
    with wave.open(str(args.wav), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise SystemExit("WAV must be PCM s16")
        rate, channels = reader.getframerate(), reader.getnchannels()
        samples = np.frombuffer(reader.readframes(reader.getnframes()), np.int16).reshape(-1, channels).mean(axis=1) / 32768.0
    duration = len(samples) / rate
    if duration <= 0:
        raise SystemExit("empty WAV")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows, start, index = [], 0.0, 0
    step = args.window - args.overlap
    while start < duration:
        end = min(duration, start + args.window)
        chunk = samples[round(start * rate):round(end * rate)]
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
        peak = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
        stem = f"window-{index:03d}"
        figure, axis = plot.subplots(figsize=(10, 2.5))
        axis.plot(np.arange(len(chunk)) / rate + start, chunk, linewidth=0.5)
        axis.set(title=f"edited waveform {start:.2f}-{end:.2f}s", xlabel="seconds", ylabel="amplitude", ylim=(-1, 1))
        figure.tight_layout(); figure.savefig(args.output_dir / f"{stem}-waveform.png", dpi=110); plot.close(figure)
        figure, axis = plot.subplots(figsize=(10, 3))
        if len(chunk) >= 512:
            axis.specgram(chunk, NFFT=512, Fs=rate, noverlap=384, xextent=(start, end))
        axis.set(title=f"edited spectrogram {start:.2f}-{end:.2f}s", xlabel="seconds", ylabel="Hz")
        figure.tight_layout(); figure.savefig(args.output_dir / f"{stem}-spectrogram.png", dpi=110); plot.close(figure)
        rows.append({"index": index, "start": round(start, 6), "end": round(end, 6),
                     "rms_dbfs": round(20 * math.log10(rms), 2) if rms > 0 else None,
                     "peak_dbfs": round(20 * math.log10(peak), 2) if peak > 0 else None,
                     "waveform": f"{stem}-waveform.png", "spectrogram": f"{stem}-spectrogram.png"})
        index += 1
        if end >= duration:
            break
        start += step
    result = {"duration": duration, "sample_rate": rate, "window_s": args.window, "overlap_s": args.overlap,
              "windows": rows, "basis": "Machine-generated windows only; an operator must inspect each pair and record findings."}
    (args.output_dir / "acoustic-windows.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"windows": len(rows), "duration": duration}))


if __name__ == "__main__":
    main()
