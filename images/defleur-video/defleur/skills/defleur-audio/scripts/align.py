#!/usr/bin/env python3
"""Align transcript words with stable-ts; language must be explicit and supported.

Input transcript JSON is the output of asr.py. This helper is intentionally not
an automatic language fallback: the operator must capability-check the model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalized(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("asr_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", required=True)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    if not args.audio.is_file() or not args.asr_json.is_file():
        raise SystemExit("Audio and ASR JSON are required")
    source = json.loads(args.asr_json.read_text(encoding="utf-8"))
    detected = source.get("language_detected")
    if detected and detected != args.language:
        raise SystemExit(f"Refusing alignment: ASR detected {detected!r}, requested {args.language!r}. Resolve language before alignment.")
    words = source.get("words")
    if not isinstance(words, list) or not words:
        raise SystemExit("ASR JSON has no words to align")
    try:
        import importlib
        stable_whisper = importlib.import_module("stable_whisper")
    except ImportError as exc:
        raise SystemExit("Install stable-ts and its supported model runtime on the media worker.") from exc
    model = stable_whisper.load_model(args.model, device=args.device)
    transcript = " ".join(str(word.get("word", "")) for word in words)
    result = model.align(str(args.audio), transcript, language=args.language, original_split=False, regroup=False, fast_mode=False, verbose=False)
    aligned = [word for segment in result.to_dict().get("segments", []) for word in segment.get("words", [])]
    if normalized(transcript) != normalized("".join(str(word.get("word", "")) for word in aligned)):
        raise SystemExit("Alignment changed transcript characters; do not use it as a source map.")
    result.save_as_json(str(args.output))
    print(json.dumps({"aligned_words": len(aligned), "language": args.language, "model": args.model}))


if __name__ == "__main__":
    main()
