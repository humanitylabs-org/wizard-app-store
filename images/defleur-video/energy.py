#!/usr/bin/env python3
"""App-original helper (not part of James DeFleur's plugin).

Write a 10 ms RMS energy envelope (dBFS per frame) of a PCM s16 WAV. The app uses it
to check that a proposed or applied cut is actually near-silent: ASR can skip whole
sentences, and a gap in the transcript is not proof of silence.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--frame", type=float, default=0.01)
    args = parser.parse_args()
    import numpy as np
    with wave.open(str(args.wav), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise SystemExit("WAV must be PCM s16")
        rate, channels, total = reader.getframerate(), reader.getnchannels(), reader.getnframes()
        hop = max(1, round(rate * args.frame))
        db: list[float] = []
        carry = np.zeros(0, np.float64)
        while True:
            raw = reader.readframes(rate * 30)  # stream 30 s at a time: bounded memory for long sources
            if not raw:
                break
            x = np.frombuffer(raw, np.int16).reshape(-1, channels).astype(np.float64).mean(axis=1) / 32768.0
            x = np.concatenate([carry, x])
            n = len(x) // hop
            frames = x[: n * hop].reshape(n, hop)
            power = np.mean(frames ** 2, axis=1)
            db.extend(np.where(power > 0, 10 * np.log10(np.maximum(power, 1e-30)), -120.0).round(1).tolist())
            carry = x[n * hop:]
        if len(carry):
            p = float(np.mean(carry ** 2))
            db.append(round(10 * np.log10(p), 1) if p > 0 else -120.0)
    out = {"frame_s": hop / rate, "sample_rate": rate, "samples": total, "dbfs": [max(-120.0, v) for v in db],
           "basis": "RMS dBFS per frame of the 48 kHz PCM source (mono mix); evidence for silence checks, not a VAD model."}
    args.out.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"frames": len(db), "frame_s": out["frame_s"]}))


if __name__ == "__main__":
    main()
