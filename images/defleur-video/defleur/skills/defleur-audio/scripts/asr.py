#!/usr/bin/env python3
"""Transcribe locally with faster-whisper and record detected-language evidence.

Example: python asr.py input.wav source-asr.json --language auto --model large-v3-turbo
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--language", default="auto", help="BCP-47/Whisper code, or auto for inference")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit("ASR input does not exist")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("Install faster-whisper on the media worker before ASR.") from exc
    started = time.monotonic()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    language = None if args.language == "auto" else args.language
    segments, info = model.transcribe(str(args.input), language=language, beam_size=5, word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
    words, rows = [], []
    for segment in segments:
        segment_words = []
        for word in segment.words or []:
            item = {"id": len(words), "word": word.word.strip(), "start": word.start, "end": word.end, "probability": word.probability}
            words.append(item)
            segment_words.append(item)
        rows.append({"start": segment.start, "end": segment.end, "text": segment.text, "words": segment_words})
    result = {"model_requested": args.model, "model_resolved": args.model, "device": args.device, "compute_type": args.compute_type, "language_requested": args.language, "language_detected": getattr(info, "language", None), "language_probability": getattr(info, "language_probability", None), "duration": getattr(info, "duration", None), "words": words, "segments": rows, "seconds": round(time.monotonic() - started, 3), "limitation": "ASR can omit fillers or miss words; it is a navigation and scan input, not a complete editorial truth."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"words": len(words), "language_detected": result["language_detected"], "seconds": result["seconds"]}))


if __name__ == "__main__":
    main()
