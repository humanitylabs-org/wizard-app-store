#!/usr/bin/env python3
"""Private, single-owner DeFleur preview service. No Hermes runtime dependency."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import workflow
import fcntl
import hmac
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import sqlite3
import struct
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast
from editing import Rejected, validate_options, validate_transcript, visual_filters, review_artifacts

VERSION = "0.2.1-testing"
UPSTREAM = "30768288eb1308b18216a5df5eb4648fbce3e55b"
MAX_UPLOAD = 512 * 1024 * 1024
MAX_PROJECTS = 8
MAX_JOBS = 32
MAX_DURATION = 300
MAX_NATIVE_LOG = 256 * 1024
ID = re.compile(r"^[a-f0-9]{32}$")
GATES = ["coherent-thought/editorial-review", "transcript-and-word-alignment",
         "filler-and-phonetic-review", "waveform-and-spectrogram-per-edge",
         "audio-dialogue-lock", "fixed-per-setup-face-audit",
         "semantic-HTML-SVG-GSAP-motion", "burned-aligned-captions",
         "phone-size-and-motion-review", "delivery-audio-receipt"]


NATIVE_CONTEXT = threading.local()


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def json_bytes(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":")).encode()


def parse_json(data):
    try:
        return json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(Rejected("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Rejected("invalid JSON") from exc


def mp4_structure(path):
    """Bounded structural allowlist. Payloads are skipped, never recursively guessed.

    This preview accepts ordinary self-contained MP4 only, not MOV aliases,
    fragmented movies, reference movies, or compressed movie metadata.
    Native demuxing additionally has fd-only protocol access.
    """
    count = 0
    seen = {b"ftyp": 0, b"moov": 0, b"mdat": 0, b"dref": 0, b"trak": 0}
    containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts"}
    forbidden = {b"cmov", b"rmra", b"rmda", b"moof", b"mvex"}
    size = path.stat().st_size
    if not 16 <= size <= MAX_UPLOAD:
        raise Rejected("MP4 byte budget")
    with path.open("rb") as f:
        def walk(start, end, depth=0):
            nonlocal count
            if depth > 8:
                raise Rejected("MP4 nesting limit")
            pos = start
            while pos < end:
                count += 1
                if count > 4096 or end - pos < 8:
                    raise Rejected("MP4 box budget or truncation")
                f.seek(pos)
                length, kind = struct.unpack(">I4s", f.read(8))
                header = 8
                if length == 1:
                    if end - pos < 16:
                        raise Rejected("truncated extended box")
                    length = struct.unpack(">Q", f.read(8))[0]
                    header = 16
                if length == 0:
                    length = end - pos
                if length < header or pos + length > end:
                    raise Rejected("invalid MP4 box")
                if kind in forbidden:
                    raise Rejected("reference/compressed/fragmented MP4 unsupported")
                if kind in seen:
                    seen[kind] += 1
                if kind == b"ftyp":
                    if depth or length > 256 or length < header + 8:
                        raise Rejected("invalid ftyp")
                    brand = f.read(4)
                    if brand not in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1"}:
                        raise Rejected("only ISO MP4 brands supported")
                if kind == b"dref":
                    if length < header + 8:
                        raise Rejected("invalid dref")
                    version_flags, entries = struct.unpack(">II", f.read(8))
                    if version_flags != 0 or entries != 1 or length != header + 20:
                        raise Rejected("only one self-contained dref supported")
                    entry_size, entry_type, flags = struct.unpack(">I4sI", f.read(12))
                    if (entry_size, entry_type, flags) != (12, b"url ", 1):
                        raise Rejected("external data references forbidden")
                if kind in containers:
                    walk(pos + header, pos + length, depth + 1)
                pos += length
        walk(0, size)
    if seen[b"ftyp"] != 1 or seen[b"moov"] != 1 or not seen[b"mdat"] or not 1 <= seen[b"trak"] <= 4 or seen[b"dref"] != seen[b"trak"]:
        raise Rejected("incomplete or unsupported MP4 structure")


def native(args, source=None, timeout=30, cwd=None, file_limit=33554432):
    """Bounded native process; one private descriptor, no shell or network inputs.

    prlimit is deliberately a separate executable, avoiding preexec_fn in this
    threaded process. RLIMIT_AS is a native child ceiling, not an OS sandbox.
    """
    timeout = min(timeout, getattr(NATIVE_CONTEXT, "deadline", float("inf")) - time.monotonic())
    if timeout <= 0:
        raise Rejected("job wall-time limit")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    with (source.open("rb") if source else open(os.devnull, "rb")) as f:
        command = ["/usr/bin/prlimit", "--as=1073741824", "--cpu=90", f"--fsize={file_limit}", "--nofile=64", "--", *args]
        command = [str(f.fileno()) if x == "@FD@" else str(x) for x in command]
        p = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, pass_fds=(f.fileno(),) if source else (),
                             env=env, cwd=cwd, start_new_session=True)
        output = {"out": bytearray(), "err": bytearray()}
        assert p.stdout is not None and p.stderr is not None
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as sel:
                sel.register(p.stdout, selectors.EVENT_READ, "out")
                sel.register(p.stderr, selectors.EVENT_READ, "err")
                while sel.get_map():
                    if time.monotonic() > deadline:
                        raise Rejected("native process wall-time limit")
                    for key, _ in sel.select(0.1):
                        chunk = os.read(key.fd, 16384)
                        if not chunk:
                            sel.unregister(key.fileobj)
                            continue
                        output[key.data].extend(chunk)
                        if sum(map(len, output.values())) > MAX_NATIVE_LOG:
                            raise Rejected("native process output limit")
                if p.wait(timeout=max(0.1, deadline - time.monotonic())):
                    raise Rejected("native media processing failed")
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            p.stdout.close()
            p.stderr.close()
        return bytes(output["out"])


def input_args():
    return ["-max_alloc", "67108864", "-threads", "1", "-protocol_whitelist", "fd",
            "-format_whitelist", "mov", "-f", "mov", "-enable_drefs", "0",
            "-use_absolute_path", "0", "-probesize", "1048576", "-analyzeduration", "3000000",
            "-max_streams", "4", "-max_pixels", "2073600", "-fd", "@FD@", "-i", "fd:"]


def probe(source):
    mp4_structure(source)
    value = parse_json(native(["/usr/bin/ffprobe", "-v", "error", *input_args(),
                               "-show_streams", "-show_format", "-of", "json"], source))
    streams = value.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1 or len(streams) != 2:
        raise Rejected("preview requires exactly one video and one audio stream")
    v, a = videos[0], audios[0]
    try:
        duration = float(value["format"]["duration"])
        width, height = int(v["width"]), int(v["height"])
    except (KeyError, ValueError, TypeError) as exc:
        raise Rejected("invalid source metadata") from exc
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise Rejected(f"source duration must be at most {MAX_DURATION} seconds")
    if not 1 <= width <= 1920 or not 1 <= height <= 1920 or width * height > 2073600:
        raise Rejected("source dimensions exceed preview budget")
    if v.get("codec_name") != "h264" or a.get("codec_name") != "aac" or a.get("channels", 999) > 2:
        raise Rejected("preview supports H.264/AAC mono/stereo only")
    # Decode a real first frame, rather than trusting metadata/zero-exit alone.
    check = native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", *input_args(),
                    "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=16:16",
                    "-filter_threads", "1", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], source)
    if len(check) != 16 * 16 * 3:
        raise Rejected("source has no decodable video frame")
    return {"duration": duration, "width": width, "height": height, "video_codec": "h264", "audio_codec": "aac",
            "source_sha256": digest(source), "first_frame_decoded": True,
            "sample_aspect_ratio": v.get("sample_aspect_ratio", "1:1"),
            "rotation": next((s["rotation"] for s in v.get("side_data_list", []) if "rotation" in s), 0)}


def edit_plan(value, duration, metadata=None):
    if not isinstance(value, dict) or "segments" not in value or set(value) - {"segments", "captions", "framing"}:
        raise Rejected("expected edit-plan object with segments")
    rows = value["segments"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise Rejected("one to eight ordered retained spans required")
    end = 0.0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"start_s", "end_s", "reason"}:
            raise Rejected("segment needs start_s, end_s, reason")
        start, stop = row["start_s"], row["end_s"]
        if type(start) not in (int, float) or type(stop) not in (int, float) or not math.isfinite(start) or not math.isfinite(stop):
            raise Rejected("finite numeric span required")
        if not end <= start < stop <= duration or stop - start < 0.1:
            raise Rejected("invalid, overlapping, or out-of-source span")
        if not isinstance(row["reason"], str) or not row["reason"].strip() or len(row["reason"]) > 1000:
            raise Rejected("truthful editorial reason required")
        end = stop
    validate_options(value, metadata)
    return value


def render(source, target, plan):
    filters, joins = [], []
    for i, row in enumerate(plan["segments"]):
        start, end = row["start_s"], row["end_s"]
        filters += [f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]",
                    f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"]
        joins.append(f"[v{i}][a{i}]")
    filters.append("".join(joins) + f"concat=n={len(joins)}:v=1:a=1[v][a]")
    filters.append("[v]" + visual_filters(plan, target.parent, target.stem) + "[out]")
    native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-n", *input_args(),
            "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
            "-map", "[out]", "-map", "[a]", "-map_metadata", "-1", "-map_chapters", "-1",
            "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-t", "60", "-movflags", "+faststart", target], source, timeout=120, cwd=target.parent)
    result = probe(target)
    if (result["width"], result["height"]) != (270, 480):
        raise Rejected("preview dimensions mismatch")
    # Full decode of the exact artifact. No perceptual-quality claim.
    native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", *input_args(),
            "-map", "0:v:0", "-map", "0:a:0", "-threads", "1", "-f", "null", "-"], target, timeout=60)
    expected = sum(r["end_s"] - r["start_s"] for r in plan["segments"])
    if abs(result["duration"] - expected) > 0.15:
        raise Rejected("preview duration mismatch")
    return {"sha256": digest(target), "bytes": target.stat().st_size, "width": 270, "height": 480,
            "duration": result["duration"], "full_decode_pass": True,
            "captions_burned": bool(plan.get("captions")), "framing": plan.get("framing", {"mode": "contain"}),
            "scope": "Externally authored review edit; caption timing and protected region are unverified assertions. Not audio-locked, animated, or delivery-approved."}


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / "state.sqlite3"
        self.lock = (self.root / "service.lock").open("a")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("data directory already owned by another worker")
        self.stop = threading.Event()
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT NOT NULL, state TEXT NOT NULL,
              plan TEXT NOT NULL, result TEXT, error TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, project TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS job_decisions(job TEXT PRIMARY KEY, decision TEXT NOT NULL);
            UPDATE jobs SET state='failed', error='worker interrupted; explicitly submit a new preview' WHERE state IN ('queued','running');
            """)
        # Files not referenced by a committed project are interrupted uploads.
        for path in self.root.glob("*.upload"):
            path.unlink()
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()

    def close(self):
        self.stop.set()
        self.worker.join(timeout=220)
        if self.worker.is_alive():
            raise RuntimeError("worker did not stop")
        self.lock.close()

    @contextmanager
    def connect(self):
        """Commit/rollback each unit of work, then always release its connection.

        sqlite3.Connection.__exit__ handles transactions but does not close.
        In particular the idle worker opens ten connections per second.
        """
        c = sqlite3.connect(self.db, timeout=5)
        try:
            c.row_factory = sqlite3.Row
            with c:
                yield c
        finally:
            c.close()

    def path(self, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise Rejected("invalid identifier")
        return self.root / identifier

    def project(self, identifier):
        self.path(identifier)
        with self.connect() as c:
            row = c.execute("SELECT metadata FROM projects WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise FileNotFoundError("project not found")
        return parse_json(row[0])

    def create(self, stream, length):
        if not 0 < length <= MAX_UPLOAD:
            raise Rejected(f"upload must be 1..{MAX_UPLOAD} bytes")
        with self.connect() as c:
            if c.execute("SELECT count(*) FROM projects").fetchone()[0] >= MAX_PROJECTS:
                raise Rejected("project quota reached; delete an unused project")
        if __import__("shutil").disk_usage(self.root).free < length + 256 * 1024 * 1024:
            raise Rejected("insufficient free disk for upload and reserve")
        identifier = uuid.uuid4().hex
        tmp = self.root / (identifier + ".upload")
        try:
            with tmp.open("xb") as f:
                remaining = length
                deadline = time.monotonic() + 60
                while remaining:
                    if time.monotonic() > deadline:
                        raise Rejected("upload wall-time limit")
                    data = stream.read1(min(65536, remaining))
                    if not data:
                        raise Rejected("truncated upload")
                    f.write(data)
                    remaining -= len(data)
            metadata = probe(tmp)
            metadata.update({"id": identifier, "upstream_commit": UPSTREAM, "created": time.time(), "missing_delivery_gates": GATES})
            dest = self.path(identifier)
            dest.mkdir(mode=0o700)
            tmp.rename(dest / "source.mp4")
            with self.connect() as c:
                c.execute("INSERT INTO projects VALUES(?,?)", (identifier, json_bytes(metadata).decode()))
            return metadata
        finally:
            tmp.unlink(missing_ok=True)

    def decisions(self, identifier):
        self.project(identifier)
        with self.connect() as c:
            rows = c.execute("SELECT id,content,created FROM decisions WHERE project=? ORDER BY created,id", (identifier,)).fetchall()
        return [{"id": row["id"], "created": row["created"], **parse_json(row["content"])} for row in rows]

    def save_decision(self, identifier, value):
        metadata = self.project(identifier)
        if not isinstance(value, dict) or set(value) != {"transcript", "plan"}:
            raise Rejected("decision requires transcript and plan")
        validate_transcript(value["transcript"], metadata["duration"])
        edit_plan(value["plan"], metadata["duration"], metadata)
        content = {**value, "source_sha256": metadata["source_sha256"],
                   "decision_sha256": hashlib.sha256(json_bytes(value)).hexdigest()}
        did, created = uuid.uuid4().hex, time.time()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT count(*) FROM decisions WHERE project=?", (identifier,)).fetchone()[0] >= 16:
                raise Rejected("decision quota reached (16 per project)")
            c.execute("INSERT INTO decisions VALUES(?,?,?,?)", (did, identifier, json_bytes(content).decode(), created))
        return {"id": did, "created": created, **content}

    def submit(self, identifier, plan):
        metadata = self.project(identifier)
        decision_id = None
        if isinstance(plan, dict) and set(plan) == {"decision_id"}:
            decision_id = plan["decision_id"]
            self.path(decision_id)
            decision = next((d for d in self.decisions(identifier) if d["id"] == decision_id), None)
            if decision is None:
                raise FileNotFoundError("decision not found in project")
            plan = decision["plan"]
        plan = edit_plan(plan, metadata["duration"], metadata)
        if sum(r["end_s"] - r["start_s"] for r in plan["segments"]) > 60:
            raise Rejected("Legacy preview output remains limited to 60 seconds; workflow source stages accept longer material")
        if __import__("shutil").disk_usage(self.root).free < 256 * 1024 * 1024:
            raise Rejected("insufficient free disk")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT count(*) FROM jobs").fetchone()[0] >= MAX_JOBS:
                raise Rejected("job quota reached; delete an unused project")
            if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= 2:
                raise Rejected("queue full")
            jid = uuid.uuid4().hex
            c.execute("INSERT INTO jobs VALUES(?,?,'queued',?,NULL,NULL,?)", (jid, identifier, json_bytes(plan).decode(), time.time()))
            if decision_id:
                c.execute("INSERT INTO job_decisions VALUES(?,?)", (jid, decision_id))
        return self.job(jid)

    def submit_stage(self, identifier, stage, value):
        metadata = self.project(identifier)
        workflow.validate(stage, value, metadata, edit_plan)
        if __import__("shutil").disk_usage(self.root).free < 512 * 1024 * 1024:
            raise Rejected("workflow stages require 512 MiB free scratch reserve")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT count(*) FROM jobs").fetchone()[0] >= MAX_JOBS:
                raise Rejected("job quota reached")
            if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] >= 2:
                raise Rejected("queue full")
            jid = uuid.uuid4().hex
            plan = {"workflow_stage": stage, "input": value}
            c.execute("INSERT INTO jobs VALUES(?,?,'queued',?,NULL,NULL,?)", (jid, identifier, json_bytes(plan).decode(), time.time()))
        return self.job(jid)

    def job(self, jid):
        self.path(jid)
        with self.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            decision = c.execute("SELECT decision FROM job_decisions WHERE job=?", (jid,)).fetchone()
        if row is None:
            raise FileNotFoundError("job not found")
        value = dict(row)
        value["decision_id"] = decision[0] if decision else None
        value["plan"] = parse_json(value["plan"])
        value["result"] = parse_json(value["result"]) if value["result"] else None
        value["delivery_approved"] = False
        value["missing_delivery_gates"] = GATES
        return value

    def delete(self, identifier):
        self.project(identifier)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM jobs WHERE project=? AND state IN ('queued','running')", (identifier,)).fetchone():
                raise Rejected("cannot delete a project with active jobs")
            __import__("shutil").rmtree(self.path(identifier))
            c.execute("DELETE FROM job_decisions WHERE job IN (SELECT id FROM jobs WHERE project=?)", (identifier,))
            c.execute("DELETE FROM decisions WHERE project=?", (identifier,))
            c.execute("DELETE FROM jobs WHERE project=?", (identifier,))
            c.execute("DELETE FROM projects WHERE id=?", (identifier,))

    def work(self):
        while not self.stop.wait(0.1):
            with self.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    c.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
            if not row:
                continue
            target = self.path(row["project"]) / (row["id"] + ".mp4")
            started = time.monotonic()
            try:
                NATIVE_CONTEXT.deadline = time.monotonic() + 180
                plan = parse_json(row["plan"])
                source = self.path(row["project"]) / "source.mp4"
                metadata = self.project(row["project"])
                if "workflow_stage" in plan:
                    result = workflow.run(plan["workflow_stage"], plan["input"], source,
                        target.with_suffix(".stage"), metadata, native, input_args, digest)
                else:
                    result = render(source, target, plan)
                    result["review"] = review_artifacts(source, target, plan, metadata, native, input_args, digest)
                result["source_sha256"] = metadata["source_sha256"]
                result["plan_sha256"] = hashlib.sha256(json_bytes(plan)).hexdigest()
                result.update({"elapsed_s": round(time.monotonic() - started, 3), "service_version": VERSION,
                               "upstream_commit": UPSTREAM, "ai_calls": 0})
                with self.connect() as c:
                    c.execute("UPDATE jobs SET state='needs_review',result=? WHERE id=?", (json_bytes(result).decode(), row["id"]))
            except Exception as exc:
                for partial in target.parent.glob(row["id"] + "*"):
                    if partial.is_dir():
                        __import__("shutil").rmtree(partial)
                    else:
                        partial.unlink(missing_ok=True)
                with self.connect() as c:
                    c.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (str(exc)[:300], row["id"]))
            finally:
                for caption in target.parent.glob(row["id"] + "-caption-*.txt"):
                    caption.unlink(missing_ok=True)
                del NATIVE_CONTEXT.deadline


