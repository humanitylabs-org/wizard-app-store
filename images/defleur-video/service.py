#!/usr/bin/env python3
"""Private, single-owner DeFleur preview service. No Hermes runtime dependency."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import workflow
import motion
import errno
import fcntl
import hmac
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import sqlite3
import struct
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import http.client
import urllib.parse
import secrets
from typing import cast
from editing import Rejected, validate_options, validate_transcript, visual_filters, review_artifacts

VERSION = "0.6.2-testing"
UPSTREAM = "30768288eb1308b18216a5df5eb4648fbce3e55b"
MAX_UPLOAD = 8 * 1024 * 1024 * 1024
MAX_PROJECTS = 8
MAX_JOBS = 256
MAX_DURATION = 1200
EDIT_PIXELS = 1920 * 1080   # editing resolution: larger sources (4K) are normalized down to 1080p, with provenance
MAX_NATIVE_LOG = 256 * 1024
MAX_STAGE_JSON = 1024 * 1024
MAX_MCP_BODY = 8 * 1024 * 1024
MAX_MOTION_JSON = 6 * 1024 * 1024
MCP_PORT = int(os.environ.get("MCP_INTERNAL_PORT", "8788"))
UPLOAD_TTL = 1800
DISK_RESERVE = int(os.environ.get("VIDEO_DISK_RESERVE_MB", "1024")) * 1024 * 1024
NORMALIZE_THREADS = max(2, min(8, os.cpu_count() or 2))
UPLOAD_SECONDS = 3600
UPLOAD_TYPES = ("video/mp4", "video/quicktime", "application/octet-stream")
MEDIA_DIR = os.environ.get("VIDEO_MEDIA_DIR", "/media")  # Runtipi's shared runtipi/media folder (the Files app)
MEDIA_VIDEO_SUFFIXES = (".mov", ".mp4", ".m4v")
MEDIA_EDITED = ("Videos", "Edited")
MEDIA_LIST_MAX = 500
MEDIA_REQUIRE_MOUNT = True  # the image's own empty /media is not the shared folder; tests point MEDIA_DIR at a temp dir
COMMON_FPS = ["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"]
ID = re.compile(r"^[a-f0-9]{32}$")
# Delivery is never approved by this app. Piece 1 supplies the audio/edit
# stages (ASR, alignment, per-edge evidence, dialogue gate) as operator tools.
GATES = ["coherent-thought/editorial-review (operator)", "audio-dialogue-lock (dialogue-gate stage, operator evidence)",
         "fixed-per-setup-face-audit (face-crop stage, sampled frames)", "semantic-HTML-SVG-GSAP-motion (motion-capture stage via the Browser app, operator-authored)",
         "burned-aligned-captions via caption_layer (final-render stage)", "1080x1920 encode via encode.py (final-render stage)",
         "phone-size-and-motion-review (operator)", "delivery-audio-receipt (delivery-gate stage)"]


NATIVE_CONTEXT = threading.local()

UPLOAD_SCRIPT = """
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = document.getElementById('file').files[0];
  const token = document.getElementById('token').value.trim();
  const out = document.getElementById('out');
  if (!file) { out.textContent = 'Choose a video file first.'; return; }
  out.textContent = 'Uploading and checking ' + file.name + ' (' + Math.round(file.size / 1048576) + ' MiB)...';
  const headers = {'Content-Type': 'video/mp4'};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  try {
    const r = await fetch('/v1/projects', {method: 'POST', headers, body: file});
    const j = await r.json();
    out.textContent = r.ok ? 'Done. Project id: ' + j.id + '\\nTell Hermes: edit project ' + j.id : 'Upload failed (HTTP ' + r.status + '): ' + (j.error || '');
  } catch (err) { out.textContent = 'Upload failed: ' + err; }
});
"""
UPLOAD_PAGE = ("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeFleur Video upload</title><style>body{font:16px system-ui,sans-serif;max-width:36rem;margin:2rem auto;padding:0 1rem}
input,button{font:inherit;margin:.4rem 0;max-width:100%;box-sizing:border-box}pre{white-space:pre-wrap;background:#f3f3f3;padding:.6rem}</style></head><body>
<h1>Upload a video</h1><p>MP4 or MOV, up to 20 minutes and 8 GiB, up to 4K. HEVC, variable-frame-rate or larger-than-1080p video is converted to 1080p H.264.</p>
<form id="f"><input type="file" id="file" accept="video/mp4,video/quicktime,.mp4,.mov"><br>
<input type="password" id="token" placeholder="API token (only if this app has one)" autocomplete="off" size="40"><br>
<button type="submit">Upload</button></form><pre id="out" aria-live="polite"></pre>
<script>""" + UPLOAD_SCRIPT + """</script></body></html>""").encode()
UPLOAD_CSP = ("default-src 'none'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'; "
              "script-src 'sha256-" + base64.b64encode(hashlib.sha256(UPLOAD_SCRIPT.encode()).digest()).decode() + "'")


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


