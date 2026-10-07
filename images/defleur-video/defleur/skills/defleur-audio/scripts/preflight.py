#!/usr/bin/env python3
"""Check declared local dependencies and probe a supplied source; no downloads."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--language", required=True)
    parser.add_argument("--acoustic-model-dir", type=Path)
    args = parser.parse_args()
    missing = [name for name in ("ffmpeg", "ffprobe", "node") if not shutil.which(name)]
    missing.extend(name for name in ("numpy", "matplotlib", "PIL", "faster_whisper", "stable_whisper") if importlib.util.find_spec(name) is None)
    capabilities = None
    if args.acoustic_model_dir:
        try:
            capabilities = json.loads((args.acoustic_model_dir / "capabilities.json").read_text(encoding="utf-8"))
            if args.language not in capabilities.get("languages", []):
                missing.append(f"CTC support for {args.language}")
        except (OSError, json.JSONDecodeError):
            missing.append("CTC capabilities.json")
    if not args.source.is_file():
        missing.append("source file")
    result = {"passed": not missing, "missing": missing, "language": args.language, "acoustic_model_capabilities": capabilities, "scope": "Dependency and declared-language capability check only; no model download, provider call, or media judgment."}
    if args.source.is_file() and shutil.which("ffprobe"):
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.source)], capture_output=True, text=True)
        result["ffprobe_returncode"] = probe.returncode
        if probe.returncode == 0:
            result["streams"] = [{key: stream.get(key) for key in ("codec_type", "codec_name", "width", "height", "r_frame_rate", "avg_frame_rate", "time_base")} for stream in json.loads(probe.stdout).get("streams", [])]
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
