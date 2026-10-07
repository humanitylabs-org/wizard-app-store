#!/usr/bin/env python3
"""Fail-closed validator for a DeFleur audio evidence receipt.

This checks hashes and declared coverage; it is not a perceptual listening test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class GateError(ValueError):
    pass


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid {label}") from exc


def _artifact(root: Path, receipt: dict[str, Any], key: str) -> Path:
    item = receipt.get(key)
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        raise GateError(f"invalid artifact declaration: {key}")
    rel, want = item["path"], item["sha256"]
    if not isinstance(rel, str) or not isinstance(want, str):
        raise GateError(f"invalid artifact declaration: {key}")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise GateError(f"missing artifact: {key}")
    if _sha256(path) != want:
        raise GateError(f"stale artifact: {key}")
    return path


def _coverage(rows: Any, duration: float, label: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise GateError(f"empty {label}")
    end = 0.0
    for row in sorted(rows, key=lambda row: row.get("start", float("inf")) if isinstance(row, dict) else float("inf")):
        if not isinstance(row, dict):
            raise GateError(f"invalid {label} row")
        start, stop = row.get("start"), row.get("end")
        if not isinstance(start, (int, float)) or not isinstance(stop, (int, float)) or start >= stop:
            raise GateError(f"invalid {label} interval")
        if start > end + 0.03:
            raise GateError(f"gap in {label}")
        end = max(end, float(stop))
    if end < duration - 0.03:
        raise GateError(f"incomplete {label}")


def _hashed_file(root: Path, path_value: Any, digest_value: Any, label: str) -> None:
    if not isinstance(path_value, str) or not isinstance(digest_value, str):
        raise GateError(f"missing {label}")
    path = (root / path_value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or _sha256(path) != digest_value:
        raise GateError(f"stale or missing {label}")


def verify(project: str | Path, stage: str = "delivery") -> dict[str, Any]:
    root = Path(project).resolve()
    receipt = _load_json(root / "audio-gate.json", "audio-gate receipt")
    if not isinstance(receipt, dict) or receipt.get("version") != 3:
        raise GateError("unsupported receipt version")

    source = _artifact(root, receipt, "source")
    edited = _artifact(root, receipt, "edited")
    del source, edited
    edit_map = _load_json(_artifact(root, receipt, "edit_map"), "edit map")
    if not isinstance(edit_map, dict) or not isinstance(edit_map.get("duration"), (int, float)) or edit_map["duration"] <= 0:
        raise GateError("invalid edit map duration")
    segments = edit_map.get("segments")
    if not isinstance(segments, list) or not segments:
        raise GateError("edit map needs segments")
    _artifact(root, receipt, "phonetic_regions")
    regression = _load_json(_artifact(root, receipt, "cut_regression"), "cut regression")
    candidate = regression.get("candidate") if isinstance(regression, dict) else None
    if not isinstance(candidate, list) or not candidate or not all(isinstance(row, dict) and row.get("pass") is True for row in candidate):
        raise GateError("candidate phonetic checks did not pass")
    if receipt.get("repair_of"):
        baseline = regression.get("baseline")
        if not isinstance(baseline, list) or not any(isinstance(row, dict) and row.get("pass") is False for row in baseline):
            raise GateError("repair lacks failed immutable baseline")

    filler = _load_json(_artifact(root, receipt, "filler_review"), "filler review")
    if not isinstance(filler, dict) or filler.get("full_pass_reviewed") is not True:
        raise GateError("full filler scan not recorded")
    candidates = filler.get("candidates")
    if not isinstance(candidates, list) or (not candidates and filler.get("none_found") is not True):
        raise GateError("filler findings unresolved")
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("action") not in {"removed", "retained_with_reason"} or not isinstance(candidate.get("reason"), str) or not candidate["reason"].strip():
            raise GateError("filler findings unresolved")

    _coverage(_load_json(_artifact(root, receipt, "edited_acoustic_scan"), "edited scan"), float(edit_map["duration"]), "edited acoustic scan")
    expected = {(index, edge) for index in range(len(segments)) for edge in ("start", "end")}
    found: set[tuple[int, str]] = set()
    edges = receipt.get("reviewed_edges")
    if not isinstance(edges, list):
        raise GateError("missing reviewed edges")
    for edge in edges:
        if not isinstance(edge, dict):
            raise GateError("invalid reviewed edge")
        segment_index, edge_type = edge.get("segment"), edge.get("edge")
        if not isinstance(segment_index, int) or not isinstance(edge_type, str):
            raise GateError("invalid reviewed edge identity")
        pair = (segment_index, edge_type)
        if pair not in expected or pair in found:
            raise GateError("incomplete or duplicate reviewed edge")
        found.add(pair)
        if edge.get("decision") not in {"keep", "move", "restore_clause"} or not isinstance(edge.get("findings"), str) or not edge["findings"].strip():
            raise GateError("reviewed edge needs decision and findings")
        _hashed_file(root, edge.get("waveform_path"), edge.get("waveform_sha256"), "edge waveform")
        _hashed_file(root, edge.get("spectrogram_path"), edge.get("spectrogram_sha256"), "edge spectrogram")
    if found != expected:
        raise GateError("every segment edge needs waveform and spectrogram evidence")

    if stage == "delivery":
        for key in ("final", "decoded_final", "final_asr"):
            _artifact(root, receipt, key)
        _coverage(_load_json(_artifact(root, receipt, "final_acoustic_scan"), "final scan"), float(edit_map["duration"]), "final acoustic scan")
        integrity = _load_json(_artifact(root, receipt, "final_integrity"), "final integrity")
        if not isinstance(integrity, dict) or not all(integrity.get(key) is True for key in ("full_decode_pass", "caption_bounds_pass", "picture_map_verified")):
            raise GateError("final integrity checks incomplete")
        regions = integrity.get("source_regions")
        if not isinstance(regions, list) or not regions or not all(isinstance(region, dict) and isinstance(region.get("correlation"), (int, float)) and region["correlation"] >= 0.90 for region in regions):
            raise GateError("protected source-region custody failed")
    return {"pass": True, "stage": stage, "reviewed_edges": len(expected), "scope": "Evidence-bound custody and coverage only; no claim of human audible approval."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--stage", choices=("dialogue", "delivery"), default="delivery")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.project, args.stage), indent=2))
    except GateError as exc:
        raise SystemExit(f"audio gate: {exc}")


if __name__ == "__main__":
    main()