def mp4_structure(path, allow_mov=False):
    """Bounded structural allowlist. Payloads are skipped, never recursively guessed.

    The edit source is always ordinary self-contained MP4. With allow_mov (upload
    conversion only) a self-contained QuickTime .mov is also accepted: brand qt,
    up to 16 tracks (real iPhone clips carry several mebx metadata tracks, a timecode
    track and, with spatial audio, a second APAC audio track; some tracks have no
    dref) and self-reference alis/url drefs; it is then converted to MP4.
    Fragmented, reference or compressed movies stay rejected. Every rejection names
    the failing rule and the counts so a phone screenshot is enough to diagnose it.
    Native demuxing additionally has fd-only protocol access. Returns the major brand.
    """
    brands = {b"isom", b"iso2", b"mp41", b"mp42", b"avc1"} | ({b"qt  "} if allow_mov else set())
    max_traks = 16 if allow_mov else 4
    self_refs = {(12, b"url ", 1)} | ({(12, b"alis", 1)} if allow_mov else set())
    major = b""
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
                    nonlocal major
                    major = f.read(4)
                    if major not in brands:
                        raise Rejected("only ISO MP4 or QuickTime MOV brands supported" if allow_mov else "only ISO MP4 brands supported")
                if kind == b"dref":
                    if length < header + 8:
                        raise Rejected("invalid dref")
                    version_flags, entries = struct.unpack(">II", f.read(8))
                    if version_flags != 0 or entries != 1 or length != header + 20:
                        raise Rejected(f"only one self-contained data reference per track supported (track {seen[b'trak']}: "
                                       f"{entries} entries, version/flags {version_flags:#x}, dref {length} bytes)")
                    entry_size, entry_type, flags = struct.unpack(">I4sI", f.read(12))
                    if (entry_size, entry_type, flags) not in self_refs:
                        raise Rejected(f"external data references forbidden (track {seen[b'trak']}: "
                                       f"{entry_type.decode('latin-1')!r} flags {flags}, {entry_size} bytes)")
                if kind in containers:
                    walk(pos + header, pos + length, depth + 1)
                pos += length
        walk(0, size)
    traks, drefs = seen[b"trak"], seen[b"dref"]
    problems = []
    if seen[b"ftyp"] != 1:
        problems.append("needs exactly one ftyp")
    if seen[b"moov"] != 1:
        problems.append("needs exactly one moov")
    if not seen[b"mdat"]:
        problems.append("no mdat (media data)")
    if not 1 <= traks <= max_traks:
        problems.append(f"{traks} tracks (allowed 1..{max_traks})")
    if allow_mov and not 1 <= drefs <= traks:
        problems.append(f"{drefs} data references for {traks} tracks (need 1..{traks})")
    if not allow_mov and drefs != traks:
        problems.append(f"{drefs} data references for {traks} tracks (need one per track)")
    if problems:
        kind = "movie" if allow_mov else "MP4"
        raise Rejected(f"unsupported {kind} structure: {'; '.join(problems)} [{traks} tracks (max {max_traks}), "
                       f"{drefs} data references, ftyp={seen[b'ftyp']} moov={seen[b'moov']} mdat={seen[b'mdat']}]")
    return major