class VideoServer(HTTPServer):
    token: str
    store: Store


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        pass  # Never log tokens, plans, or media-derived content.

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def send(self, status, data, kind="application/json"):
        if not isinstance(data, bytes):
            data = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorize(self):
        token = cast(VideoServer, self.server).token
        if not token:
            return True  # Open mode: network access (e.g. Tailscale-only host) is the boundary.
        values = self.headers.get_all("Authorization", [])
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ("Bearer " + cast(VideoServer, self.server).token).encode()):
            self.send(401, {"error": "bearer authentication required"})
            return False
        return True

    def send_file(self, path, kind, sha256):
        if digest(path) != sha256:
            return self.send(409, {"error": "artifact hash changed; do not review or deliver"})
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Content-Disposition", 'attachment; filename="' + path.name + '"')
        self.end_headers()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def length(self, maximum):
        values = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(values) != 1 or not values[0].isdigit():
            raise Rejected("one explicit Content-Length required; no chunked uploads")
        n = int(values[0])
        if not 0 < n <= maximum:
            raise Rejected("request body exceeds limit or is empty")
        return n

    def route(self, method):
        if self.path == "/healthz" and method == "GET":
            return self.send(200, {"status": "ok", "version": VERSION})
        if not self.authorize():
            return
        parts = self.path.split("/")
        store = cast(VideoServer, self.server).store
        if method == "GET" and self.path == "/v1/capabilities":
            return self.send(200, {"version": VERSION, "upstream_commit": UPSTREAM,
                "operations": ["upload_mp4", "submit_edit_plan_preview", "persist_transcript_decisions", "burn_timed_captions", "fixed_protected_crop", "cut_edge_review_artifacts", "poll_job", "download_preview", "delete_project"],
                "limits": {"upload_bytes": MAX_UPLOAD, "duration_s": MAX_DURATION, "projects": MAX_PROJECTS, "jobs": MAX_JOBS, "workers": 1, "decisions_per_project": 16, "json_bytes": 65536, "job_wall_seconds": 180},
                "workflow": workflow.capabilities(),
                "ai_calls": False, "delivery_approval": False, "missing_delivery_gates": GATES})
        if method == "POST" and len(parts) == 6 and parts[1:3] == ["v1", "projects"] and parts[4] == "stages":
            if self.headers.get("Content-Type") != "application/json":
                raise Rejected("Content-Type must be application/json")
            n = self.length(65536)
            data = self.rfile.read(n)
            if len(data) != n:
                raise Rejected("truncated JSON")
            value = parse_json(data)
            return self.send(202, store.submit_stage(parts[3], parts[5], value))
        if method == "GET" and len(parts) == 6 and parts[1:3] == ["v1", "jobs"] and parts[4] == "stage-artifacts":
            job = store.job(parts[3])
            if job["state"] != "needs_review" or not job["result"] or "stage" not in job["result"]:
                return self.send(409, {"error": "stage artifacts not ready"})
            item = next((a for a in job["result"]["artifacts"] if a["name"] == parts[5]), None)
            if item is None or Path(parts[5]).name != parts[5]:
                raise FileNotFoundError("artifact not in stage manifest")
            return self.send_file(store.path(job["project"]) / (job["id"] + ".stage") / parts[5], item["content_type"], item["sha256"])
        if method == "POST" and self.path == "/v1/projects":
            if self.headers.get("Content-Type") != "video/mp4":
                raise Rejected("Content-Type must be video/mp4")
            return self.send(201, store.create(self.rfile, self.length(MAX_UPLOAD)))
        if len(parts) == 4 and parts[1:3] == ["v1", "projects"]:
            if method == "GET":
                return self.send(200, store.project(parts[3]))
            if method == "DELETE":
                store.delete(parts[3])
                return self.send(200, {"deleted": parts[3]})
        if method == "GET" and len(parts) == 5 and parts[1:3] == ["v1", "projects"]:
            if parts[4] == "decisions":
                return self.send(200, {"decisions": store.decisions(parts[3])})
            if parts[4] == "source":
                project = store.project(parts[3])
                return self.send_file(store.path(parts[3]) / "source.mp4", "video/mp4", project["source_sha256"])
        if method == "POST" and len(parts) == 5 and parts[1:3] == ["v1", "projects"] and parts[4] in ("previews", "decisions"):
            if self.headers.get("Content-Type") != "application/json":
                raise Rejected("Content-Type must be application/json")
            n = self.length(65536)
            data = self.rfile.read(n)
            if len(data) != n:
                raise Rejected("truncated JSON")
            if parts[4] == "decisions":
                return self.send(201, store.save_decision(parts[3], parse_json(data)))
            return self.send(202, store.submit(parts[3], parse_json(data)))
        if method == "GET" and len(parts) in (4, 5, 6) and parts[1:3] == ["v1", "jobs"]:
            job = store.job(parts[3])
            if len(parts) == 4:
                return self.send(200, job)
            if len(parts) == 6 and parts[4] == "artifacts":
                if job["state"] != "needs_review":
                    return self.send(409, {"error": "review artifacts not ready"})
                artifact = job["result"].get("review", {}).get("artifacts", {}).get(parts[5])
                if artifact is None:
                    raise FileNotFoundError("artifact not found")
                return self.send_file(store.path(job["project"]) / parts[5], artifact["content_type"], artifact["sha256"])
            if len(parts) == 5 and parts[4] == "preview":
                if job["state"] != "needs_review" or "workflow_stage" in job["plan"]:
                    return self.send(409, {"error": "preview not ready or job is a workflow stage"})
                path = store.path(job["project"]) / (job["id"] + ".mp4")
                return self.send_file(path, "video/mp4", job["result"]["sha256"])
        self.send(404, {"error": "route not found"})

    def handle_request(self, method):
        try:
            self.route(method)
        except Rejected as exc:
            self.send(422, {"error": str(exc)})
        except FileNotFoundError:
            self.send(404, {"error": "not found"})
        except (TimeoutError, ConnectionError):
            self.close_connection = True
        except Exception:
            self.send(500, {"error": "internal error"})

    def do_GET(self): self.handle_request("GET")
    def do_POST(self): self.handle_request("POST")
    def do_DELETE(self): self.handle_request("DELETE")


def make_server(root, token, host="127.0.0.1", port=8787):
    if token and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
        raise ValueError("VIDEO_API_TOKEN, when set, must be at least 32 non-whitespace ASCII characters")
    server = VideoServer((host, port), Handler)
    server.token = token
    server.store = Store(root)
    return server


if __name__ == "__main__":
    os.umask(0o077)
    server = make_server(os.environ.get("VIDEO_DATA_DIR", "/data"), os.environ.get("VIDEO_API_TOKEN", ""),
                         os.environ.get("VIDEO_BIND", "127.0.0.1"), int(os.environ.get("VIDEO_PORT", "8787")))
    try:
        server.serve_forever()
    finally:
        server.store.close()
        server.server_close()
