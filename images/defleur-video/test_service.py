"""Bounded real-FFmpeg and authenticated HTTP regression suite."""
from contextlib import closing
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import copy
import sys
import wave
from unittest.mock import patch
from typing import Any

import service


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="defleur-test-", dir=os.environ.get("TMPDIR"))
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                        "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-movflags", "+faststart", str(cls.source)],
                       check=True, timeout=30)
        cls.token = secrets.token_hex(24)
        cls.server = service.make_server(cls.root / "data", cls.token, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.store.close()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, method, path, body=None, kind="application/json", auth=True) -> tuple[int, Any]:
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=45)
        headers = {"Content-Type": kind}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        c.request(method, path, body, headers)
        response = c.getresponse()
        status, mime = response.status, response.getheader("Content-Type")
        data = response.read()
        c.close()
        return status, json.loads(data) if mime == "application/json" else data

    def test_connections_commit_rollback_and_close_without_gc(self):
        # Hold strong references so garbage collection cannot hide a leak.
        store = service.Store(self.root / "connection-regression")
        store.stop.set(); store.worker.join(timeout=2)
        connections = []
        real_connect = sqlite3.connect
        def tracked(*args, **kwargs):
            c = real_connect(*args, **kwargs)
            if Path(args[0]) == store.db:
                connections.append(c)
            return c
        try:
            with patch.object(service.sqlite3, "connect", side_effect=tracked):
                with store.connect() as c:
                    c.execute("CREATE TABLE probe(value TEXT)")
                    c.execute("INSERT INTO probe VALUES ('committed')")
                with self.assertRaisesRegex(RuntimeError, "rollback"):
                    with store.connect() as c:
                        c.execute("INSERT INTO probe VALUES ('rolled back')")
                        raise RuntimeError("rollback")
                for _ in range(200):
                    with store.connect() as c:
                        self.assertEqual([r[0] for r in c.execute("SELECT value FROM probe")], ["committed"])
                for c in connections:
                    with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                        c.execute("SELECT 1")
            self.assertEqual(len(connections), 202)
        finally:
            store.close()

    def test_idle_worker_closes_connections(self):
        connections = []
        real_connect = sqlite3.connect
        def tracked(*args, **kwargs):
            c = real_connect(*args, **{**kwargs, "check_same_thread": False})
            if Path(args[0]) == self.root / "idle-regression" / "state.sqlite3":
                connections.append(c)
            return c
        with patch.object(service.sqlite3, "connect", side_effect=tracked):
            store = service.Store(self.root / "idle-regression")
            time.sleep(.4)
            store.close()
        self.assertGreaterEqual(len(connections), 2)
        for c in connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                c.execute("SELECT 1")

    def test_helper_hash_and_symlink_rejected(self):
        import workflow
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            root = Path(temp)
            rel, _ = workflow.HELPERS['assemble_pcm']
            file = root / rel
            file.parent.mkdir(parents=True)
            file.write_text('raise RuntimeError("must never execute")')
            with patch.object(workflow, 'UPSTREAM_ROOT', root):
                with self.assertRaisesRegex(service.Rejected, 'hash mismatch'):
                    workflow.helper('assemble_pcm')
                self.assertFalse(workflow.capabilities(False)['helpers']['assemble_pcm']['available'])
                file.unlink()
                file.symlink_to(self.source)
                with self.assertRaisesRegex(service.Rejected, 'missing'):
                    workflow.helper('assemble_pcm')

    def test_bundled_helpers_match_upstream_hashes(self):
        import workflow
        for name in workflow.HELPERS:
            workflow.helper(name)
        self.assertEqual(workflow.sha(workflow.UPSTREAM_ROOT / workflow.DEFAULTS[0]), workflow.DEFAULTS[1])
        caps = workflow.capabilities(False)
        self.assertTrue(all(h['available'] for h in caps['helpers'].values()))
        self.assertFalse(caps['acoustic_ctc']['available'])

    def test_actual_vfr_requires_picture_ledger(self):
        import workflow
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            root = Path(temp)
            source = root / 'vfr.mp4'
            subprocess.run(['/usr/bin/ffmpeg', '-v', 'error', '-i', str(self.source),
                '-vf', 'select=not(eq(n\\,5))', '-fps_mode', 'vfr', '-c:v', 'libx264',
                '-threads', '1', '-c:a', 'copy', str(source)], check=True, timeout=30)
            metadata = service.probe(source)
            result = workflow.run('source-audio', {}, source, root / 'probe', metadata,
                service.native, None, time.monotonic() + 60, service.input_args)
            receipt = json.loads((root / 'probe/source-probe.json').read_text())
            self.assertFalse(receipt['fps']['constant_frame_rate'])
            self.assertEqual(receipt['mapping_support'], 'requires-pts-picture-ledger')
            self.assertFalse(result['summary']['constant_frame_rate'])
            fake = {'result': result}
            with self.assertRaisesRegex(service.Rejected, 'CFR'):
                workflow.validate('pcm-assemble', {'audio_job': 'a' * 32, 'segments': [{'start_s': 0, 'end_s': 1, 'reason': 'VFR rejection'}]},
                                  metadata, lambda jid, stages: (fake, root / 'probe'))

    def fake_transcriber(self, words, models=("Systran/faster-whisper-small",)):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = []
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def reply(self, value):
                data = json.dumps(value).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                self.reply({"data": [{"id": m} for m in models]})
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                seen.append(body)
                self.reply({"language": "en", "duration": 2.0, "text": " ".join(w["word"] for w in words),
                            "segments": [{"id": 0, "start": 0.0, "end": 2.0, "text": "x"}], "words": words})
        server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}", seen

    def stage(self, pid, name, value, ok=True):
        from client import Client
        client = Client(f"http://127.0.0.1:{self.server.server_port}", self.token)
        status, job = self.request("POST", f"/v1/projects/{pid}/stages/{name}", json.dumps(value))
        self.assertEqual(status, 202, job)
        job = client.wait(job["id"], True)
        if ok:
            self.assertEqual(job["state"], "needs_review", job.get("error"))
            self.assertFalse(job["delivery_approved"])
        return job

    def test_piece1_stages_over_http(self):
        import workflow
        from client import Client
        client = Client(f"http://127.0.0.1:{self.server.server_port}", self.token)
        pid = client.upload(self.source)["id"]
        other = client.upload(self.source)["id"]
        src = self.stage(pid, "source-audio", {})
        self.assertEqual(src["result"]["summary"]["frames"], 48)
        self.assertTrue(src["result"]["summary"]["constant_frame_rate"])
        self.assertEqual(src["result"]["helpers"]["probe_source"], workflow.HELPERS["probe_source"][1])
        bundle = self.root / "source-stage-bundle"
        client.stage_bundle(src["id"], bundle)
        self.assertEqual(json.loads((bundle / "source-probe.json").read_text())["fps"]["r_frame_rate"], "24")
        self.assertEqual(self.request("GET", f"/v1/jobs/{src['id']}/stage-artifacts/source.wav", auth=False)[0], 401)
        self.assertEqual(self.request("GET", f"/v1/jobs/{src['id']}/stage-artifacts/secrets.json")[0], 404)
        self.assertEqual(self.request("GET", f"/v1/jobs/{src['id']}/preview")[0], 409)
        # Never paths, shell, unknown stages or cross-project references.
        for stage, value in [("shell", {}), ("source-audio", {"command": "id"}),
                             ("pcm-assemble", {"audio_job": src["id"], "segments": [{"start_s": 0, "end_s": 1, "reason": "x"}], "path": "/etc"}),
                             ("asr", {"audio_job": "../../etc/passwd", "language": "en"}),
                             ("resolve-preset", {"owner": {"caption": {"font_path": "/etc/passwd"}}}),
                             ("pcm-assemble", {"audio_job": src["id"], "segments": [{"start_s": 0, "end_s": 9, "reason": "beyond source"}]})]:
            self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/{stage}", json.dumps(value))[0], 422, (stage, value))
        self.assertEqual(self.request("POST", f"/v1/projects/{other}/stages/pcm-assemble",
            json.dumps({"audio_job": src["id"], "segments": [{"start_s": 0, "end_s": 1, "reason": "x"}]}))[0], 422)

        preset = self.stage(pid, "resolve-preset", {"owner": {"caption": {"max_words": 4}}, "project": {"caption": {"max_words": 3}}})
        bundle = self.root / "preset-stage-bundle"
        client.stage_bundle(preset["id"], bundle)
        resolved = json.loads((bundle / "preset-resolution.json").read_text())
        self.assertEqual(resolved["preset"]["caption"]["max_words"], 3)
        self.assertEqual(len(resolved["sources"]), 3)
        self.assertTrue(resolved["preset"]["caption"]["font_path"].startswith("/usr/share/fonts/"))

        pre = self.stage(pid, "preflight", {"language": "en"})
        self.assertEqual(pre["result"]["summary"]["piece_1_blockers"], [], pre["result"]["summary"])

        words = [{"word": " Hello", "start": 0.1, "end": 0.4, "probability": 0.9}, {"word": " um", "start": 0.6, "end": 0.9, "probability": 0.5},
                 {"word": " world.", "start": 1.2, "end": 1.6, "probability": 0.9}]
        url, seen = self.fake_transcriber(words)
        with patch.dict(os.environ, {"TRANSCRIBER_URL": url}):
            asr = self.stage(pid, "asr", {"audio_job": src["id"], "language": "en"})
        bundle = self.root / "asr-stage-bundle"
        client.stage_bundle(asr["id"], bundle)
        receipt = json.loads((bundle / "asr.json").read_text())
        for key in ("model_requested", "model_resolved", "device", "compute_type", "language_requested", "language_detected",
                    "language_probability", "duration", "words", "segments", "seconds", "limitation"):
            self.assertIn(key, receipt)
        self.assertEqual([w["word"] for w in receipt["words"]], ["Hello", "um", "world."])
        self.assertEqual([w["id"] for w in receipt["words"]], [0, 1, 2])
        self.assertEqual(receipt["segments"][0]["words"][1]["word"], "um")
        self.assertEqual(receipt["provenance"]["audio_sha256"], hashlib.sha256((bundle / "asr-input.wav").read_bytes()).hexdigest())
        self.assertIn(b'name="timestamp_granularities[]"\r\n\r\nword', seen[0])
        with wave.open(str(bundle / "asr-input.wav")) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1))
        # Transcriber absent or model missing: clear failure, no fake transcript.
        with patch.dict(os.environ, {"TRANSCRIBER_URL": "http://127.0.0.1:9"}):
            failed = self.stage(pid, "asr", {"audio_job": src["id"], "language": "en"}, ok=False)
        self.assertEqual(failed["state"], "failed")
        self.assertIn("Install the Transcriber app", failed["error"])
        url2, _ = self.fake_transcriber(words, models=("other/model",))
        with patch.dict(os.environ, {"TRANSCRIBER_URL": url2}):
            failed = self.stage(pid, "asr", {"audio_job": src["id"], "language": "en"}, ok=False)
        self.assertIn("not installed", failed["error"])
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/align", json.dumps({"asr_job": asr["id"], "language": "de"}))[0], 422)
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/align", json.dumps({"asr_job": asr["id"], "language": "en", "model": "../x"}))[0], 422)
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/acoustic-ctc",
            json.dumps({"asr_job": asr["id"], "language": "en", "start_s": 0, "end_s": 1}))[0], 422)

        # Cut the filler "um" (0.5-1.1 s).
        segments = [{"start_s": 0, "end_s": .5, "reason": "Hello"}, {"start_s": 1.1, "end_s": 2, "reason": "world, filler removed"}]
        asm = self.stage(pid, "pcm-assemble", {"audio_job": src["id"], "segments": segments})
        self.assertAlmostEqual(asm["result"]["summary"]["duration_s"], 1.4, places=6)
        bundle = self.root / "pcm-stage-bundle"
        client.stage_bundle(asm["id"], bundle)
        ledger = json.loads((bundle / "edit-map.json").read_text())
        self.assertEqual(ledger["samples"], int(1.4 * 48000))
        with wave.open(str(bundle / "source.wav")) as s, wave.open(str(bundle / "edited.wav")) as e:
            s.setpos(int(1.1 * 48000)); tail = s.readframes(int(.9 * 48000))
            e.setpos(int(.5 * 48000)); self.assertEqual(e.readframes(int(.9 * 48000)), tail)
        regions = [{"mode": "keep", "start_s": .1, "end_s": .4, "word": "Hello"}, {"mode": "drop", "start_s": .6, "end_s": .9, "word": "um"},
                   {"mode": "keep", "start_s": 1.2, "end_s": 1.6, "word": "world"}]
        audit = self.stage(pid, "speech-cut-audit", {"assemble_job": asm["id"], "regions": regions})
        self.assertTrue(audit["result"]["summary"]["pass"])
        self.assertEqual(audit["result"]["summary"]["edges"], 4)
        names = {a["name"] for a in audit["result"]["artifacts"]}
        self.assertTrue({"0-start-waveform.png", "1-end-spectrogram.png", "cut-regression.json"} <= names)
        bad = self.stage(pid, "speech-cut-audit", {"assemble_job": asm["id"], "regions": [{"mode": "keep", "start_s": .6, "end_s": .9}]})
        self.assertFalse(bad["result"]["summary"]["pass"])
        scan = self.stage(pid, "acoustic-scan", {"assemble_job": asm["id"], "window_s": 1.0})
        windows = scan["result"]["summary"]["windows"]
        self.assertEqual(windows, 2)
        gate = {"assemble_job": asm["id"], "audit_job": audit["id"], "scan_job": scan["id"],
                "filler_review": {"full_pass_reviewed": True, "candidates": [{"word": "um", "source_start_s": .6, "source_end_s": .9, "action": "removed", "reason": "hesitation filler"}]},
                "acoustic_review": [{"window": i, "findings": "synthetic tone; no clicks visible"} for i in range(windows)],
                "reviewed_edges": [{"segment": s, "edge": e, "decision": "keep", "findings": "synthetic tone edge"} for s in (0, 1) for e in ("start", "end")]}
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/dialogue-gate", json.dumps({**gate, "acoustic_review": gate["acoustic_review"][:1]}))[0], 422)
        result = self.stage(pid, "dialogue-gate", gate)
        self.assertTrue(result["result"]["summary"]["dialogue_gate_pass"], result["result"]["summary"])
        self.assertEqual(result["result"]["helpers"]["audio_gate"], workflow.HELPERS["audio_gate"][1])
        missing = self.stage(pid, "dialogue-gate", {**gate, "reviewed_edges": gate["reviewed_edges"][:3]})
        self.assertFalse(missing["result"]["summary"]["dialogue_gate_pass"])
        self.assertIn("every segment edge", missing["result"]["summary"]["error"])
        failing = self.stage(pid, "dialogue-gate", {**gate, "audit_job": bad["id"]})
        self.assertIn("phonetic checks did not pass", failing["result"]["summary"]["error"])

        # Piece 2: face audit / fixed crop, James' caption_layer + encode.py, delivery gate (no face in testsrc2 -> flagged).
        with patch.dict(os.environ, {"TRANSCRIBER_URL": url}):
            easr = self.stage(pid, "asr", {"audio_job": asm["id"], "language": "en"})
        crop = self.stage(pid, "face-crop", {"assemble_job": asm["id"]})
        cs = crop["result"]["summary"]
        self.assertFalse(cs["pass"])
        self.assertIn("no face found: centered crop", cs["setups"][0]["flags"])
        self.assertEqual(cs["setups"][0]["crop"], [110, 0, 100, 180])
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/final-render",
                         json.dumps({"assemble_job": asm["id"], "crop_job": crop["id"], "edited_asr_job": asr["id"]}))[0], 422)
        render = self.stage(pid, "final-render", {"assemble_job": asm["id"], "crop_job": crop["id"], "edited_asr_job": easr["id"]})
        rs = render["result"]["summary"]
        self.assertEqual((rs["width"], rs["height"], rs["frames"]), (1080, 1920, 34), rs)
        self.assertTrue(all(v is True for k, v in rs["checks"].items() if k != "min_source_region_correlation"), rs["checks"])
        self.assertGreaterEqual(rs["checks"]["min_source_region_correlation"], 0.99)
        self.assertEqual(rs["captions"]["words"], 3)
        self.assertEqual(render["result"]["helpers"]["encode"], workflow.HELPERS["encode"][1])
        self.assertEqual(render["result"]["helpers"]["caption_layer"], workflow.HELPERS["caption_layer"][1])
        names = {a["name"] for a in render["result"]["artifacts"]}
        self.assertTrue({"final.mp4", "final-integrity.json", "media-verification.json", "live-check.json", "final-audio.wav"} <= names)
        status, mp4 = self.request("GET", f"/v1/jobs/{render['id']}/stage-artifacts/final.mp4")
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(mp4).hexdigest(), rs["final_sha256"])
        with patch.dict(os.environ, {"TRANSCRIBER_URL": url}):
            fasr = self.stage(pid, "asr", {"audio_job": render["id"], "language": "en"})
        fscan = self.stage(pid, "acoustic-scan", {"assemble_job": render["id"]})
        self.assertEqual(fscan["result"]["summary"]["audio"], "final-audio.wav")
        dg = {"render_job": render["id"], "final_asr_job": fasr["id"], "final_scan_job": fscan["id"], "dialogue_gate_job": result["id"]}
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/delivery-gate", json.dumps({**dg, "final_asr_job": easr["id"]}))[0], 422)
        delivery = self.stage(pid, "delivery-gate", dg)
        ds = delivery["result"]["summary"]
        self.assertTrue(ds["delivery_gate_pass"], ds)
        self.assertEqual(ds["words_lost_vs_edited"], [])
        self.assertEqual(delivery["result"]["helpers"]["audio_gate"], workflow.HELPERS["audio_gate"][1])

        project = {"locked_timeline": {"fps": "24", "frames": 34, "duration": 1.4},
                   "visual_plan": {"beats": [{"start": 0, "end": 1.4, **{k: "x" for k in ("spoken_anchor", "viewer_inference", "visual_family", "state_before", "state_after", "causal_action", "caption_treatment", "speaker_return")}}]},
                   "crop_ledger": {"source_mode": "cfr", "ranges": [{"start": 0, "end": 1.4}]}}
        self.assertTrue(self.stage(pid, "validate-project", project)["result"]["summary"]["pass"])
        self.assertFalse(self.stage(pid, "validate-project", {**project, "crop_ledger": {"ranges": []}})["result"]["summary"]["pass"])
        status, docs = self.request("GET", "/v1/workflow/docs")
        self.assertIn("defleur-audio", docs["docs"])
        status, text = self.request("GET", "/v1/workflow/docs/defleur-audio")
        self.assertEqual(text, (workflow.UPSTREAM_ROOT / "skills/defleur-audio/SKILL.md").read_bytes())
        self.assertIn(b"30768288eb1308b18216a5df5eb4648fbce3e55b", self.request("GET", "/v1/workflow/docs/notice")[1])
        self.assertEqual(self.request("GET", "/v1/workflow/docs/..%2Fplugin.json")[0], 404)
        self.assertEqual(self.request("DELETE", f"/v1/projects/{pid}")[0], 200)
        self.assertEqual(self.request("DELETE", f"/v1/projects/{other}")[0], 200)

    def test_open_mode_without_token(self):
        from client import Client
        server = service.make_server(self.root / "open-data", "", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            c.request("GET", "/v1/capabilities")
            self.assertEqual(c.getresponse().status, 200)
            c.close()
            self.assertIn("operations", Client(f"http://127.0.0.1:{server.server_port}", "").request("GET", "/v1/capabilities"))
        finally:
            server.shutdown(); server.store.close(); thread.join(timeout=5); server.server_close()
        with self.assertRaises(ValueError):
            service.make_server(self.root / "short", "too-short", port=0)

    def test_auth_and_capabilities(self):
        self.assertEqual(self.request("GET", "/healthz", auth=False)[0], 200)
        self.assertEqual(self.request("GET", "/v1/capabilities", auth=False)[0], 401)
        self.assertEqual(self.request("POST", "/v1/projects", b"bad", auth=False)[0], 401)
        status, data = self.request("GET", "/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertFalse(data["delivery_approval"])
        self.assertFalse(data["ai_calls"])
        self.assertEqual(data["upstream_commit"], service.UPSTREAM)

    def test_real_api_preview_and_persistence(self):
        original = self.source.read_bytes()
        status, project = self.request("POST", "/v1/projects", original, "video/mp4")
        self.assertEqual(status, 201, project)
        pid = project["id"]
        self.assertEqual(project["source_sha256"], hashlib.sha256(original).hexdigest())
        plan = {"segments": [{"start_s": 0, "end_s": 0.6, "reason": "synthetic retained start"},
                             {"start_s": 1.1, "end_s": 1.8, "reason": "synthetic retained close"}]}
        status, job = self.request("POST", f"/v1/projects/{pid}/previews", json.dumps(plan))
        self.assertEqual(status, 202, job)
        jid = job["id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            status, job = self.request("GET", f"/v1/jobs/{jid}")
            if job["state"] not in ("queued", "running"):
                break
            time.sleep(.1)
        self.assertEqual(job["state"], "needs_review", job)
        self.assertFalse(job["delivery_approved"])
        self.assertTrue(job["result"]["full_decode_pass"])
        self.assertEqual(job["result"]["ai_calls"], 0)
        self.assertEqual(job["plan"], plan)
        status, movie = self.request("GET", f"/v1/jobs/{jid}/preview")
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(movie).hexdigest(), job["result"]["sha256"])
        self.assertEqual((self.server.store.path(pid) / "source.mp4").read_bytes(), original)
        with closing(sqlite3.connect(self.server.store.db)) as c:
            self.assertEqual(c.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()[0], "needs_review")
        artifact_dir = os.environ.get("VIDEO_TEST_ARTIFACTS")
        if artifact_dir:
            out = Path(artifact_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "synthetic-source.mp4").write_bytes(original)
            (out / "synthetic-preview.mp4").write_bytes(movie)
            (out / "job-receipt.json").write_text(json.dumps(job, indent=2))
        self.assertEqual(self.request("DELETE", f"/v1/projects/{pid}")[0], 200)
        self.assertEqual(self.request("GET", f"/v1/projects/{pid}")[0], 404)
        self.assertEqual(self.request("GET", f"/v1/jobs/{jid}")[0], 404)

    def test_reject_untrusted_input(self):
        for data in (b"not a movie", self.source.read_bytes()[:80], b"#EXTM3U\nhttp://127.0.0.1"):
            status, _ = self.request("POST", "/v1/projects", data, "video/mp4")
            self.assertEqual(status, 422)
        self.assertEqual(self.request("POST", "/v1/projects", self.source.read_bytes(), "video/quicktime")[0], 422)
        self.assertEqual(self.request("GET", "/v1/projects/../secrets")[0], 404)
        self.assertFalse(list(self.server.store.root.glob("*.upload")))

    def test_external_dref_rejected(self):
        content = bytearray(self.source.read_bytes())
        # Match the COMPLETE dref URL entry, not a handler's raw 'url ' token.
        marker = b"\x00\x00\x00\x0curl \x00\x00\x00\x01"
        index = content.index(marker)
        content[index + 11] = 0
        path = self.root / "external.mp4"
        path.write_bytes(content)
        with self.assertRaisesRegex(service.Rejected, "external"):
            service.mp4_structure(path)

    def test_audio_only_and_oversized_dimensions(self):
        audio = self.root / "audio-only.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(self.source),
                        "-vn", "-c:a", "copy", str(audio)], check=True, timeout=10)
        with self.assertRaisesRegex(service.Rejected, "exactly one video"):
            service.probe(audio)
        wide = self.root / "wide.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=1922x2:r=24",
                        "-f", "lavfi", "-i", "sine", "-t", "0.1", "-c:v", "libx264", "-threads", "1",
                        "-c:a", "aac", str(wide)], check=True, timeout=10)
        with self.assertRaises(service.Rejected):
            service.probe(wide)

    def test_truncation_brand_and_native_failure(self):
        content = bytearray(self.source.read_bytes())
        self.assertEqual(content[4:8], b"ftyp")
        content[8:12] = b"qt  "
        path = self.root / "quicktime.mp4"
        path.write_bytes(content)
        with self.assertRaisesRegex(service.Rejected, "ISO MP4"):
            service.mp4_structure(path)
        with self.assertRaisesRegex(service.Rejected, "byte budget"):
            service.mp4_structure(self._empty())
        with self.assertRaisesRegex(service.Rejected, "processing failed"):
            service.native(["/usr/bin/false"], timeout=2)

    def _empty(self):
        path = self.root / "empty.mp4"
        path.write_bytes(b"")
        return path

    def test_http_body_bounds(self):
        for headers in ({"Content-Length": str(service.MAX_UPLOAD + 1)}, {"Transfer-Encoding": "chunked"}):
            c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            c.putrequest("POST", "/v1/projects")
            c.putheader("Authorization", "Bearer " + self.token)
            c.putheader("Content-Type", "video/mp4")
            for name, value in headers.items():
                c.putheader(name, value)
            c.endheaders()
            response = c.getresponse()
            self.assertEqual(response.status, 422)
            response.read()
            c.close()

    def test_plan_validation(self):
        invalid = [None, {}, {"segments": []}, {"segments": [{"start_s": True, "end_s": 1, "reason": "r"}]},
                   {"segments": [{"start_s": float("nan"), "end_s": 1, "reason": "r"}]},
                   {"segments": [{"start_s": 0, "end_s": 3, "reason": "r"}]},
                   {"segments": [{"start_s": 0, "end_s": 1, "reason": ""}]},
                   {"segments": [{"start_s": 0, "end_s": 1, "reason": "r", "filter": "movie=/etc/passwd"}]}]
        for value in invalid:
            with self.assertRaises(service.Rejected):
                service.edit_plan(value, 2)
        with self.assertRaises(service.Rejected):
            service.parse_json(b'{"segments":NaN}')

    def test_job_recovery_and_queue_bound(self):
        store = service.Store(self.root / "recovery")
        store.stop.set()
        store.worker.join(timeout=2)
        project = store.create(io.BytesIO(self.source.read_bytes()), self.source.stat().st_size)
        plan = {"segments": [{"start_s": 0, "end_s": 1, "reason": "synthetic"}]}
        first = store.submit(project["id"], plan)
        store.submit(project["id"], plan)
        with self.assertRaisesRegex(service.Rejected, "queue full"):
            store.submit(project["id"], plan)
        with self.assertRaisesRegex(service.Rejected, "active jobs"):
            store.delete(project["id"])
        with self.assertRaisesRegex(RuntimeError, "already owned"):
            service.Store(store.root)
        store.close()
        recovered = service.Store(store.root)
        recovered.stop.set()
        recovered.worker.join(timeout=2)
        self.assertEqual(recovered.job(first["id"])["state"], "failed")
        self.assertIn("interrupted", recovered.job(first["id"])["error"])
        recovered.delete(project["id"])
        recovered.close()

    def test_native_timeout_and_output_bound(self):
        with self.assertRaisesRegex(service.Rejected, "wall-time"):
            service.native(["/usr/bin/sleep", "5"], timeout=.1)
        with self.assertRaisesRegex(service.Rejected, "output limit"):
            service.native(["/usr/bin/yes"], timeout=5)

    def decision(self):
        return {"transcript": {"language": "en", "provenance": "Synthetic timing test, not actual speech or ASR",
                               "words": [{"start_s": 0.1, "end_s": 0.7, "word": "Synthetic"}]},
                "plan": {"segments": [{"start_s": 0, "end_s": 1.8, "reason": "synthetic test span"}],
                         "captions": [{"start_s": 0.125, "end_s": 0.75, "text": "SAFE: 100% [caption]\nLiteral %{pts}: ' \\"}],
                         "framing": {"mode": "crop", "crop": {"x": 20, "y": 10, "width": 90, "height": 160},
                                     "protected_region": {"x": 40, "y": 30, "width": 40, "height": 110}}}}

    def poll(self, jid):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status, job = self.request("GET", f"/v1/jobs/{jid}")
            self.assertEqual(status, 200)
            if job["state"] not in ("queued", "running"):
                return job
            time.sleep(.05)
        self.fail("render did not finish")

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("client.py")),
                                 "--url", f"http://127.0.0.1:{self.server.server_port}", *args],
                                env={**os.environ, "VIDEO_API_TOKEN": self.token}, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def test_standalone_client_caption_crop_and_review_bundle(self):
        source = self.root / "caption-source.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=blue:s=320x180:r=24,drawbox=x=0:y=0:w=160:h=180:color=red:t=fill",
                        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000", "-t", "2",
                        "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(source)], check=True, timeout=15)
        project = self.cli("upload", str(source))
        pid = project["id"]
        decision_file = self.root / "decision.json"
        decision_file.write_text(json.dumps(self.decision()))
        decision = self.cli("decision", pid, str(decision_file))
        self.assertEqual(self.cli("decisions", pid)["decisions"], [decision])
        job = self.cli("render", pid, "--decision", decision["id"])
        job = self.cli("status", job["id"], "--wait")
        self.assertEqual(job["state"], "needs_review", job)
        self.assertTrue(job["result"]["captions_burned"])
        self.assertEqual(job["decision_id"], decision["id"])
        self.assertEqual(job["plan"], self.decision()["plan"])
        self.assertFalse(job["delivery_approved"])
        self.assertFalse(job["result"]["review"]["audio_lock"])
        bundle = self.root / "review-bundle"
        self.cli("review", job["id"], str(bundle))
        preview = bundle / "preview.mp4"
        self.assertEqual(service.digest(preview), job["result"]["sha256"])
        self.assertTrue((bundle / "index.html").is_file())
        self.assertEqual(len(job["result"]["review"]["edges"]), 2)
        artifacts = job["result"]["review"]["artifacts"]
        self.assertEqual(len(artifacts), 7)
        for name, artifact in artifacts.items():
            self.assertEqual(service.digest(bundle / name), artifact["sha256"])
            data = (bundle / name).read_bytes()
            if name.endswith(".png"):
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(__import__("struct").unpack(">II", data[16:24]), (640, 200))
            else:
                with wave.open(str(bundle / name)) as wav:
                    self.assertEqual(wav.getsampwidth(), 2)
                    self.assertGreater(wav.getnframes(), 1000)
                    self.assertTrue(any(wav.readframes(1000)))
        # Inspect real decoded pixels: caption present only in its interval;
        # crop selects the red source region, not blue right half or letterbox.
        for seconds, captioned in ((.25, True), (1.25, False)):
            pixels = service.native(["/usr/bin/ffmpeg", "-v", "error", *service.input_args(),
                                     "-ss", str(seconds), "-frames:v", "1", "-vf", "crop=270:80:0:390",
                                     "-filter_threads", "1", "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], preview)
            rgb = list(zip(pixels[::3], pixels[1::3], pixels[2::3]))
            white = sum(r > 200 and g > 200 and b > 200 for r, g, b in rgb)
            self.assertGreater(sum(r > 180 and g < 80 and b < 80 for r, g, b in rgb), len(rgb) // 2)
            self.assertGreater(white, 100) if captioned else self.assertEqual(white, 0)
            for i, (r, g, b) in enumerate(rgb):
                if r > 200 and g > 200 and b > 200:
                    self.assertTrue(12 <= i % 270 < 258 and 6 <= i // 270 < 74)
        service.native(["/usr/bin/ffmpeg", "-v", "error", *service.input_args(), "-ss", "0.25", "-frames:v", "1", "-threads", "1", bundle / "caption-frame.png"], preview)
        artifact_dir = os.environ.get("VIDEO_TEST_ARTIFACTS")
        if artifact_dir:
            out = Path(artifact_dir) / "editing-review"
            __import__("shutil").copytree(bundle, out)
            __import__("shutil").copyfile(source, out / "synthetic-source.mp4")
        self.cli("delete", pid)
        self.assertEqual(self.request("GET", f"/v1/projects/{pid}/decisions")[0], 404)
        self.assertFalse(self.server.store.path(pid).exists())

    def test_caption_and_protected_crop_validation(self):
        metadata = {"width": 320, "height": 180, "sample_aspect_ratio": "1:1", "rotation": 0}
        base = self.decision()["plan"]
        self.assertEqual(service.edit_plan(base, 2, metadata), base)
        invalid = []
        for cue in ({"start_s": True, "end_s": 1, "text": "bad"},
                    {"start_s": 0, "end_s": 2, "text": "beyond output"},
                    {"start_s": 0, "end_s": .01, "text": "too short"},
                    {"start_s": 0, "end_s": 1, "text": "a" * 25},
                    {"start_s": 0, "end_s": 1, "text": "unsupported 中文"},
                    {"start_s": 0, "end_s": 1, "text": "bad\x00"},
                    {"start_s": 0, "end_s": 1, "text": "a\nb\nc"}):
            plan = copy.deepcopy(base); plan["captions"] = [cue]; invalid.append(plan)
        plan = copy.deepcopy(base); plan["captions"] *= 2; invalid.append(plan)
        for field, value in (("x", -2), ("width", 88), ("y", 9), ("height", 200), ("x", True)):
            plan = copy.deepcopy(base); plan["framing"]["crop"][field] = value; invalid.append(plan)
        plan = copy.deepcopy(base); plan["framing"]["protected_region"]["x"] = 20; invalid.append(plan)
        plan = copy.deepcopy(base); plan["framing"]["protected_region"]["height"] = 125; invalid.append(plan)
        plan = copy.deepcopy(base); plan["framing"]["filter"] = "movie=/etc/passwd"; invalid.append(plan)
        for plan in invalid:
            with self.assertRaises(service.Rejected):
                service.edit_plan(plan, 2, metadata)
        for changed in ({"rotation": 90}, {"sample_aspect_ratio": "4:3"}, {"rotation": None}, {"sample_aspect_ratio": None}):
            with self.assertRaises(service.Rejected):
                service.edit_plan(base, 2, {**metadata, **changed})

    def test_decision_http_validation_and_immutability(self):
        status, project = self.request("POST", "/v1/projects", self.source.read_bytes(), "video/mp4")
        self.assertEqual(status, 201)
        route = f"/v1/projects/{project['id']}/decisions"
        self.assertEqual(self.request("GET", route, auth=False)[0], 401)
        self.assertEqual(self.request("POST", route, json.dumps(self.decision()), auth=False)[0], 401)
        for mutate in (lambda d: d["transcript"]["words"][0].update(start_s=-1),
                       lambda d: d["transcript"]["words"][0].update(end_s=3),
                       lambda d: d["transcript"].update(provenance=""),
                       lambda d: d["plan"].update(filter="evil")):
            value = self.decision(); mutate(value)
            self.assertEqual(self.request("POST", route, json.dumps(value))[0], 422)
        saved = []
        for i in range(16):
            value = self.decision(); value["transcript"]["provenance"] = f"synthetic revision {i}"
            status, decision = self.request("POST", route, json.dumps(value))
            self.assertEqual(status, 201); saved.append(decision)
        self.assertEqual(self.request("POST", route, json.dumps(self.decision()))[0], 422)
        self.assertEqual(self.request("GET", route)[1]["decisions"], saved)
        self.assertEqual(self.request("POST", f"/v1/projects/{project['id']}/previews", json.dumps({"decision_id": "a" * 32}))[0], 404)
        self.assertEqual(self.request("GET", f"/v1/projects/{project['id']}/source")[1], self.source.read_bytes())
        self.request("DELETE", f"/v1/projects/{project['id']}")

    def test_decisions_survive_restart_and_legacy_schema(self):
        root = self.root / "decision-recovery"
        root.mkdir()
        with closing(sqlite3.connect(root / "state.sqlite3")) as db:
            db.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY, metadata TEXT NOT NULL); CREATE TABLE jobs(id TEXT PRIMARY KEY, project TEXT NOT NULL, state TEXT NOT NULL, plan TEXT NOT NULL, result TEXT, error TEXT, created REAL NOT NULL);")
        store = service.Store(root)
        store.stop.set(); store.worker.join(timeout=2)
        project = store.create(io.BytesIO(self.source.read_bytes()), self.source.stat().st_size)
        decision = store.save_decision(project["id"], self.decision())
        job = store.submit(project["id"], {"decision_id": decision["id"]})
        store.close()
        store = service.Store(root)
        try:
            self.assertEqual(store.decisions(project["id"]), [decision])
            self.assertEqual(store.job(job["id"])["decision_id"], decision["id"])
            self.assertEqual(store.job(job["id"])["state"], "failed")
            store.delete(project["id"])
        finally:
            store.close()

    def test_artifact_auth_allowlist_and_hash_custody(self):
        _, project = self.request("POST", "/v1/projects", self.source.read_bytes(), "video/mp4")
        pid = project["id"]
        plan = {"segments": [{"start_s": .2, "end_s": 1, "reason": "synthetic"}]}
        _, job = self.request("POST", f"/v1/projects/{pid}/previews", json.dumps(plan))
        job = self.poll(job["id"])
        self.assertEqual(job["state"], "needs_review", job)
        name = next(iter(job["result"]["review"]["artifacts"]))
        route = f"/v1/jobs/{job['id']}/artifacts/"
        self.assertEqual(self.request("GET", route + name, auth=False)[0], 401)
        self.assertEqual(self.request("GET", route + "source.mp4")[0], 404)
        self.assertEqual(self.request("GET", route + "../source.mp4")[0], 404)
        self.assertEqual(self.request("GET", route + name)[0], 200)
        (self.server.store.path(pid) / name).write_bytes(b"changed")
        self.assertEqual(self.request("GET", route + name)[0], 409)
        self.request("DELETE", f"/v1/projects/{pid}")

    def test_review_failure_cleans_partial_files(self):
        _, project = self.request("POST", "/v1/projects", self.source.read_bytes(), "video/mp4")
        pid = project["id"]
        with patch.object(service, "review_artifacts", side_effect=service.Rejected("synthetic evidence failure")):
            _, job = self.request("POST", f"/v1/projects/{pid}/previews", json.dumps(self.decision()["plan"]))
            job = self.poll(job["id"])
        self.assertEqual(job["state"], "failed")
        self.assertIn("synthetic evidence failure", job["error"])
        self.assertFalse(list(self.server.store.path(pid).glob(job["id"] + "*")))
        self.assertEqual(self.request("GET", f"/v1/jobs/{job['id']}/preview")[0], 409)
        self.request("DELETE", f"/v1/projects/{pid}")


    def test_one_time_upload_url_project_list_and_upload_page(self):
        status, data = self.request("POST", "/v1/uploads", b"", auth=False)
        self.assertEqual(status, 401)
        status, ticket = self.request("POST", "/v1/uploads", b"")
        self.assertEqual(status, 201)
        self.assertTrue(ticket["path"].startswith("/v1/uploads/") and ticket["one_time"])
        body = self.source.read_bytes()
        status, project = self.request("POST", ticket["path"], body, "video/mp4", auth=False)
        self.assertEqual(status, 201, project)
        self.assertNotIn("normalization", project)  # H.264 CFR source keeps its original bytes
        status, again = self.request("POST", ticket["path"], body, "video/mp4", auth=False)
        self.assertEqual(status, 403)
        status, bogus = self.request("POST", "/v1/uploads/" + "x" * 43, body, "video/mp4", auth=False)
        self.assertEqual(status, 403)
        status, listing = self.request("GET", "/v1/projects")
        self.assertIn(project["id"], [p["id"] for p in listing["projects"]])
        status, page = self.request("GET", "/upload", auth=False)
        self.assertEqual(status, 200)
        self.assertIn(b'type="file"', page)
        self.assertNotIn(b"http", page.split(b"<script>")[1])  # no external assets
        self.request("DELETE", f"/v1/projects/{project['id']}")

    def test_hevc_and_vfr_sources_are_normalized_with_provenance(self):
        hevc, vfr = self.root / "hevc.mp4", self.root / "vfr.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-y", "-i", str(self.source), "-c:v", "libx265", "-x265-params", "log-level=error:pools=1:frame-threads=1",
                        "-tag:v", "hvc1", "-c:a", "copy", str(hevc)], check=True, timeout=120)
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-y", "-i", str(self.source), "-vf", "setpts='if(lt(N,24),N/24/TB,(N*1.6)/24/TB)'",
                        "-fps_mode", "vfr", "-c:v", "libx264", "-threads", "1", "-c:a", "copy", str(vfr)], check=True, timeout=60)
        for path, reason in ((hevc, "HEVC video"), (vfr, "variable frame rate")):
            status, project = self.request("POST", "/v1/projects", path.read_bytes(), "video/mp4")
            self.assertEqual(status, 201, project)
            self.assertEqual(project["video_codec"], "h264")
            self.assertIn(reason, project["normalization"]["reasons"])
            self.assertEqual(project["normalization"]["frame_rate_mode"], "constant")
            self.assertEqual(project["original"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotEqual(project["source_sha256"], project["original"]["sha256"])
            self.assertEqual(service.frame_rate_mode(self.server.store.path(project["id"]) / "source.mp4",
                                                     {"r_frame_rate": project["normalization"]["fps"]})[0], "constant")
            self.request("DELETE", f"/v1/projects/{project['id']}")

    def test_motion_submission_paths_plan_and_asset_upload(self):
        import motion
        import workflow
        status, project = self.request("POST", "/v1/projects", self.source.read_bytes(), "video/mp4")
        self.assertEqual(status, 201, project)
        pid = project["id"]
        beat = {"start": 0.5, "end": 1.5, "spoken_anchor": "a", "viewer_inference": "b", "visual_family": "diagram",
                "state_before": "c", "state_after": "d", "causal_action": "e", "caption_treatment": "suppress", "speaker_return": "f"}
        index = ('<img id="live"><script src="defleur/ledger.js"></script><script src="defleur/gsap.min.js"></script>'
                 '<script>window.renderFrame = (t) => {};</script>')
        post = lambda body: self.request("POST", f"/v1/projects/{pid}/motion", json.dumps(body).encode(), "application/json")
        good = {"files": {"index.html": index, "main.css": "body{margin:0}"}, "plan": {"beats": [beat]}}
        for bad_path in ("../x.html", "/etc/passwd", "defleur/ledger.js", "a/b/c/d/e.js", "x.exe", "Index.html", "locked-timeline.json"):
            status, err = post({**good, "files": {**good["files"], bad_path: "x"}})
            self.assertEqual(status, 422, (bad_path, err))
        status, err = post({**good, "files": {"index.html": index.replace("renderFrame", "render")}})
        self.assertEqual(status, 422)
        self.assertIn("renderFrame", err["error"])
        status, err = post({**good, "files": {"index.html": index + '<script src="https://cdn.example/gsap.js"></script>'}})
        self.assertEqual(status, 422)
        status, err = post({**good, "plan": {"beats": [{**beat, "causal_action": ""}]}})
        self.assertEqual(status, 422)
        status, err = post({**good, "plan": {"beats": [{**beat, "caption_treatment": "show"}], "caption_suppress": [{"start": 0.6, "end": 1.0, "reason": "r"}]}})
        self.assertEqual(status, 422)  # James' encode.py rule: suppression only inside a 'suppress' beat
        status, err = post({**good, "files": {**good["files"], "assets/x.png": {"base64": "aGVsbG8="}}})
        self.assertEqual(status, 422)  # not a real PNG
        status, err = post({**good, "plan": {"beats": [beat], "inserts": [{"start": 2, "end": 3, "asset": "assets/missing.mp4", "reason": "r"}]}})
        self.assertEqual(status, 422)
        status, st = post({**good, "plan": {"beats": [beat], "caption_suppress": [{"start": 0.6, "end": 1.0, "reason": "chart says it"}]}})
        self.assertEqual(status, 201, st)
        self.assertTrue(st["submitted"])
        first = st["composition_sha256"]
        # Asset upload: one-time URL bound to one project path; bytes checked by magic.
        status, ticket = self.request("POST", f"/v1/projects/{pid}/asset-uploads", json.dumps({"path": "assets/clip.mp4"}).encode(), "application/json")
        self.assertEqual(status, 201, ticket)
        status, err = self.request("POST", ticket["path"], b"\x00" * 64, "application/octet-stream", auth=False)
        self.assertEqual(status, 422)  # not an MP4; ticket consumed
        status, ticket = self.request("POST", f"/v1/projects/{pid}/asset-uploads", json.dumps({"path": "assets/clip.mp4"}).encode(), "application/json")
        status, up = self.request("POST", ticket["path"], self.source.read_bytes(), "application/octet-stream", auth=False)
        self.assertEqual(status, 201, up)
        status, again = self.request("POST", ticket["path"], self.source.read_bytes(), "application/octet-stream", auth=False)
        self.assertEqual(status, 403)
        status, err = self.request("POST", f"/v1/projects/{pid}/asset-uploads", json.dumps({"path": "main.js"}).encode(), "application/json")
        self.assertEqual(status, 422)
        plan = {"beats": [beat], "inserts": [{"start": 2.0, "end": 3.0, "asset": "assets/clip.mp4", "fit": "cover", "reason": "B-roll"}]}
        status, st = post({**good, "plan": plan})
        self.assertEqual(status, 201, st)
        self.assertIn("assets/clip.mp4", [f["path"] for f in st["files"]])  # uploaded media survives a resubmission
        self.assertNotEqual(st["composition_sha256"], first)
        # Base-frame map: inserts replace source frames with insert ids inside their window only.
        edit = {"fps": "24/1", "frames": 96, "duration": 4.0, "source_frame_indices": list(range(96))}
        ids, windows = motion.base_map(edit, plan)
        self.assertEqual(ids[47], 47)
        self.assertTrue(all(ids[f] >= motion.INSERT_BASE for f in range(48, 72)))
        self.assertEqual(ids[72], 72)
        self.assertEqual(windows[0]["frames"], 24)
        js = motion.ledger_js(edit, plan, ids, (1080, 1920))
        self.assertIn("window.sourceFrameForOutputFrame", js)
        self.assertEqual(workflow._proof_indices(96, 24.0, 4.0, plan)[:3], [0, 6, 12])
        status, st = self.request("DELETE", f"/v1/projects/{pid}/motion")
        self.assertFalse(st["submitted"])
        self.request("DELETE", f"/v1/projects/{pid}")

    def test_capabilities_report_browser_and_resources(self):
        os.environ["BROWSER_URL"] = "http://127.0.0.1:9"
        try:
            status, caps = self.request("GET", "/v1/capabilities")
        finally:
            del os.environ["BROWSER_URL"]
        self.assertEqual(status, 200)
        self.assertEqual(caps["version"], "0.6.0-testing")
        b = caps["workflow"]["motion"]["browser"]
        self.assertFalse(b["reachable"])
        self.assertIn("Browser app", b["fix"])
        self.assertTrue(caps["workflow"]["motion"]["gsap_present"])
        res = caps["workflow"]["resources"]
        self.assertGreater(res["host_ram_bytes"], 0)
        self.assertGreater(res["data_disk_free_bytes"], 0)
        self.assertIn("per_job_estimates", res)
        self.assertGreaterEqual(caps["limits"]["duration_s"], 900)
        self.assertGreaterEqual(caps["limits"]["output_duration_s"], 300)

if __name__ == "__main__":
    unittest.main(verbosity=2)