def native(args, source=None, timeout=30, cwd=None, file_limit=33554432, env_extra=None, check=True,
           explain=False, cpu=90, as_limit=1073741824, nofile=64, max_log=MAX_NATIVE_LOG, threads="1"):
    """Bounded native process; one private descriptor, no shell or network inputs.

    prlimit is deliberately a separate executable, avoiding preexec_fn in this
    threaded process. RLIMIT_AS is a native child ceiling, not an OS sandbox.
    Returns stdout, or (returncode, stdout, stderr) when check is False.
    """
    timeout = min(timeout, getattr(NATIVE_CONTEXT, "deadline", float("inf")) - time.monotonic())
    if timeout <= 0:
        raise Rejected("job wall-time limit")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_NUM_THREADS": threads, "OPENBLAS_NUM_THREADS": threads,
           "MKL_NUM_THREADS": threads, **(env_extra or {})}
    with (source.open("rb") if source else open(os.devnull, "rb")) as f:
        command = ["/usr/bin/prlimit", f"--as={as_limit}", f"--cpu={cpu}", f"--fsize={file_limit}", f"--nofile={nofile}", "--", *args]
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
                        if key.data == "err" and len(output["err"]) > max_log:
                            del output["err"][:len(output["err"]) - max_log // 2]  # keep the tail of progress logs
                        if len(output["out"]) > max_log:
                            raise Rejected("native process output limit")
                code = p.wait(timeout=max(0.1, deadline - time.monotonic()))
                if code and check:
                    detail = ""
                    if explain:
                        tail = bytes(output["err"]).decode(errors="replace").strip().splitlines()
                        detail = ": " + (tail[-1][:400] if tail else f"exit {code}")
                    raise Rejected("native media processing failed" + detail)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            p.stdout.close()
            p.stderr.close()
        if not check:
            return p.returncode, bytes(output["out"]), bytes(output["err"])
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
    if not 1 <= width <= 1920 or not 1 <= height <= 1920 or width * height > EDIT_PIXELS:
        raise Rejected("source dimensions exceed the 1080p editing size (larger sources are normalized on upload)")
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


def loose_input_args():
    """Like input_args but admits phone-size (up to 4096x2304) frames for normalization only."""
    args = input_args()
    args[args.index("-max_pixels") + 1] = str(4096 * 2304)
    args[args.index("-max_streams") + 1] = "16"
    return args


def frame_rate_mode(source, stream):
    """CFR iff every video packet PTS sits on the nominal frame grid (packets only; no decode)."""
    rate = stream.get("r_frame_rate", "0/1")
    try:
        num, den = (int(x) for x in rate.split("/"))
        step = den / num
    except (ValueError, ZeroDivisionError):
        return "unknown", rate
    raw = parse_json(native(["/usr/bin/ffprobe", "-v", "error", *loose_input_args(),
                             "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "json"], source,
                            timeout=120, cpu=120, max_log=64 * 1024 * 1024))
    pts = sorted(float(p["pts_time"]) for p in raw.get("packets", []) if p.get("pts_time") not in (None, "N/A"))
    if len(pts) < 2:
        return "unknown", rate
    tick = 0.5 * step
    for i, t in enumerate(pts):
        if abs((t - pts[0]) - i * step) > tick:
            return "variable", rate
    if stream.get("avg_frame_rate") not in (rate, None, "0/0"):
        try:
            a, b = (int(x) for x in stream["avg_frame_rate"].split("/"))
            if abs(a / b - num / den) > 0.01:
                return "variable", rate
        except (ValueError, ZeroDivisionError):
            pass
    return "constant", rate


def target_fps(stream):
    """Nearest common rate to the average (VFR phones hover around 30/60)."""
    try:
        a, b = (int(x) for x in stream.get("avg_frame_rate", "30/1").split("/"))
        avg = a / b
    except (ValueError, ZeroDivisionError):
        avg = 30.0
    return min(COMMON_FPS, key=lambda r: abs(int(r.split("/")[0]) / int(r.split("/")[1]) - avg))


NORMALIZE_LOCK = threading.Semaphore(1)


def normalize_if_needed(path):
    """HEVC / VFR / extra-track phone footage -> H.264 CFR + AAC. Returns provenance or None."""
    brand = mp4_structure(path, allow_mov=True)
    value = parse_json(native(["/usr/bin/ffprobe", "-v", "error", *loose_input_args(), "-show_streams", "-show_format", "-of", "json"], path))
    streams = value.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) < 1 or videos[0].get("codec_name") not in ("h264", "hevc"):
        if brand == b"qt  ":
            raise Rejected("this MOV needs one H.264 or HEVC video track and an audio track")
        return None  # probe() rejects it with the usual message
    # iPhone spatial-audio clips can carry an extra codec ffmpeg can't decode; prefer AAC, then any common codec.
    common = ("aac", "alac", "mp3", "ac3", "eac3", "opus", "flac")
    v = videos[0]
    a = next((s for s in audios if s.get("codec_name") == "aac"), None) or \
        next((s for s in audios if s.get("codec_name") in common or str(s.get("codec_name", "")).startswith("pcm_")), None)
    if a is None:
        raise Rejected("no decodable audio track (found: " + ", ".join(str(s.get("codec_name")) for s in audios) + ")")
    hdr = v.get("color_transfer") in ("arib-std-b67", "smpte2084")
    try:
        duration = float(value["format"]["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise Rejected("invalid source metadata") from exc
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise Rejected(f"source duration must be at most {MAX_DURATION} seconds")
    mode, rate = frame_rate_mode(path, v)
    reasons = []
    if brand == b"qt  ":
        reasons.append("QuickTime MOV container")
    if hdr:
        reasons.append(f"HDR ({v.get('color_transfer')}) tone-mapped to SDR BT.709")
    if v["codec_name"] == "hevc":
        reasons.append("HEVC video")
    if mode != "constant":
        reasons.append(f"{mode} frame rate")
    big = int(v.get("width", 0)) * int(v.get("height", 0)) > EDIT_PIXELS or max(int(v.get("width", 0)), int(v.get("height", 0))) > 1920
    if big:
        reasons.append(f"{v.get('width')}x{v.get('height')} is larger than 1080p (normalized down for editing)")
    if not reasons:
        return None  # H.264 CFR up to 1080p: keep the original bytes untouched
    if a.get("codec_name") != "aac" or a.get("channels", 9) > 2:
        reasons.append(f"audio {a.get('codec_name')} x{a.get('channels')}")
    if len(streams) != 2:
        reasons.append(f"{len(streams)} streams (keeping one video and one audio)")
    if __import__("shutil").disk_usage(path.parent).free < path.stat().st_size * 2 + DISK_RESERVE:
        raise Rejected("not enough free disk to convert this upload (needs about 2x its size plus 1 GiB)")
    if not NORMALIZE_LOCK.acquire(blocking=False):
        raise Rejected("another upload is being converted; retry in a few minutes")
    try:
        fps = target_fps(v)
        out = path.with_name(path.name + ".norm.mp4")
        started = time.monotonic()
        # Fit inside 1920x1920 and 2073600 px with even dimensions. Rotation metadata is applied
        # by ffmpeg's autorotate, so swap the axes for 90/270-degree sources.
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = next((abs(int(float(x["rotation"]))) for x in v.get("side_data_list", []) if "rotation" in x), 0)
        if rot % 180 == 90:
            w, h = h, w
        f = min(1.0, 1920 / max(w, h), math.sqrt(2073600 / (w * h)))
        scale = f"scale={max(2, int(w * f) // 2 * 2)}:{max(2, int(h * f) // 2 * 2)},setsar=1"
        chain = scale
        color = []
        if hdr:
            # Scale first (cheap), then a standard zscale+tonemap HDR->SDR pass so iPhone HDR doesn't look washed out.
            chain += (f",zscale=tin={v.get('color_transfer')}:min=bt2020nc:pin=bt2020:t=linear:npl=100,format=gbrpf32le,"
                      "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
            color = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        native(["/usr/bin/ffmpeg", "-v", "error", "-nostdin", *loose_input_args(), "-map", f"0:{int(v['index'])}", "-map", f"0:{int(a['index'])}",
                "-vf", chain, *color, "-fps_mode", "cfr", "-r", fps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", str(min(2, int(a.get("channels") or 2))),
                "-map_metadata", "-1", "-movflags", "+faststart", "-threads", str(NORMALIZE_THREADS), "-filter_threads", "2", "-y", out],
               path, timeout=7200, cpu=7200 * NORMALIZE_THREADS, file_limit=MAX_UPLOAD * 2, as_limit=8 * 1024**3, explain=True,
               threads=str(NORMALIZE_THREADS))
        original = {"sha256": digest(path), "bytes": path.stat().st_size, "video_codec": v["codec_name"],
                    "width": int(v.get("width", 0)), "height": int(v.get("height", 0)),
                    "frame_rate_mode": mode, "r_frame_rate": rate, "avg_frame_rate": v.get("avg_frame_rate"),
                    "audio_codec": a.get("codec_name"), "streams": len(streams), "duration": duration}
        out.replace(path)
        return {"original": original, "normalization": {
            "reasons": reasons, "tool": "ffmpeg libx264 veryfast crf 18 + AAC 192k 48 kHz", "fps": fps, "frame_rate_mode": "constant",
            "seconds": round(time.monotonic() - started, 2),
            "scaled_to": scale.split(",")[0].removeprefix("scale="),
            "note": "The normalized H.264 CFR file (at most 1080p) is the edit source; the original bytes are not kept, only their SHA-256."}}
    finally:
        path.with_name(path.name + ".norm.mp4").unlink(missing_ok=True)
        NORMALIZE_LOCK.release()


# ---------- shared Files folder (/media) ----------

def media_parts(rel, allow_root=False):
    """Validate a path relative to /media. No absolute paths, no '..', no control characters."""
    if not isinstance(rel, str) or len(rel) > 1024 or any(ord(c) < 32 or c == "\x7f" for c in rel):
        raise Rejected("path must be text relative to the Files folder, e.g. 'Videos/IMG_5644.mov'")
    if rel.startswith("/") or rel.startswith("~"):
        raise Rejected("absolute paths are not allowed; give the path inside Files, e.g. 'Videos/IMG_5644.mov'")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise Rejected("'..' is not allowed in a Files path")
    if not parts and not allow_root:
        raise Rejected("give a file path inside Files, e.g. 'Videos/IMG_5644.mov'")
    return parts


def media_open_dir(parts, create=False):
    """Open /media/<parts> one component at a time with O_NOFOLLOW, so no symlink can lead outside /media."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    fd = os.open(MEDIA_DIR, flags)
    try:
        for i, part in enumerate(parts):
            try:
                nxt = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise FileNotFoundError("/".join(parts[:i + 1]) + " not found in Files") from None
                try:
                    os.mkdir(part, 0o775, dir_fd=fd)
                except FileExistsError:
                    pass
                nxt = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
                os.fchmod(nxt, 0o775)  # the service umask is 077; shared folders stay usable by other apps
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise Rejected(f"'{'/'.join(parts[:i + 1])}' is a symlink or not a folder; Files paths never follow symlinks") from None
                raise
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def media_open_file(rel):
    """Open a regular file under /media read-only: O_NOFOLLOW at every step, regular files only."""
    parts = media_parts(rel)
    if not parts[-1].lower().endswith(MEDIA_VIDEO_SUFFIXES):
        raise Rejected("only video files (.mov, .mp4, .m4v) can be imported")
    dfd = media_open_dir(parts[:-1])
    try:
        try:
            st = os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            raise FileNotFoundError("/".join(parts) + " not found in Files") from None
        if not stat.S_ISREG(st.st_mode):
            raise Rejected(f"'{'/'.join(parts)}' is not a regular file (symlinks, folders and devices are refused)")
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise Rejected(f"'{'/'.join(parts)}' is a symlink; Files paths never follow symlinks") from None
            raise
    finally:
        os.close(dfd)
    st2 = os.fstat(fd)
    if not stat.S_ISREG(st2.st_mode) or (st2.st_dev, st2.st_ino) != (st.st_dev, st.st_ino):
        os.close(fd)
        raise Rejected(f"'{'/'.join(parts)}' changed while opening; try again")
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
    return os.fdopen(fd, "rb"), st2.st_size, parts


def media_list(folder="Videos"):
    parts = media_parts(folder, allow_root=True)
    files, skipped = [], 0
    root = media_open_dir(parts)

    def walk(fd, prefix, depth):
        nonlocal skipped
        with os.scandir(fd) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            if e.name.startswith(".") or len(files) >= MEDIA_LIST_MAX:
                continue
            rel = "/".join(prefix + [e.name])
            if e.is_dir(follow_symlinks=False):
                if depth < 3:
                    try:
                        sub = os.open(e.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    except OSError:
                        continue
                    try:
                        walk(sub, prefix + [e.name], depth + 1)
                    finally:
                        os.close(sub)
            elif e.is_file(follow_symlinks=False) and e.name.lower().endswith(MEDIA_VIDEO_SUFFIXES):
                st = e.stat(follow_symlinks=False)
                files.append({"path": rel, "name": e.name, "bytes": st.st_size,
                              "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                              "edited_output": prefix[:2] == list(MEDIA_EDITED)})
            else:
                skipped += 1
    try:
        walk(root, parts, 0)
    finally:
        os.close(root)
    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"folder": "/".join(parts) or ".", "files": files, "truncated": len(files) >= MEDIA_LIST_MAX,
            "non_video_entries_skipped": skipped}


def media_status():
    """Is the shared Files folder usable? Never raises; reports a plain fix instead."""
    out = {"mount": MEDIA_DIR, "present": False, "readable": False, "videos_folder": False, "edited_folder": "Videos/Edited",
           "writable": False, "fix": None}
    upload_note = " Uploads with create_upload keep working meanwhile."
    try:
        st = os.stat(MEDIA_DIR)
        out["present"] = stat.S_ISDIR(st.st_mode) and (os.path.ismount(MEDIA_DIR) or not MEDIA_REQUIRE_MOUNT)
    except OSError:
        pass
    if not out["present"]:
        out["fix"] = ("The shared Files folder is not mounted in DeFleur Video (no /media). Update DeFleur Video in Runtipi to "
                      "0.6.2 or later (it mounts runtipi/media), and install the Files app from the Wizard App Store." + upload_note)
        return out
    out["readable"] = os.access(MEDIA_DIR, os.R_OK | os.X_OK)
    if not out["readable"]:
        out["fix"] = ("DeFleur Video cannot read the shared Files folder (runtipi/media). Install or update the Files app from the "
                      "Wizard App Store; its first start makes the folder usable by apps (user 1000)." + upload_note)
        return out
    try:
        os.close(media_open_dir(["Videos"]))
        out["videos_folder"] = True
    except (OSError, Rejected):
        pass
    read_only = bool(os.statvfs(MEDIA_DIR).f_flag & os.ST_RDONLY)
    # Non-mutating: the deepest existing folder on the way to Videos/Edited must be writable (save creates the rest).
    target = Path(MEDIA_DIR)
    for part in MEDIA_EDITED:
        nxt = target / part
        if nxt.is_symlink() or not nxt.is_dir():
            break
        target = nxt
    out["writable"] = not read_only and not target.is_symlink() and os.access(target, os.W_OK | os.X_OK)
    if read_only:
        out["fix"] = ("The shared Files folder is mounted read-only, so finished videos cannot be saved to Files → Videos → Edited "
                      "(they stay downloadable from the render_final link). Reading videos from Files still works.")
    elif not out["writable"]:
        out["fix"] = ("DeFleur Video cannot write Files → Videos → Edited (runtipi/media is not writable by user 1000). Install or "
                      "update the Files app from the Wizard App Store and start it once: it creates Videos/ and Videos/Edited/ "
                      "for apps. Finished videos stay downloadable from the render_final link meanwhile.")
    elif not out["videos_folder"]:
        out["fix"] = "There is no Videos folder in Files yet. Install the Files app (it creates Videos/ and Videos/Edited/)."
    return out


def media_save_final(src, sha256, stem, short_id):
    """Copy a verified final MP4 to /media/Videos/Edited/<stem>-edited-<id>.mp4: never overwrite, atomic, mode 0664."""
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(stem).replace("\\", "/").rsplit("/", 1)[-1])[:80].strip(" ._-") or "video"
    dfd = media_open_dir(list(MEDIA_EDITED), create=True)
    try:
        if __import__("shutil").disk_usage(os.path.join(MEDIA_DIR, *MEDIA_EDITED)).free < src.stat().st_size + 64 * 1024 * 1024:
            raise Rejected("not enough free disk in Files to save the finished video")
        tmp = f".{stem}-edited-{short_id}.{secrets.token_hex(4)}.partial"
        h = hashlib.sha256()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o664, dir_fd=dfd)
        try:
            with os.fdopen(fd, "wb", closefd=False) as out, src.open("rb") as f:
                while chunk := f.read(1024 * 1024):
                    h.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fchmod(fd, 0o664)
                os.fsync(fd)
            os.close(fd)
            fd = -1
            if h.hexdigest() != sha256:
                raise Rejected("final video hash changed while saving; not saved")
            for n in range(1, 100):
                name = f"{stem}-edited-{short_id}" + (f"-{n}" if n > 1 else "") + ".mp4"
                try:
                    os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)  # fails if name exists
                    break
                except FileExistsError:
                    continue
                except OSError as exc:
                    if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.EMLINK):
                        raise
                    try:  # filesystems without hard links: rename only when the name is free
                        os.stat(name, dir_fd=dfd, follow_symlinks=False)
                        continue
                    except FileNotFoundError:
                        os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
                        break
            else:
                raise Rejected("too many saved copies with this name in Videos/Edited")
            os.fsync(dfd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp, dir_fd=dfd)
            except FileNotFoundError:
                pass
        return {"saved_to": "/".join(MEDIA_EDITED + (name,)), "name": name, "bytes": src.stat().st_size, "sha256": sha256}
    finally:
        os.close(dfd)


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

    def create(self, stream, length, extra=None):
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
                deadline = time.monotonic() + UPLOAD_SECONDS
                while remaining:
                    if time.monotonic() > deadline:
                        raise Rejected("upload wall-time limit")
                    data = stream.read1(min(65536, remaining))
                    if not data:
                        raise Rejected("truncated upload")
                    f.write(data)
                    remaining -= len(data)
            converted = normalize_if_needed(tmp)
            metadata = probe(tmp)
            if converted:
                metadata.update(converted)
            metadata.update({"id": identifier, "upstream_commit": UPSTREAM, "created": time.time(), "missing_delivery_gates": GATES})
            metadata.update(extra or {})
            dest = self.path(identifier)
            dest.mkdir(mode=0o700)
            tmp.rename(dest / "source.mp4")
            with self.connect() as c:
                c.execute("INSERT INTO projects VALUES(?,?)", (identifier, json_bytes(metadata).decode()))
            return metadata
        finally:
            tmp.unlink(missing_ok=True)

    def import_media(self, rel):
        """A file from the shared Files folder becomes a project through exactly the upload path (create())."""
        f, size, parts = media_open_file(rel)
        with f:
            return self.create(f, size, {"imported_from": "/".join(parts), "source_name": parts[-1]})

    def save_final(self, jid):
        job = self.job(jid)
        result = job["result"] or {}
        if job["state"] != "needs_review" or result.get("stage") != "final-render":
            raise Rejected("only a finished final-render job can be saved to Files")
        item = next((a for a in result["artifacts"] if a["name"] == "final.mp4"), None)
        if item is None:
            raise FileNotFoundError("final.mp4 not in the render manifest")
        src = self.path(job["project"]) / (jid + ".stage") / "final.mp4"
        if digest(src) != item["sha256"]:
            raise Rejected("artifact hash changed; not saved")
        metadata = self.project(job["project"])
        stem = Path(metadata.get("source_name") or "video").stem
        return media_save_final(src, item["sha256"], stem, jid[:8])

    def projects(self):
        with self.connect() as c:
            rows = c.execute("SELECT metadata FROM projects").fetchall()
        out = []
        for row in rows:
            m = parse_json(row[0])
            out.append({"id": m["id"], "duration": m["duration"], "width": m["width"], "height": m["height"],
                        "created": m.get("created"), "normalized": "normalization" in m, "imported_from": m.get("imported_from")})
        return sorted(out, key=lambda m: m["created"] or 0)

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

    def stage_ref(self, project, jid, stages):
        """Resolve a client-supplied job reference to a finished stage of the same project."""
        if not isinstance(jid, str) or not ID.fullmatch(jid):
            raise Rejected("job reference must be a 32-hex job id")
        try:
            job = self.job(jid)
        except FileNotFoundError:
            raise Rejected(f"referenced job {jid} not found")
        if job["project"] != project or job["state"] != "needs_review" or not job["result"] or job["result"].get("stage") not in stages:
            raise Rejected(f"job {jid} is not a finished {'/'.join(sorted(stages))} stage of this project")
        return job, self.path(project) / (jid + ".stage")

    def submit_stage(self, identifier, stage, value):
        metadata = self.project(identifier)
        workflow.validate(stage, value, metadata, lambda jid, stages: self.stage_ref(identifier, jid, stages))
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
                plan = parse_json(row["plan"])
                stage = plan.get("workflow_stage")
                NATIVE_CONTEXT.deadline = time.monotonic() + (workflow.deadline_for(stage) if stage else 180)
                source = self.path(row["project"]) / "source.mp4"
                metadata = self.project(row["project"])
                if stage:
                    result = workflow.run(stage, plan["input"], source, target.with_suffix(".stage"), metadata, native,
                        lambda jid, stages, p=row["project"]: self.stage_ref(p, jid, stages), NATIVE_CONTEXT.deadline, input_args)
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
                for partial in [*target.parent.glob(row["id"] + ".*"), *target.parent.glob(row["id"] + "-*")]:
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


class VideoServer(ThreadingHTTPServer):
    daemon_threads = True
    token: str
    store: Store
    uploads: dict
    asset_uploads: dict
    uploads_lock: threading.Lock


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

    def proxy_mcp(self, method):
        """Forward /mcp to the loopback MCP server (official SDK, Streamable HTTP)."""
        n = int(self.headers.get("Content-Length") or 0) if method == "POST" else 0
        if not 0 <= n <= MAX_MCP_BODY:
            raise Rejected("MCP request too large")
        body = self.rfile.read(n) if n else None
        headers = {k: v for k, v in self.headers.items() if k.lower() in (
            "content-type", "accept", "mcp-session-id", "mcp-protocol-version", "last-event-id", "host")}
        c = http.client.HTTPConnection("127.0.0.1", MCP_PORT, timeout=150)
        try:
            try:
                c.request(method, self.path, body=body, headers=headers)
                r = c.getresponse()
            except OSError:
                return self.send(503, {"error": "MCP server is starting or unavailable; retry in a few seconds"})
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() in ("content-type", "mcp-session-id", "cache-control", "content-length", "allow", "www-authenticate"):
                    self.send_header(k, v)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while chunk := r.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            c.close()

    def route(self, method):
        if self.path == "/healthz" and method == "GET":
            return self.send(200, {"status": "ok", "version": VERSION})
        server = cast(VideoServer, self.server)
        parts = self.path.split("/")
        if method == "GET" and self.path == "/upload":
            self.send_response(200)
            for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(UPLOAD_PAGE))),
                         ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                         ("Content-Security-Policy", UPLOAD_CSP), ("Referrer-Policy", "no-referrer")):
                self.send_header(k, v)
            self.end_headers()
            return self.wfile.write(UPLOAD_PAGE)
        if method == "POST" and len(parts) == 4 and parts[1:3] == ["v1", "uploads"]:
            # One-time capability URL from create_upload: the token in the path is the credential.
            with server.uploads_lock:
                now = time.time()
                for k in [k for k, exp in server.uploads.items() if exp < now]:
                    del server.uploads[k]
                ok = any(hmac.compare_digest(parts[3], k) for k in server.uploads) and server.uploads.pop(parts[3], 0) >= now
            if not ok:
                return self.send(403, {"error": "upload URL unknown, used or expired; ask for a new one (create_upload)"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() not in UPLOAD_TYPES:
                raise Rejected("Content-Type must be video/mp4 (curl: -H 'Content-Type: video/mp4')")
            return self.send(201, server.store.create(self.rfile, self.length(MAX_UPLOAD)))
        if method == "POST" and len(parts) == 4 and parts[1:3] == ["v1", "asset-uploads"]:
            # One-time capability URL from create_asset_upload: names one project and one composition path.
            with server.uploads_lock:
                now = time.time()
                for k in [k for k, v in server.asset_uploads.items() if v[2] < now]:
                    del server.asset_uploads[k]
                key = next((k for k in server.asset_uploads if hmac.compare_digest(parts[3], k)), None)
                grant = server.asset_uploads.pop(key) if key else None
            if grant is None:
                return self.send(403, {"error": "asset upload URL unknown, used or expired; ask for a new one (create_asset_upload)"})
            project, rel, _ = grant
            server.store.project(project)
            n = self.length(motion.MAX_ASSET.get(Path(rel).suffix, 0))
            return self.send(201, {"project_id": project, **motion.store_asset(server.store.path(project), rel, self.rfile, n),
                                   "motion": {k: v for k, v in motion.status(server.store.path(project)).items() if k != "plan"}})
        if not self.authorize():
            return
        if self.path == "/mcp" or self.path.startswith("/mcp?"):
            if method not in ("GET", "POST", "DELETE"):
                return self.send(405, {"error": "method not allowed"})
            return self.proxy_mcp(method)
        if method == "POST" and self.path == "/v1/uploads":
            n = int(self.headers.get("Content-Length") or "0") if (self.headers.get("Content-Length") or "0").isdigit() else -1
            if not 0 <= n <= 4096 or self.headers.get("Transfer-Encoding"):
                raise Rejected("upload request body must be empty or a small JSON object")
            self.rfile.read(n)
            token = secrets.token_urlsafe(32)
            with server.uploads_lock:
                if len(server.uploads) >= 64:
                    server.uploads.pop(min(server.uploads, key=server.uploads.get))
                server.uploads[token] = time.time() + UPLOAD_TTL
            return self.send(201, {"path": "/v1/uploads/" + token, "expires_in_s": UPLOAD_TTL, "one_time": True})
        if method == "GET" and self.path == "/v1/projects":
            return self.send(200, {"projects": server.store.projects()})
        if method == "GET" and (self.path == "/v1/media" or self.path.startswith("/v1/media?")):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, max_num_fields=4)
            status = media_status()
            if not status["readable"]:
                return self.send(409, {"error": status["fix"], "media": status})
            return self.send(200, {**media_list(query.get("folder", ["Videos"])[0]), "media": status})
        if method == "POST" and self.path in ("/v1/media/import", "/v1/media/save-final"):
            if self.headers.get("Content-Type") != "application/json":
                raise Rejected("Content-Type must be application/json")
            n = self.length(4096)
            value = parse_json(self.rfile.read(n))
            if self.path == "/v1/media/import":
                if not isinstance(value, dict) or set(value) != {"path"}:
                    raise Rejected('body must be {"path": "Videos/IMG_5644.mov"}')
                if not media_status()["readable"]:
                    raise Rejected(media_status()["fix"])
                return self.send(201, server.store.import_media(value["path"]))
            if not isinstance(value, dict) or set(value) != {"job"}:
                raise Rejected('body must be {"job": "<final-render job id>"}')
            status = media_status()
            if not status["writable"]:
                return self.send(409, {"error": status["fix"] or "Files folder not writable", "media": status})
            return self.send(201, server.store.save_final(value["job"]))
        store = server.store
        if method == "GET" and self.path == "/v1/capabilities":
            return self.send(200, {"version": VERSION, "upstream_commit": UPSTREAM,
                "operations": ["upload_mp4", "workflow_stages", "read_workflow_docs", "submit_edit_plan_preview", "persist_transcript_decisions", "burn_timed_captions", "fixed_protected_crop", "cut_edge_review_artifacts", "poll_job", "download_preview", "delete_project"],
                "limits": {"upload_bytes": MAX_UPLOAD, "duration_s": MAX_DURATION, "output_duration_s": workflow.MAX_OUTPUT_S, "editing_resolution": "up to 1920x1080 (4K and other larger sources are normalized down on upload)", "motion_inline_json_bytes": MAX_MOTION_JSON, "motion_asset_bytes": {k: v for k, v in motion.MAX_ASSET.items()}, "projects": MAX_PROJECTS, "jobs": MAX_JOBS, "workers": 1, "decisions_per_project": 16, "json_bytes": MAX_STAGE_JSON, "preview_job_wall_seconds": 180},
                "workflow": workflow.capabilities(), "media": media_status(),
                "ai_calls": False, "delivery_approval": False, "missing_delivery_gates": GATES})
        if method == "POST" and len(parts) == 6 and parts[1:3] == ["v1", "projects"] and parts[4] == "stages":
            if self.headers.get("Content-Type") != "application/json":
                raise Rejected("Content-Type must be application/json")
            n = self.length(MAX_STAGE_JSON)
            data = self.rfile.read(n)
            if len(data) != n:
                raise Rejected("truncated JSON")
            value = parse_json(data)
            return self.send(202, store.submit_stage(parts[3], parts[5], value))
        if len(parts) == 5 and parts[1:3] == ["v1", "projects"] and parts[4] in ("motion", "asset-uploads"):
            store.project(parts[3])
            folder = store.path(parts[3])
            if method == "GET" and parts[4] == "motion":
                return self.send(200, motion.status(folder))
            if method == "DELETE" and parts[4] == "motion":
                motion.clear(folder)
                return self.send(200, motion.status(folder))
            if method == "POST":
                if self.headers.get("Content-Type") != "application/json":
                    raise Rejected("Content-Type must be application/json")
                n = self.length(MAX_MOTION_JSON)
                data = self.rfile.read(n)
                if len(data) != n:
                    raise Rejected("truncated JSON")
                value = parse_json(data)
                if parts[4] == "asset-uploads":
                    if not isinstance(value, dict) or set(value) != {"path"}:
                        raise Rejected("body must be {\"path\": \"assets/name.mp4\"}")
                    rel = motion.check_path(value["path"])
                    if Path(rel).suffix not in motion.BINARY_KINDS:
                        raise Rejected("asset uploads are for .png/.jpg/.jpeg/.webp/.woff2/.mp4 files")
                    token = secrets.token_urlsafe(32)
                    with server.uploads_lock:
                        if len(server.asset_uploads) >= 64:
                            server.asset_uploads.pop(min(server.asset_uploads, key=lambda k: server.asset_uploads[k][2]))
                        server.asset_uploads[token] = (parts[3], rel, time.time() + UPLOAD_TTL)
                    return self.send(201, {"path": "/v1/asset-uploads/" + token, "asset_path": rel, "expires_in_s": UPLOAD_TTL,
                                           "max_bytes": motion.MAX_ASSET[Path(rel).suffix], "one_time": True})
                if not isinstance(value, dict) or set(value) - {"files", "plan", "replace"} or "plan" not in value:
                    raise Rejected("body must be {files: {path: text|{base64}}, plan: {...}, replace?: bool}")
                with store.connect() as c:
                    if c.execute("SELECT 1 FROM jobs WHERE project=? AND state IN ('queued','running')", (parts[3],)).fetchone():
                        raise Rejected("a job is running for this project; wait before changing the motion composition")
                # The edited duration is checked again at capture time against the locked timeline.
                return self.send(201, motion.submit(folder, value.get("files", {}), value["plan"], None, bool(value.get("replace", True))))
        if method == "GET" and self.path == "/v1/workflow/docs":
            return self.send(200, {"docs": sorted(workflow.DOCS)})
        if method == "GET" and len(parts) == 5 and parts[1:4] == ["v1", "workflow", "docs"]:
            path = workflow.doc(parts[4])
            kind = "application/json" if path.suffix == ".json" else "text/markdown; charset=utf-8" if path.suffix == ".md" else "text/plain; charset=utf-8"
            return self.send(200, path.read_bytes(), kind)
        if method == "GET" and len(parts) == 6 and parts[1:3] == ["v1", "jobs"] and parts[4] == "stage-artifacts":
            job = store.job(parts[3])
            if job["state"] != "needs_review" or not job["result"] or "stage" not in job["result"]:
                return self.send(409, {"error": "stage artifacts not ready"})
            item = next((a for a in job["result"]["artifacts"] if a["name"] == parts[5]), None)
            if item is None or Path(parts[5]).name != parts[5]:
                raise FileNotFoundError("artifact not in stage manifest")
            return self.send_file(store.path(job["project"]) / (job["id"] + ".stage") / parts[5], item["content_type"], item["sha256"])
        if method == "POST" and self.path == "/v1/projects":
            if self.headers.get("Content-Type", "").split(";")[0].strip() not in UPLOAD_TYPES:
                raise Rejected("Content-Type must be video/mp4 or video/quicktime")
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
        except FileNotFoundError as exc:
            msg = str(exc.args[0]) if exc.args and isinstance(exc.args[0], str) and "in Files" in exc.args[0] else "not found"
            self.send(404, {"error": msg})
        except PermissionError:
            self.send(409, {"error": "permission denied in the shared Files folder (runtipi/media); see capabilities for the fix"})
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
    server.uploads, server.uploads_lock = {}, threading.Lock()
    server.asset_uploads = {}
    server.store = Store(root)
    return server


def supervise_mcp(port, token):
    """Run mcp_server.py (needs /opt/venv's mcp SDK) on loopback; restart it if it dies."""
    python = os.environ.get("VIDEO_MCP_PYTHON", "/opt/venv/bin/python")
    script = Path(__file__).with_name("mcp_server.py")
    if not Path(python).is_file() or not script.is_file():
        return None
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "VIDEO_DATA_DIR", "VIDEO_PUBLIC_URL", "TMPDIR", "HOME")}
    env.update({"VIDEO_INTERNAL_API": f"http://127.0.0.1:{port}", "VIDEO_API_TOKEN": token, "VIDEO_VERSION": VERSION,
                "MCP_INTERNAL_PORT": str(MCP_PORT), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})

    def loop():
        while True:
            started = time.monotonic()
            subprocess.run([python, "-I", str(script)], env=env, stdin=subprocess.DEVNULL)
            time.sleep(1 if time.monotonic() - started > 30 else 10)
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    os.umask(0o077)
    server = make_server(os.environ.get("VIDEO_DATA_DIR", "/data"), os.environ.get("VIDEO_API_TOKEN", ""),
                         os.environ.get("VIDEO_BIND", "127.0.0.1"), int(os.environ.get("VIDEO_PORT", "8787")))
    supervise_mcp(server.server_address[1], server.token)
    try:
        server.serve_forever()
    finally:
        server.store.close()
        server.server_close()
