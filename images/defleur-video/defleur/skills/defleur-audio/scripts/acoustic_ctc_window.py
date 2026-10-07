#!/usr/bin/env python3
"""Run a local, explicit-language CTC second opinion for a short PCM window.

The model directory must contain model.onnx, vocab.json, and capabilities.json
with {"languages":["en", ...]}. Character peaks are not cut instructions.
"""
from __future__ import annotations

import argparse
import itertools
import json
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--start", required=True, type=float)
    parser.add_argument("--end", required=True, type=float)
    parser.add_argument("--language", required=True)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if not 0 <= args.start < args.end or args.end - args.start > 20:
        raise SystemExit("Use a source window no longer than 20 seconds.")
    capabilities_path = args.model_dir / "capabilities.json"
    try:
        capabilities = json.loads(capabilities_path.read_text(encoding="utf-8"))
        languages = capabilities["languages"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("CTC model needs capabilities.json with supported languages.") from exc
    if not isinstance(languages, list) or args.language not in languages:
        raise SystemExit(f"CTC model does not declare support for {args.language!r}.")
    required = [args.model_dir / name for name in ("model.onnx", "vocab.json")]
    if not all(path.is_file() for path in required):
        raise SystemExit("CTC model directory lacks model.onnx or vocab.json.")
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise SystemExit("Install numpy and onnxruntime on the media worker.") from exc
    with wave.open(str(args.wav), "rb") as reader:
        if (reader.getsampwidth(), reader.getnchannels(), reader.getframerate()) != (2, 1, 16000):
            raise SystemExit("Provide mono PCM s16 16 kHz WAV.")
        reader.setpos(round(args.start * 16000))
        audio = np.frombuffer(reader.readframes(round((args.end - args.start) * 16000)), np.int16).astype(np.float32) / 32768
    vocabulary = json.loads((args.model_dir / "vocab.json").read_text(encoding="utf-8"))
    inverse = {index: character for character, index in vocabulary.items()}
    options = ort.SessionOptions(); options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"])
    normalized = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
    logits = np.asarray(session.run(None, {"input_values": normalized[None]})[0])[0]
    entries = []
    for token, group in itertools.groupby(enumerate(logits.argmax(-1)), key=lambda value: int(value[1])):
        rows = list(group)
        if token:
            entries.append({"character": inverse.get(token, "?"), "start_s": args.start + rows[0][0] * 0.02, "end_s": args.start + (rows[-1][0] + 1) * 0.02})
    result = {"language": args.language, "model_capabilities": capabilities, "source_start_s": args.start, "source_end_s": args.end, "greedy_text": "".join(entry["character"] for entry in entries).replace("|", " "), "characters": entries, "limitation": "CTC spelling and peaks can be wrong; use only as local acoustic context alongside spectrum and listening."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"characters": len(entries), "language": args.language}))


if __name__ == "__main__":
    main()
