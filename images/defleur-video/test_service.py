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
            rel, _ = workflow.HELPERS['pcm-assemble']
            file = root / rel
            file.parent.mkdir(parents=True)
            file.write_text('raise RuntimeError("must never execute")')
            with patch.dict(os.environ, {'VIDEO_HELPER_ROOT': str(root)}):
                with self.assertRaisesRegex(service.Rejected, 'hash mismatch'):
                    workflow.helper('pcm-assemble')
                self.assertFalse(workflow.capabilities()['helpers']['pcm-assemble']['available'])
                file.unlink()
                file.symlink_to(self.source)
                with self.assertRaisesRegex(service.Rejected, 'missing'):
                    workflow.helper('pcm-assemble')

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
                service.native, service.input_args, service.digest)
            receipt = json.loads((root / 'probe/source-probe.json').read_text())
            self.assertFalse(receipt['constant_frame_rate'])
            self.assertEqual(receipt['mapping_support'], 'requires-pts-picture-ledger')
            with self.assertRaisesRegex(service.Rejected, 'requires verified CFR'):
                workflow.run('pcm-assemble', {'segments': [{'start_s': 0, 'end_s': 1, 'reason': 'VFR rejection regression'}]},
                    source, root / 'assemble', metadata, service.native, service.input_args, service.digest)

    def test_workflow_source_and_private_helpers(self):
        from client import Client
        client = Client(f"http://127.0.0.1:{self.server.server_port}", self.token)
        project = client.upload(self.source)
        pid = project["id"]
        job = client.request("POST", f"/v1/projects/{pid}/stages/source-audio", "{}")
        job = client.wait(job["id"], True)
        self.assertEqual(job["state"], "needs_review", job.get("error"))
        self.assertFalse(job["delivery_approved"])
        bundle = self.root / "source-stage-bundle"
        client.stage_bundle(job["id"], bundle)
        probe = json.loads((bundle / "source-probe.json").read_text())
        self.assertTrue(probe["constant_frame_rate"])
        self.assertEqual(probe["frames"], 48)
        self.assertEqual(probe["fps"], "24")
        self.assertEqual(self.request("GET", f"/v1/jobs/{job['id']}/stage-artifacts/request.json", auth=False)[0], 401)
        self.assertEqual(self.request("GET", f"/v1/jobs/{job['id']}/stage-artifacts/secrets.json")[0], 404)
        self.assertEqual(self.request("GET", f"/v1/jobs/{job['id']}/preview")[0], 409)
        for stage, value in [("shell", {}), ("source-audio", {"command": "id"})]:
            self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/{stage}", json.dumps(value))[0], 422)
        with patch.dict(os.environ, {"VIDEO_HELPER_ROOT": ""}):
            self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/pcm-assemble", json.dumps({"segments": [{"start_s": 0, "end_s": 1, "reason": "synthetic"}]}))[0], 422)
        self.assertEqual(self.request("DELETE", f"/v1/projects/{pid}")[0], 200)

    @unittest.skipUnless(os.environ.get("VIDEO_HELPER_ROOT"), "private upstream snapshot not mounted; no false helper parity claim")
    def test_actual_pinned_pcm_and_preset_helpers(self):
        from client import Client
        client = Client(f"http://127.0.0.1:{self.server.server_port}", self.token)
        pid = client.upload(self.source)["id"]
        value = {"segments": [{"start_s": .25, "end_s": 1.25, "reason": "synthetic sample-lock regression"}]}
        job = client.request("POST", f"/v1/projects/{pid}/stages/pcm-assemble", json.dumps(value))
        job = client.wait(job["id"], True)
        self.assertEqual(job["state"], "needs_review", job.get("error"))
        self.assertEqual(job["result"]["helper_sha256"], service.workflow.HELPERS['pcm-assemble'][1])
        bundle = self.root / "pcm-stage-bundle"
        client.stage_bundle(job["id"], bundle)
        ledger = json.loads((bundle / "edit-map.json").read_text())
        self.assertEqual(ledger["samples"], 48000)
        self.assertEqual(ledger["source_frame_indices"], list(range(6, 30)))
        with wave.open(str(bundle / "source.wav")) as source:
            source.setpos(12000)
            expected = source.readframes(48000)
        with wave.open(str(bundle / "edited.wav")) as edited:
            self.assertEqual(edited.readframes(48000), expected)
        value = {"owner": {"caption": {"max_words": 4}}, "project": {"caption": {"max_words": 3}}}
        job = client.request("POST", f"/v1/projects/{pid}/stages/resolve-preset", json.dumps(value))
        job = client.wait(job["id"], True)
        self.assertEqual(job["state"], "needs_review", job.get("error"))
        bundle = self.root / "preset-stage-bundle"
        client.stage_bundle(job["id"], bundle)
        resolved = json.loads((bundle / "preset-resolution.json").read_text())
        self.assertEqual(resolved["preset"]["caption"]["max_words"], 3)
        self.assertEqual(len(resolved["sources"]), 3)
        self.assertTrue(resolved["font_sha256"])
        value = {"owner": {"caption": {"font_path": "/etc/passwd"}}}
        self.assertEqual(self.request("POST", f"/v1/projects/{pid}/stages/resolve-preset", json.dumps(value))[0], 422)
        self.assertEqual(self.request("DELETE", f"/v1/projects/{pid}")[0], 200)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
