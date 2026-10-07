#!/usr/bin/env python3
"""Synthetic, fail-closed tests for audio_gate.py; no production media claims."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).with_name("audio_gate.py")


class GateTests(unittest.TestCase):
    def test_dialogue_and_delivery_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def item(name: str, payload: object) -> dict[str, str]:
                content = payload if isinstance(payload, bytes) else json.dumps(payload, sort_keys=True).encode()
                path = root / name
                path.write_bytes(content)
                return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}

            receipt = {
                "version": 3,
                "source": item("source.bin", b"synthetic source"),
                "edited": item("edited.bin", b"synthetic edit"),
                "edit_map": item("edit-map.json", {"duration": 1.0, "segments": [{"start_sample": 0, "end_sample": 10}]}),
                "phonetic_regions": item("regions.json", [{"name": "synthetic", "mode": "keep"}]),
                "cut_regression": item("regression.json", {"candidate": [{"pass": True}]}),
                "filler_review": item("filler.json", {"full_pass_reviewed": True, "none_found": True, "candidates": []}),
                "edited_acoustic_scan": item("edited-scan.json", [{"start": 0, "end": 1.0}]),
            }
            waveform = item("edge-waveform.png", b"synthetic waveform")
            spectrogram = item("edge-spectrogram.png", b"synthetic spectrogram")
            receipt["reviewed_edges"] = [
                {"segment": 0, "edge": edge, "decision": "keep", "findings": "Synthetic checked evidence.", "waveform_path": waveform["path"], "waveform_sha256": waveform["sha256"], "spectrogram_path": spectrogram["path"], "spectrogram_sha256": spectrogram["sha256"]}
                for edge in ("start", "end")
            ]

            def run(value: dict, stage: str, optimized: bool = False) -> int:
                (root / "audio-gate.json").write_text(json.dumps(value), encoding="utf-8")
                command = [sys.executable, *( ["-O"] if optimized else []), str(GATE), str(root), "--stage", stage]
                return subprocess.run(command, capture_output=True, text=True).returncode

            self.assertEqual(run(receipt, "dialogue"), 0)
            self.assertEqual(run(receipt, "dialogue", optimized=True), 0)
            missing_edge = copy.deepcopy(receipt)
            missing_edge["reviewed_edges"].pop()
            self.assertNotEqual(run(missing_edge, "dialogue", optimized=True), 0)
            missing_spectrogram = copy.deepcopy(receipt)
            missing_spectrogram["reviewed_edges"][0].pop("spectrogram_sha256")
            self.assertNotEqual(run(missing_spectrogram, "dialogue"), 0)
            stale_edit = copy.deepcopy(receipt)
            stale_edit["edited"]["sha256"] = "0" * 64
            self.assertNotEqual(run(stale_edit, "dialogue", optimized=True), 0)
            unresolved = copy.deepcopy(receipt)
            unresolved["filler_review"] = item("unresolved.json", {"full_pass_reviewed": True, "candidates": [{"action": "unresolved", "reason": "synthetic"}]})
            self.assertNotEqual(run(unresolved, "dialogue"), 0)

            delivery = copy.deepcopy(receipt)
            delivery.update({
                "final": item("final.mp4", b"synthetic final"),
                "decoded_final": item("decoded.wav", b"synthetic decoded"),
                "final_asr": item("final-asr.json", {"synthetic": True}),
                "final_acoustic_scan": item("final-scan.json", [{"start": 0, "end": 1.0}]),
                "final_integrity": item("integrity.json", {"full_decode_pass": True, "caption_bounds_pass": True, "picture_map_verified": True, "source_regions": [{"correlation": 0.95}]}),
            })
            self.assertEqual(run(delivery, "delivery"), 0)
            stale_final = copy.deepcopy(delivery)
            stale_final["final"]["sha256"] = "f" * 64
            self.assertNotEqual(run(stale_final, "delivery"), 0)


if __name__ == "__main__":
    unittest.main()
