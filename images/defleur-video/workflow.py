"""API stages over James DeFleur's bundled workflow helpers (piece 1: audio/edit).

James' original scripts ship unchanged under /opt/defleur (see NOTICE). Every
stage runs them with server-owned paths in a fresh per-job directory; clients
send JSON decisions and job references only, never paths, shell, filters or
executables. Each output file is listed with its SHA-256 in the job result and
re-verified whenever a later stage consumes it.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import wave

from editing import Rejected
import motion
import transcriber

UPSTREAM_ROOT = Path(os.environ.get("DEFLEUR_ROOT") or ("/opt/defleur" if Path("/opt/defleur").is_dir() else Path(__file__).with_name("defleur")))
APP_ROOT = Path(__file__).resolve().parent
HELPER_PYTHON = os.environ.get("VIDEO_HELPER_PYTHON") or ("/opt/venv/bin/python" if Path("/opt/venv/bin/python").exists() else sys.executable)
MODELS_DIR = Path(os.environ.get("VIDEO_MODELS_DIR", "/data/models"))
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
FACE_MODEL = Path(os.environ.get("VIDEO_FACE_MODEL", "/opt/models/yunet.onnx"))
FACE_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"  # opencv_zoo YuNet 2023mar (MIT)
CANVAS = (1080, 1920)
CAPTURE_DIR = Path(os.environ.get("VIDEO_CAPTURE_DIR") or ("/opt/capture" if Path("/opt/capture").is_dir() else APP_ROOT / "capture"))
CAPTURE_SCRIPT = CAPTURE_DIR / "capture-remote.cjs"
GSAP = CAPTURE_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js"
CAPTURE_ADAPTED_SHA256 = "d8d8e62b0bc490d59c1112673fdcd1e0e87d1d1d311b41ff104e16819ab9d2ce"  # NOTICE: diff of James' capture.cjs
NODE = os.environ.get("VIDEO_NODE", "/usr/bin/node")
DEFAULT_BROWSER_URL = "http://browser:9222"
MAX_OUTPUT_S = float(os.environ.get("VIDEO_MAX_OUTPUT_S", "360"))
FRAME_BYTES = 520_000          # measured ~0.3-0.45 MB per 1080x1920 q95 JPEG; generous
BROWSER_HINT = ("Install the Browser app from the Wizard App Store on the same Runtipi host (reachable as "
                "http://browser:9222), or set BROWSER_URL in this app's settings.")

# Exact upstream bytes (commit 30768288eb1308b18216a5df5eb4648fbce3e55b). Verified before every run.
HELPERS = {
    "probe_source": ("skills/defleur-edit/scripts/probe_source.py", "ce1874c4b81547b56d60de129a235ad97857c560abf69b091f7a821454ed7cf0"),
    "preset": ("skills/defleur-edit/scripts/preset.py", "5260b709e71a694756e2a9da4088ffb0323f6f4fc02ab4c3ff3c11516b7b75ce"),
    "validate_project": ("skills/defleur-edit/scripts/validate_project.py", "4cfb6a9e7c3a633eb37920ae6e2b343c46df05740f4e7ca97ea8108d07d7dd05"),
    "preflight": ("skills/defleur-audio/scripts/preflight.py", "ab4aa87761859c43b91841fe899e203ba54491705abd6684722e554ccaecca14"),
    "asr": ("skills/defleur-audio/scripts/asr.py", "e007fc22e31822aa0b1b46fccdf1a295b4b813e4230d391f7bbbc24285935a96"),
    "align": ("skills/defleur-audio/scripts/align.py", "620bc9eae9dbb54531672284b766a1fd72d816ec8ab65b4f81322c055bb76f36"),
    "acoustic_ctc_window": ("skills/defleur-audio/scripts/acoustic_ctc_window.py", "5cd9525d60ce8ec61cef544442962666f4a00070e262c8b494bcdf9d158ab7cf"),
    "speech_cut_audit": ("skills/defleur-audio/scripts/speech_cut_audit.py", "b0762b7bf53abe16f2664887a0b06446481840eae99317b800850a63b9bbfcd4"),
    "assemble_pcm": ("skills/defleur-audio/scripts/assemble_pcm.py", "96731e90aac18c4209e4408e0469751e5e8029fe7cb62a4f6795d1e51bde7c1e"),
    "audio_gate": ("skills/defleur-audio/scripts/audio_gate.py", "aa2d5965b0cc8f19103f42899cfe3be09c6b9760c3e16a2717bf4441a81431ce"),
    "encode": ("skills/defleur-motion/scripts/encode.py", "1b431ca6012804d4add45841437a0737038dc36d7318e06d4975bcbddddcb76d"),
    "capture": ("skills/defleur-motion/scripts/capture.cjs", "e09fc4625000dbde832900ef0b94c45a2fbbe56a22a97436f93f6a05e4a86b89"),
    "caption_layer": ("skills/defleur-motion/scripts/caption_layer.py", "b096a9d36f04ef71ba3779e5bc9acffaa88412d7fbcf8d209c4188190ac413fe"),
    "test_audio_gate": ("skills/defleur-audio/scripts/test_audio_gate.py", "09bba3c7ed527149aba5d9d034e8d8fe210ce230eacf9c961302c01b2707b177"),
}
DEFAULTS = ("defaults/neutral-preset.json", "d4992d28e6b0219778e377d696bd6a8db8d5db90bce64f87784d2a4e38f47072")

DOCS = {
    "notice": "NOTICE", "readme": "README.md", "setup": "SETUP.md", "neutral-preset": "defaults/neutral-preset.json",
    "defleur-edit": "skills/defleur-edit/SKILL.md", "defleur-edit-contract": "skills/defleur-edit/references/project-contract.md",
    "defleur-audio": "skills/defleur-audio/SKILL.md", "defleur-audio-contract": "skills/defleur-audio/references/audio-contract.md",
    "defleur-motion": "skills/defleur-motion/SKILL.md", "defleur-motion-contract": "skills/defleur-motion/references/motion-contract.md",
}

# Whisper checkpoints openai-whisper/stable-ts can load for align(); downloaded on first use into /data/models.
ALIGN_MODELS = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v3-turbo", "turbo", "large-v3"}
DEFAULT_ALIGN_MODEL = "base"
LANG = re.compile(r"^[a-z]{2,3}$")
ID = re.compile(r"^[a-f0-9]{32}$")

# stage -> (wall seconds, description)
STAGES = {
    "source-audio": (1800, "probe_source.py + 48 kHz PCM s16 source.wav decode"),
    "resolve-preset": (60, "preset.py over neutral defaults + client owner/project JSON"),
    "preflight": (60, "preflight.py dependency/language check"),
    "asr": (5400, "Transcriber app -> asr.py receipt schema"),
    "align": (5400, "align.py (stable-ts, local CPU)"),
    "acoustic-ctc": (300, "acoustic_ctc_window.py (needs VIDEO_CTC_MODEL_DIR)"),
    "pcm-assemble": (900, "assemble_pcm.py -> edited.wav + edit-map.json"),
    "speech-cut-audit": (2400, "speech_cut_audit.py per-edge waveform + spectrogram + keep/drop coverage"),
    "acoustic-scan": (2400, "scan_windows.py full-coverage edited windows (app-original)"),
    "dialogue-gate": (900, "audio-gate.json receipt + audio_gate.py --stage dialogue"),
    "validate-project": (60, "validate_project.py on client planning records"),
    "face-crop": (1800, "face_audit.py (app-original, OpenCV YuNet) -> fixed per-setup crop-ledger.json + face audit receipts; optional per-segment speaker targets"),
    "motion-capture": (3600, "James' capture.cjs (adapted: shared Browser app) smoke/proof capture of the submitted HTML/SVG/GSAP composition + contact sheet"),
    "final-render": (14400, "live frames (final_render.py) or full motion capture (capture.cjs via the Browser app) + James' caption_layer.py/encode.py + encode.py --verify-only + decoded-pixel checks"),
    "delivery-gate": (900, "delivery audio-gate.json receipt + audio_gate.py --stage delivery"),
}


def deadline_for(stage):
    return STAGES.get(stage, (180, ""))[0]


def sha(path):
    import hashlib
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def helper(name):
    rel, expected = HELPERS[name]
    root = UPSTREAM_ROOT.resolve()
    file = root / rel
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root):
        raise Rejected(f"Bundled helper missing: {rel}")
    if sha(file) != expected:
        raise Rejected(f"Bundled helper hash mismatch: {rel}")
    return file


def doc(name):
    rel = DOCS.get(name)
    if rel is None:
        raise FileNotFoundError(name)
    path = UPSTREAM_ROOT / rel
    if name == "notice" and not path.is_file():
        path = APP_ROOT / "NOTICE"  # source checkout; the image copies NOTICE into /opt/defleur
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(name)
    return path


def ctc_dir():
    value = os.environ.get("VIDEO_CTC_MODEL_DIR", "").strip()
    if not value:
        return None
    path = Path(value)
    return path if all((path / n).is_file() for n in ("model.onnx", "vocab.json", "capabilities.json")) else None


def align_model(requested=None):
    model = requested or os.environ.get("VIDEO_ALIGN_MODEL", "").strip() or DEFAULT_ALIGN_MODEL
    if model not in ALIGN_MODELS:
        raise Rejected(f"alignment model must be one of {sorted(ALIGN_MODELS)}")
    return model


def capabilities(probe_transcriber=True):
    helpers = {}
    for name in HELPERS:
        try:
            helpers[name] = {"available": True, "sha256": HELPERS[name][1]}
        except Rejected as e:  # pragma: no cover
            helpers[name] = {"available": False, "reason": str(e)}
        try:
            helper(name)
        except Rejected as e:
            helpers[name] = {"available": False, "reason": str(e)}
    model = align_model()
    cached = MODELS_DIR / "whisper" / (("large-v3-turbo" if model == "turbo" else model) + ".pt")
    return {
        "operator": "Hermes (or any HTTP client) makes every editorial decision; the app never calls an LLM",
        "bundle": {"root": str(UPSTREAM_ROOT), "upstream_commit": "30768288eb1308b18216a5df5eb4648fbce3e55b", "license": "MIT (declared in plugin.json)",
                   "docs": sorted(DOCS)},
        "stages": {k: v[1] for k, v in STAGES.items()}, "stage_wall_seconds": {k: v[0] for k, v in STAGES.items()},
        "helpers": helpers,
        "transcriber": transcriber.status() if probe_transcriber else {"probe": "skipped"},
        "alignment": {"engine": "stable-ts 2.19.1 + openai-whisper on CPU torch", "model": model, "configurable": "VIDEO_ALIGN_MODEL or request 'model'",
                      "allowed_models": sorted(ALIGN_MODELS), "cache": str(MODELS_DIR / "whisper"), "cached": cached.is_file()},
        "acoustic_ctc": {"available": ctc_dir() is not None,
                         "reason": None if ctc_dir() else "No CTC model bundle supplied (set VIDEO_CTC_MODEL_DIR to a directory with model.onnx, vocab.json, capabilities.json)"},
        "piece_1_complete": True,
        "piece_2_complete": True,
        "face_model": {"path": str(FACE_MODEL), "sha256": FACE_MODEL_SHA256, "present": FACE_MODEL.is_file()},
        "piece_3_complete": True,
        "motion": {"capture": "James' capture.cjs adapted to the shared Browser app (see NOTICE)", "capture_sha256": sha(CAPTURE_SCRIPT) if CAPTURE_SCRIPT.is_file() else None,
                   "gsap": "defleur/gsap.min.js (GSAP 3.15.0, vendored; Webflow standard no-charge license)", "gsap_present": GSAP.is_file(),
                   "browser": browser_status() if probe_transcriber else {"probe": "skipped"}},
        "resources": resources(),
        "not_built_yet": [],
        "provider_calls": False,
    }


def browser_url():
    from urllib.parse import urlsplit
    url = os.environ.get("BROWSER_URL", "").strip() or DEFAULT_BROWSER_URL
    p = urlsplit(url)
    if p.scheme not in ("http", "ws") or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise Rejected("BROWSER_URL must look like http://browser:9222 (no path, credentials or query)")
    return f"http://{p.hostname}:{p.port or 80}"


def browser_status(timeout=4):
    """Is the shared Browser app reachable? (Chrome needs an IP Host header, so resolve first.)"""
    import socket
    import urllib.request
    try:
        url = browser_url()
    except Rejected as e:
        return {"reachable": False, "url": os.environ.get("BROWSER_URL", ""), "error": str(e), "fix": "Set BROWSER_URL to http://browser:9222 in this app's settings."}
    from urllib.parse import urlsplit
    p = urlsplit(url)
    try:
        ip = socket.getaddrinfo(p.hostname, p.port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with urllib.request.urlopen(f"http://{ip}:{p.port}/json/version", timeout=timeout) as r:
            v = json.loads(r.read())
        return {"reachable": True, "url": url, "browser": v.get("Browser"), "protocol": v.get("Protocol-Version")}
    except Exception as e:  # noqa: BLE001 - report any failure plainly
        return {"reachable": False, "url": url, "error": f"{type(e).__name__}: {str(e)[:160]}",
                "fix": BROWSER_HINT, "needed_for": "motion graphics only; render_final without a motion composition works without it"}


def _cgroup(name):
    try:
        v = Path("/sys/fs/cgroup/" + name).read_text().strip()
        return None if v == "max" else int(v)
    except (OSError, ValueError):
        return None


def _anon_memory():
    """Non-reclaimable app memory (anon); memory.current also counts page cache, which the kernel drops under pressure."""
    try:
        for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines():
            k, v = line.split()
            if k == "anon":
                return int(v)
    except (OSError, ValueError):
        pass
    return None


def resources():
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    data = Path(os.environ.get("VIDEO_DATA_DIR", "/data"))
    disk = shutil.disk_usage(data if data.is_dir() else "/")
    return {"host_ram_bytes": mem.get("MemTotal"), "host_ram_available_bytes": mem.get("MemAvailable"),
            "app_memory_limit_bytes": _cgroup("memory.max"), "app_memory_in_use_bytes": _cgroup("memory.current"),
            "cpus": os.cpu_count(), "data_disk_free_bytes": disk.free, "data_disk_total_bytes": disk.total,
            "per_job_estimates": {
                "final_render_disk_bytes_per_output_second_at_30fps": 30 * FRAME_BYTES * 2,
                "final_render_disk_bytes_5min_output_30fps": int(300 * 30 * FRAME_BYTES * 2 + 1024**3),
                "memory_peak_note": "Measured app peak on a 3-minute 1080p source is reported in RELEASE.md; jobs check free memory and disk before starting.",
                "upload_normalize_disk": "about 2x the upload size while converting HEVC/VFR/4K"}}


def ensure_resources(frames, label, memory_bytes=1536 * 1024**2):
    need = int(frames * FRAME_BYTES * 1.25) + int(os.environ.get("VIDEO_DISK_RESERVE_MB", "1024")) * 1024**2
    free = shutil.disk_usage(Path(os.environ.get("VIDEO_DATA_DIR", "/data")) if Path(os.environ.get("VIDEO_DATA_DIR", "/data")).is_dir() else "/").free
    if free < need:
        raise Rejected(f"{label} needs about {need // 1024**2} MiB free disk for {frames} frames; {free // 1024**2} MiB free. Delete old projects (delete_project) or free disk.")
    limit, used = _cgroup("memory.max"), _anon_memory()
    if limit and used is not None and limit - used < memory_bytes:
        raise Rejected(f"{label} needs about {memory_bytes // 1024**2} MiB of free app memory; {(limit - used) // 1024**2} MiB free under the app limit. Wait for other jobs or raise the app memory limit.")


# ---------- validation ----------

def _obj(value, keys, optional=()):
    if not isinstance(value, dict) or not set(keys) <= set(value) or set(value) - set(keys) - set(optional):
        raise Rejected(f"expected object with {sorted(keys)}" + (f" and optional {sorted(optional)}" if optional else ""))
    return value


def _num(v, label):
    if type(v) not in (int, float) or not math.isfinite(v):
        raise Rejected(f"{label} must be a finite number")
    return float(v)


def _text(v, label, limit=2000, required=True):
    if not isinstance(v, str) or (required and not v.strip()) or len(v) > limit:
        raise Rejected(f"{label} must be a nonempty string up to {limit} chars")
    return v


def _lang(v, allow_auto=False):
    if allow_auto and v == "auto":
        return v
    if not isinstance(v, str) or not LANG.fullmatch(v):
        raise Rejected("language must be a lowercase ISO 639 code like 'en'" + (" or 'auto'" if allow_auto else ""))
    return v


def _segments(rows, duration):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 400:
        raise Rejected("segments must be a list of 1..400 retained spans")
    end = 0.0
    for row in rows:
        _obj(row, {"start_s", "end_s", "reason"})
        start, stop = _num(row["start_s"], "start_s"), _num(row["end_s"], "end_s")
        if not end <= start < stop <= duration + 1e-6 or stop - start < 0.01:
            raise Rejected("segments must be ordered, non-overlapping, inside the source and at least 10 ms")
        _text(row["reason"], "segment reason", 1000)
        end = stop
    return rows


def _framing(value, segments):
    _obj(value, set(), {"targets", "new_setup_at"})
    targets = value.get("targets", {})
    if not isinstance(targets, dict) or len(targets) > 400:
        raise Rejected("framing.targets must map kept-segment index -> largest|left|right|center")
    for k, v in targets.items():
        if not str(k).isdigit() or not 0 <= int(k) < segments or v not in ("largest", "left", "right", "center"):
            raise Rejected(f"framing.targets: segment index 0..{segments - 1} -> largest|left|right|center")
    breaks = value.get("new_setup_at", [])
    if not isinstance(breaks, list) or any(type(b) is not int or not 0 < b < segments for b in breaks):
        raise Rejected(f"framing.new_setup_at must list kept-segment indexes 1..{segments - 1}")


def _render_refs(value, lookup):
    lookup(value["assemble_job"], {"pcm-assemble"})
    crop, _ = lookup(value["crop_job"], {"face-crop"})
    asr, _ = lookup(value["edited_asr_job"], {"asr"})
    if crop["result"]["summary"]["assemble_job"] != value["assemble_job"] or asr["result"]["summary"]["audio_job"] != value["assemble_job"]:
        raise Rejected("crop_job and edited_asr_job must both come from this assemble_job")
    if "preset_job" in value:
        lookup(value["preset_job"], {"resolve-preset"})


def validate(stage, value, metadata, lookup):
    """Fast 422 checks at submit time. lookup(jid, stages) -> (job, dir) or raises."""
    if stage not in STAGES or not isinstance(value, dict):
        raise Rejected(f"Unknown workflow stage or invalid body; stages: {sorted(STAGES)}")
    if stage == "source-audio":
        if value:
            raise Rejected("source-audio takes an empty object")
    elif stage == "resolve-preset":
        if set(value) - {"owner", "project"}:
            raise Rejected("preset stage accepts owner/project JSON objects, not file paths")
        for preset in value.values():
            if not isinstance(preset, dict) or preset.get("version", 1) != 1:
                raise Rejected("Unsupported preset JSON")
            caption = preset.get("caption", {})
            font = caption.get("font_path", "") if isinstance(caption, dict) else None
            if not isinstance(font, str) or (font and (not font.startswith(FONT_DIR) or ".." in font or not Path(font).is_file())):
                raise Rejected(f"caption.font_path must be empty (auto) or an installed font under {FONT_DIR}")
    elif stage == "preflight":
        _obj(value, {"language"})
        _lang(value["language"])
    elif stage == "asr":
        _obj(value, {"audio_job", "language"})
        _lang(value["language"], allow_auto=True)
        lookup(value["audio_job"], {"source-audio", "pcm-assemble", "final-render"})
    elif stage == "align":
        _obj(value, {"asr_job", "language"}, {"model"})
        _lang(value["language"])
        align_model(value.get("model"))
        job, _ = lookup(value["asr_job"], {"asr"})
        detected = job["result"].get("summary", {}).get("language_detected")
        if detected and detected != value["language"]:
            raise Rejected(f"ASR detected {detected!r}; align.py refuses a different language {value['language']!r}")
    elif stage == "acoustic-ctc":
        _obj(value, {"asr_job", "start_s", "end_s", "language"})
        if ctc_dir() is None:
            raise Rejected("acoustic_ctc_window unavailable: no CTC model bundle supplied (VIDEO_CTC_MODEL_DIR)")
        _lang(value["language"])
        start, end = _num(value["start_s"], "start_s"), _num(value["end_s"], "end_s")
        if not 0 <= start < end or end - start > 20:
            raise Rejected("CTC window must be 0 <= start < end and at most 20 s")
        lookup(value["asr_job"], {"asr"})
    elif stage == "pcm-assemble":
        _obj(value, {"audio_job", "segments"})
        job, _ = lookup(value["audio_job"], {"source-audio"})
        _segments(value["segments"], job["result"]["summary"]["duration_s"])
        if not job["result"]["summary"]["constant_frame_rate"]:
            raise Rejected("assemble_pcm.py needs a CFR source; this source requires a PTS picture ledger (not built)")
    elif stage == "speech-cut-audit":
        _obj(value, {"assemble_job", "regions"}, {"baseline_job"})
        lookup(value["assemble_job"], {"pcm-assemble"})
        if "baseline_job" in value:
            lookup(value["baseline_job"], {"pcm-assemble"})
        rows = value["regions"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
            raise Rejected("regions must be a list of 1..2000 keep/drop regions")
        for row in rows:
            _obj(row, {"mode", "start_s", "end_s"}, {"name", "word", "reason"})
            if row["mode"] not in ("keep", "drop"):
                raise Rejected("region mode must be keep or drop")
            if _num(row["start_s"], "start_s") >= _num(row["end_s"], "end_s"):
                raise Rejected("region start must precede end")
            for k in ("name", "word", "reason"):
                if k in row:
                    _text(row[k], k, 500)
    elif stage == "acoustic-scan":
        _obj(value, {"assemble_job"}, {"window_s"})
        lookup(value["assemble_job"], {"pcm-assemble", "final-render"})
        if "window_s" in value and not 1 <= _num(value["window_s"], "window_s") <= 20:
            raise Rejected("window_s must be 1..20")
    elif stage == "dialogue-gate":
        _obj(value, {"assemble_job", "audit_job", "scan_job", "filler_review", "acoustic_review", "reviewed_edges"}, {"edited_asr_job", "repair_of"})
        assemble, _ = lookup(value["assemble_job"], {"pcm-assemble"})
        audit, _ = lookup(value["audit_job"], {"speech-cut-audit"})
        scan, _ = lookup(value["scan_job"], {"acoustic-scan"})
        if audit["result"]["summary"]["assemble_job"] != value["assemble_job"] or scan["result"]["summary"]["assemble_job"] != value["assemble_job"]:
            raise Rejected("audit_job and scan_job must both come from assemble_job")
        if "edited_asr_job" in value:
            asr, _ = lookup(value["edited_asr_job"], {"asr"})
            if asr["result"]["summary"]["audio_job"] != value["assemble_job"]:
                raise Rejected("edited_asr_job must transcribe assemble_job's edited.wav")
        if "repair_of" in value:
            _text(value["repair_of"], "repair_of", 200)
        filler = value["filler_review"]
        if not isinstance(filler, dict) or len(json.dumps(filler)) > 200000:
            raise Rejected("filler_review must be an object")
        rows = value["acoustic_review"]
        windows = scan["result"]["summary"]["windows"]
        if not isinstance(rows, list) or not all(isinstance(r, dict) and type(r.get("window")) is int for r in rows) \
                or sorted(r["window"] for r in rows) != list(range(windows)):
            raise Rejected(f"acoustic_review needs exactly one {{window, findings}} row for each of the {windows} scan windows")
        for row in rows:
            _obj(row, {"window", "findings"})
            _text(row["findings"], "window findings", 2000)
        edges = value["reviewed_edges"]
        if not isinstance(edges, list) or len(edges) > 2000:
            raise Rejected("reviewed_edges must be a list")
        for edge in edges:
            _obj(edge, {"segment", "edge", "decision", "findings"})
            if type(edge["segment"]) is not int or edge["edge"] not in ("start", "end") or not isinstance(edge["decision"], str):
                raise Rejected("reviewed edge needs integer segment, edge start|end, decision")
            _text(edge["findings"], "edge findings", 2000, required=False)
    elif stage == "face-crop":
        _obj(value, {"assemble_job"}, {"framing"})
        asm, _ = lookup(value["assemble_job"], {"pcm-assemble"})
        if "framing" in value:
            _framing(value["framing"], asm["result"]["summary"]["segments"])
    elif stage == "motion-capture":
        _obj(value, {"assemble_job", "crop_job", "edited_asr_job", "mode", "composition_sha256"})
        _render_refs(value, lookup)
        if value["mode"] not in ("smoke", "proof"):
            raise Rejected("motion-capture mode must be smoke or proof (full capture runs inside final-render)")
    elif stage == "final-render":
        _obj(value, {"assemble_job", "crop_job", "edited_asr_job"}, {"preset_job", "proof_job"})
        _render_refs(value, lookup)
        if "proof_job" in value:
            proof, _ = lookup(value["proof_job"], {"motion-capture"})
            ps = proof["result"]["summary"]
            if ps["mode"] != "proof" or not ps["pass"] or ps["crop_job"] != value["crop_job"] or ps["assemble_job"] != value["assemble_job"]:
                raise Rejected("proof_job must be a passing proof capture of this assemble_job and crop_job")
    elif stage == "delivery-gate":
        _obj(value, {"render_job", "final_asr_job", "final_scan_job", "dialogue_gate_job"}, {"acoustic_review"})
        render, _ = lookup(value["render_job"], {"final-render"})
        gate, _ = lookup(value["dialogue_gate_job"], {"dialogue-gate"})
        asr, _ = lookup(value["final_asr_job"], {"asr"})
        scan, _ = lookup(value["final_scan_job"], {"acoustic-scan"})
        if asr["result"]["summary"]["audio_job"] != value["render_job"] or scan["result"]["summary"]["assemble_job"] != value["render_job"]:
            raise Rejected("final_asr_job and final_scan_job must both read this render_job's decoded final audio")
        if gate["plan"]["input"]["assemble_job"] != render["plan"]["input"]["assemble_job"]:
            raise Rejected("dialogue_gate_job and render_job must come from the same assemble_job")
        rows = value.get("acoustic_review")
        if rows is not None:
            if not isinstance(rows, list) or len(rows) > 2000:
                raise Rejected("acoustic_review must be a list of {window, findings}")
            for row in rows:
                _obj(row, {"window", "findings"})
                _text(row["findings"], "window findings", 2000)
    elif stage == "validate-project":
        _obj(value, {"locked_timeline", "visual_plan", "crop_ledger"}, {"pts_picture_ledger"})
        if not all(isinstance(v, dict) for v in value.values()):
            raise Rejected("planning records must be JSON objects")
    return value


# ---------- execution ----------

class Ctx:
    def __init__(self, root, native, lookup, deadline):
        self.root, self.native, self.lookup, self.deadline = root, native, lookup, deadline
        self.scratch = root.with_suffix(".tmp")
        self.used = {}

    def env(self):
        self.scratch.mkdir(mode=0o700, exist_ok=True)
        return {"HOME": str(self.scratch), "MPLCONFIGDIR": str(self.scratch / "mpl"), "TMPDIR": str(self.scratch),
                "XDG_CACHE_HOME": str(MODELS_DIR), "TORCH_HOME": str(MODELS_DIR / "torch"),
                "NUMBA_CACHE_DIR": str(self.scratch / "numba"), "PYTHONUNBUFFERED": "1"}

    def run(self, name, args, timeout, check=True, flags=("-I",), **kw):
        script = helper(name)
        self.used[name] = HELPERS[name][1]
        return self.native([HELPER_PYTHON, *flags, script, *args], timeout=timeout, cwd=self.root,
                           env_extra=self.env(), check=check, explain=True, **kw)

    def app(self, script, args, timeout, **kw):
        path = APP_ROOT / script
        self.used[f"{script} (app-original)"] = sha(path)
        return self.native([HELPER_PYTHON, "-I", path, *args], timeout=timeout, cwd=self.root, env_extra=self.env(),
                           explain=True, **kw)

    def write(self, name, obj):
        (self.root / name).write_text(json.dumps(obj, allow_nan=False, indent=2))

    def ref(self, jid, stages, name, dest=None):
        """Verified consumption of an earlier stage's artifact (hash re-checked)."""
        job, folder = self.lookup(jid, stages)
        item = next((a for a in job["result"]["artifacts"] if a["name"] == name), None)
        path = folder / name
        if item is None or not path.is_file() or path.is_symlink() or sha(path) != item["sha256"]:
            raise Rejected(f"artifact {name} of job {jid} is missing or changed")
        if dest:
            target = self.root / dest
            try:
                os.link(path, target)
            except OSError:
                shutil.copyfile(path, target)
            return target, job
        return path, job


def _tail(data):
    text = data.decode(errors="replace").strip() if isinstance(data, bytes) else str(data)
    return text[-1500:]


def run(stage, value, source, root, metadata, native, lookup, deadline, input_args):
    root.mkdir(mode=0o700)
    ctx = Ctx(root, native, lookup, deadline)
    ctx.input_args = input_args
    try:
        summary = STAGE_RUNNERS[stage](ctx, value, source, metadata)
    finally:
        shutil.rmtree(ctx.scratch, ignore_errors=True)
    artifacts = []
    for path in sorted(root.iterdir()):
        if path.suffix not in {".json", ".wav", ".png", ".mp4"} or not path.is_file() or path.is_symlink():
            raise Rejected(f"Unexpected helper output: {path.name}")
        artifacts.append({"name": path.name, "sha256": sha(path), "bytes": path.stat().st_size,
                          "content_type": {".wav": "audio/wav", ".png": "image/png", ".mp4": "video/mp4"}.get(path.suffix, "application/json")})
    return {"stage": stage, "helpers": ctx.used, "helper_sha256": next(iter(ctx.used.values()), None),
            "summary": summary, "artifacts": artifacts,
            "scope": "Real mechanics with hash-bound artifacts. Evidence for operator review; not human listening, not delivery approval."}


def _source_audio(ctx, value, source, metadata):
    ctx.write("request.json", {"stage": "source-audio", "source_sha256": metadata["source_sha256"]})
    link = ctx.root / "source.mp4"
    # probe_source.py takes a path; give it the server-owned upload (already structure-checked at upload).
    os.symlink(source, link)
    try:
        ctx.run("probe_source", [link, ctx.root / "source-probe.json"], timeout=280, cpu=600, file_limit=64 * 1024 * 1024)
    finally:
        link.unlink()
    probe = json.loads((ctx.root / "source-probe.json").read_text())
    ctx.native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-n", *ctx.input_args(), "-map", "0:a:0", "-vn",
                "-c:a", "pcm_s16le", "-ar", "48000", "-threads", "1", ctx.root / "source.wav"], source,
               timeout=200, file_limit=512 * 1024 * 1024, cpu=300)
    with wave.open(str(ctx.root / "source.wav")) as pcm:
        info = {"samples": pcm.getnframes(), "rate": pcm.getframerate(), "channels": pcm.getnchannels(), "sample_width": pcm.getsampwidth()}
    if info["sample_width"] != 2 or not info["samples"]:
        raise Rejected("PCM decode produced no s16 samples")
    ctx.write("pcm-source.json", {**info, "sha256": sha(ctx.root / "source.wav"), "codec": "pcm_s16le", "lossy_intermediate": False})
    ctx.app("energy.py", [ctx.root / "source.wav", ctx.root / "energy.json"], timeout=280, cpu=600, as_limit=2 * 1024**3, nofile=64)
    frames = probe["video"].get("nb_read_frames")
    return {"duration_s": info["samples"] / info["rate"], "sample_rate": info["rate"], "channels": info["channels"],
            "fps": probe["fps"]["r_frame_rate"], "frames": int(frames) if frames else None,
            "constant_frame_rate": bool(probe["fps"]["constant_frame_rate"]), "mapping_support": probe["mapping_support"]}


def _resolve_preset(ctx, value, source, metadata):
    script = helper("preset")
    defaults = UPSTREAM_ROOT / DEFAULTS[0]
    if defaults.is_symlink() or sha(defaults) != DEFAULTS[1]:
        raise Rejected("Bundled preset defaults mismatch")
    args = [ctx.root / "preset-resolution.json", "--defaults", defaults]
    for label in ("owner", "project"):
        if label in value:
            ctx.write(label + "-preset.json", value[label])
            args += ["--" + label, ctx.root / (label + "-preset.json")]
    del script
    ctx.run("preset", args, timeout=30)
    resolved = json.loads((ctx.root / "preset-resolution.json").read_text())
    return {"font_path": resolved["preset"]["caption"]["font_path"], "sources": len(resolved["sources"])}


EXPLAIN_MISSING = {
    "faster_whisper": "Replaced by the shared Transcriber app (asr stage); not bundled by design.",
    "node": "Bundled for motion capture (capture.cjs via the shared Browser app); preflight's check looks for it on PATH only.",
}


def _preflight(ctx, value, source, metadata):
    args = ["--source", source, "--language", value["language"]]
    if ctx_dir := ctc_dir():
        args += ["--acoustic-model-dir", ctx_dir]
    code, out, err = ctx.run("preflight", args, timeout=30, check=False)
    try:
        report = json.loads(out)
    except ValueError:
        raise Rejected("preflight.py failed: " + _tail(err))
    ctx.write("preflight.json", report)
    t = transcriber.status()
    missing = report.get("missing", [])
    notes = {m: EXPLAIN_MISSING.get(m, "Required for piece 1; this is a real gap.") for m in missing}
    piece1_missing = [m for m in missing if m not in EXPLAIN_MISSING]
    ctx.write("preflight-app-notes.json", {"helper_exit_code": code, "explanations": notes, "transcriber": t,
                                            "piece_1_blockers": piece1_missing + ([] if t.get("model_installed") else ["transcriber model"])})
    return {"helper_passed": report.get("passed"), "missing": missing, "piece_1_blockers": piece1_missing,
            "transcriber_ready": bool(t.get("model_installed"))}


def _asr(ctx, value, source, metadata):
    job, _ = ctx.lookup(value["audio_job"], {"source-audio", "pcm-assemble", "final-render"})
    name = {"source-audio": "source.wav", "pcm-assemble": "edited.wav", "final-render": "final-audio.wav"}[job["result"]["stage"]]
    wav, _ = ctx.ref(value["audio_job"], {"source-audio", "pcm-assemble", "final-render"}, name)
    ctx.native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-n", "-i", wav, "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", "-threads", "1", ctx.root / "asr-input.wav"], timeout=120, file_limit=256 * 1024 * 1024, cpu=200)
    receipt, raw = transcriber.transcribe(ctx.root / "asr-input.wav", value["language"], ctx.deadline)
    receipt["provenance"]["input_artifact"] = {"job": value["audio_job"], "name": name, "sha256": sha(wav)}
    ctx.write("asr.json", receipt)
    ctx.write("transcriber-response.json", raw)
    ctx.used["asr.py (schema only; local faster-whisper replaced by Transcriber)"] = HELPERS["asr"][1]
    return {"audio_job": value["audio_job"], "audio": name, "words": len(receipt["words"]), "language_detected": receipt["language_detected"],
            "transcriber_model": receipt["model_resolved"], "seconds": receipt["seconds"], "text": raw.get("text", "")[:2000]}


def _align(ctx, value, source, metadata):
    model = align_model(value.get("model"))
    audio, _ = ctx.ref(value["asr_job"], {"asr"}, "asr-input.wav", "align-input.wav")
    asr, _ = ctx.ref(value["asr_job"], {"asr"}, "asr.json", "asr.json")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = MODELS_DIR / "whisper" / (("large-v3-turbo" if model == "turbo" else model) + ".pt")
    cached = checkpoint.is_file()
    started = time.monotonic()
    threads = os.environ.get("VIDEO_ALIGN_THREADS", "2")
    ctx.run("align", [audio, asr, ctx.root / "aligned.json", "--language", value["language"], "--model", model, "--device", "cpu"],
            timeout=1780, cpu=3600, as_limit=16 * 1024**3, file_limit=4 * 1024**3, nofile=512, max_log=4 * 1024 * 1024,
            threads=threads)
    aligned = json.loads((ctx.root / "aligned.json").read_text())
    words = [w for s in aligned.get("segments", []) for w in s.get("words", [])]
    receipt = {"engine": "stable-ts (stable_whisper) via align.py", "model": model, "checkpoint": str(checkpoint),
               "checkpoint_sha256": sha(checkpoint) if checkpoint.is_file() else None,
               "checkpoint_downloaded_this_job": not cached, "device": "cpu", "torch_threads": threads,
               "language": value["language"], "aligned_words": len(words), "seconds": round(time.monotonic() - started, 3),
               "asr_job": value["asr_job"], "limitation": "Word timings are navigation seeds, not cut instructions."}
    ctx.write("align-receipt.json", receipt)
    return {k: receipt[k] for k in ("model", "aligned_words", "seconds", "checkpoint_downloaded_this_job", "language")}


def _ctc(ctx, value, source, metadata):
    audio, _ = ctx.ref(value["asr_job"], {"asr"}, "asr-input.wav", "ctc-input.wav")
    ctx.run("acoustic_ctc_window", ["--wav", audio, "--start", str(value["start_s"]), "--end", str(value["end_s"]),
            "--language", value["language"], "--model-dir", ctc_dir(), "--out", ctx.root / "ctc-window.json"],
            timeout=280, cpu=600, as_limit=8 * 1024**3, nofile=256)
    data = json.loads((ctx.root / "ctc-window.json").read_text())
    return {"characters": len(data.get("characters", [])), "greedy_text": data.get("greedy_text", "")[:500]}


def _pcm_assemble(ctx, value, source, metadata):
    job, _ = ctx.lookup(value["audio_job"], {"source-audio"})
    s = job["result"]["summary"]
    if not s["constant_frame_rate"] or not s["frames"]:
        raise Rejected("assemble_pcm.py needs a CFR source with a probed frame count")
    ctx.ref(value["audio_job"], {"source-audio"}, "source.wav", "source.wav")
    ctx.write("edit-plan.json", {"segments": value["segments"]})
    ctx.run("assemble_pcm", [ctx.root, "--fps", s["fps"], "--source-frames", str(s["frames"])],
            timeout=280, cpu=600, file_limit=1024 * 1024 * 1024, as_limit=4 * 1024**3)
    mapped = json.loads((ctx.root / "edit-map.json").read_text())
    with wave.open(str(ctx.root / "edited.wav")) as edited:
        if edited.getnframes() != mapped["samples"]:
            raise Rejected("Assembled PCM does not match sample ledger")
    blocks = [{"id": f"segment-{i}", "source_start_s": seg["start_s"], "source_end_s": seg["end_s"]} for i, seg in enumerate(mapped["segments"])]
    ctx.write("blocks.json", {"blocks": blocks, "derived_from": "edit-map.json segments (sample-exact)"})
    return {"audio_job": value["audio_job"], "duration_s": mapped["duration"], "frames": mapped["frames"], "fps": mapped["fps"],
            "segments": len(mapped["segments"]),
            "removed_s": round(s["duration_s"] - mapped["duration"], 6)}


def _speech_cut_audit(ctx, value, source, metadata):
    wav, _ = ctx.ref(value["assemble_job"], {"pcm-assemble"}, "source.wav", "source.wav")
    blocks, _ = ctx.ref(value["assemble_job"], {"pcm-assemble"}, "blocks.json", "blocks.json")
    ctx.write("regions.json", value["regions"])
    args = ["--source-wav", wav, "--manifest", blocks, "--regions", ctx.root / "regions.json", "--output-dir", ctx.root]
    if "baseline_job" in value:
        base, _ = ctx.ref(value["baseline_job"], {"pcm-assemble"}, "blocks.json")
        target = ctx.root / "baseline-blocks.json"
        shutil.copyfile(base, target)
        args += ["--baseline", target]
    code, out, err = ctx.run("speech_cut_audit", args, timeout=580, cpu=1200, as_limit=4 * 1024**3, nofile=256,
                             max_log=8 * 1024 * 1024, check=False)
    if not (ctx.root / "cut-regression.json").is_file():
        raise Rejected("speech_cut_audit.py failed: " + _tail(err))
    receipt = json.loads((ctx.root / "cut-regression.json").read_text())
    return {"assemble_job": value["assemble_job"], "pass": receipt.get("pass") is True, "helper_exit_code": code,
            "edges": len(receipt.get("edges", [])), "failed_regions": [r for r in receipt.get("candidate", []) if not r.get("pass")][:50]}


def _acoustic_scan(ctx, value, source, metadata):
    job, _ = ctx.lookup(value["assemble_job"], {"pcm-assemble", "final-render"})
    name = "final-audio.wav" if job["result"]["stage"] == "final-render" else "edited.wav"
    wav, _ = ctx.ref(value["assemble_job"], {"pcm-assemble", "final-render"}, name, "edited.wav")
    script = APP_ROOT / "scan_windows.py"
    ctx.used["scan_windows.py (app-original)"] = sha(script)
    ctx.native([HELPER_PYTHON, "-I", script, wav, ctx.root, "--window", str(value.get("window_s", 5.0))],
               timeout=580, cwd=ctx.root, env_extra=ctx.env(), cpu=1200, as_limit=4 * 1024**3, nofile=256, explain=True)
    edited_sha = sha(wav)
    (ctx.root / "edited.wav").unlink()  # already bound in the assemble job; keep the scan bundle small
    data = json.loads((ctx.root / "acoustic-windows.json").read_text())
    return {"assemble_job": value["assemble_job"], "audio": name, "windows": len(data["windows"]), "duration_s": data["duration"],
            "edited_wav_sha256": edited_sha}


def _dialogue_gate(ctx, value, source, metadata):
    root = ctx.root
    a = value["assemble_job"]
    ctx.ref(a, {"pcm-assemble"}, "source.wav", "source.wav")
    ctx.ref(a, {"pcm-assemble"}, "edited.wav", "edited.wav")
    ctx.ref(a, {"pcm-assemble"}, "edit-map.json", "edit-map.json")
    ctx.ref(value["audit_job"], {"speech-cut-audit"}, "regions.json", "phonetic-regions.json")
    ctx.ref(value["audit_job"], {"speech-cut-audit"}, "cut-regression.json", "cut-regression.json")
    windows, _ = ctx.ref(value["scan_job"], {"acoustic-scan"}, "acoustic-windows.json")
    scan_rows = json.loads(windows.read_text())["windows"]
    review = {r["window"]: r["findings"] for r in value["acoustic_review"]}
    rows = []
    for w in scan_rows:
        wave_path, _ = ctx.ref(value["scan_job"], {"acoustic-scan"}, w["waveform"])
        spec_path, _ = ctx.ref(value["scan_job"], {"acoustic-scan"}, w["spectrogram"])
        rows.append({"start": w["start"], "end": w["end"], "window": w["index"], "findings": review[w["index"]],
                     "rms_dbfs": w["rms_dbfs"], "waveform_sha256": sha(wave_path), "spectrogram_sha256": sha(spec_path)})
    ctx.write("edited-acoustic-scan.json", rows)
    filler = dict(value["filler_review"])
    if "edited_asr_job" in value:
        ctx.ref(value["edited_asr_job"], {"asr"}, "asr.json", "edited-asr.json")
        filler.setdefault("edited_asr", {"job": value["edited_asr_job"], "sha256": sha(root / "edited-asr.json")})
    ctx.write("filler-review.json", filler)
    edges = []
    for edge in value["reviewed_edges"]:
        item = dict(edge)
        if type(edge["segment"]) is int and edge["edge"] in ("start", "end") and edge["segment"] >= 0:
            for kind in ("waveform", "spectrogram"):
                name = f"{edge['segment']}-{edge['edge']}-{kind}.png"
                try:
                    ctx.ref(value["audit_job"], {"speech-cut-audit"}, name, "edge-" + name)
                    item[f"{kind}_path"] = "edge-" + name
                    item[f"{kind}_sha256"] = sha(root / ("edge-" + name))
                except Rejected:
                    pass  # gate fails closed on the missing image
        edges.append(item)
    receipt: dict = {"version": 3}
    for key, name in [("source", "source.wav"), ("edited", "edited.wav"), ("edit_map", "edit-map.json"),
                      ("phonetic_regions", "phonetic-regions.json"), ("cut_regression", "cut-regression.json"),
                      ("filler_review", "filler-review.json"), ("edited_acoustic_scan", "edited-acoustic-scan.json")]:
        receipt[key] = {"path": name, "sha256": sha(root / name)}
    receipt["reviewed_edges"] = edges
    if "repair_of" in value:
        receipt["repair_of"] = value["repair_of"]
    ctx.write("audio-gate.json", receipt)
    code, out, err = ctx.run("audio_gate", [root, "--stage", "dialogue"], timeout=120, check=False, as_limit=2 * 1024**3)
    result = {"pass": code == 0, "exit_code": code, "stage": "dialogue",
              "output": json.loads(out) if code == 0 else None, "error": None if code == 0 else _tail(err),
              "receipt_sha256": sha(root / "audio-gate.json"),
              "scope": "Evidence completeness and custody per audio_gate.py; not human listening approval."}
    ctx.write("dialogue-gate-result.json", result)
    return {"dialogue_gate_pass": result["pass"], "error": result["error"], "reviewed_edges": len(edges), "scan_windows": len(rows)}


def _validate_project(ctx, value, source, metadata):
    for key, name in [("locked_timeline", "locked-timeline.json"), ("visual_plan", "visual-plan.json"),
                      ("crop_ledger", "crop-ledger.json"), ("pts_picture_ledger", "pts-picture-ledger.json")]:
        if key in value:
            ctx.write(name, value[key])
    code, out, err = ctx.run("validate_project", [ctx.root], timeout=30, check=False)
    result = {"pass": code == 0, "exit_code": code, "output": json.loads(out) if code == 0 else None,
              "error": None if code == 0 else _tail(err).splitlines()[-1] if _tail(err) else "failed"}
    ctx.write("validate-result.json", result)
    return result


def _norm(word):
    return re.sub(r"[^\w']+", "", str(word).lower()).strip("'")


def _words_diff(expected, got, with_fillers=False):
    from editing import diff_words
    lost, added, f_lost, f_added = diff_words([w for w in map(_norm, expected) if w], [w for w in map(_norm, got) if w])
    return (lost, added, f_lost, f_added) if with_fillers else (lost, added)


def _face_model():
    if not FACE_MODEL.is_file() or FACE_MODEL.is_symlink() or sha(FACE_MODEL) != FACE_MODEL_SHA256:
        raise Rejected(f"face model missing or hash mismatch at {FACE_MODEL}")
    return FACE_MODEL


def _caption_style(ctx, value):
    """Resolve James' preset (neutral defaults + optional resolve-preset job) and return its caption block."""
    if "preset_job" in value:
        path, _ = ctx.ref(value["preset_job"], {"resolve-preset"}, "preset-resolution.json", "preset-resolution.json")
    else:
        defaults = UPSTREAM_ROOT / DEFAULTS[0]
        if defaults.is_symlink() or sha(defaults) != DEFAULTS[1]:
            raise Rejected("Bundled preset defaults mismatch")
        ctx.run("preset", [ctx.root / "preset-resolution.json", "--defaults", defaults], timeout=30)
        path = ctx.root / "preset-resolution.json"
    resolved = json.loads(path.read_text())["preset"]
    canvas = resolved.get("video", {}).get("canvas", list(CANVAS))
    if list(canvas) != list(CANVAS):
        raise Rejected("only the 1080x1920 canvas is supported")
    return resolved["caption"]


def _face_crop(ctx, value, source, metadata):
    model = _face_model()
    edit_map, _ = ctx.ref(value["assemble_job"], {"pcm-assemble"}, "edit-map.json", "edit-map.json")
    defaults = json.loads((UPSTREAM_ROOT / DEFAULTS[0]).read_text())
    top = int(defaults["caption"]["safe_rect"][1])
    ctx.used["yunet.onnx (opencv_zoo f12e127, MIT)"] = FACE_MODEL_SHA256
    extra = []
    if value.get("framing"):
        ctx.write("framing.json", value["framing"])
        extra = ["--framing", ctx.root / "framing.json"]
    ctx.app("face_audit.py", [source, edit_map, ctx.root, "--model", model, "--canvas", f"{CANVAS[0]}x{CANVAS[1]}",
                              "--caption-top", str(top), *extra], timeout=1780, cpu=3600, as_limit=4 * 1024**3, nofile=128,
            file_limit=64 * 1024**2, threads="2")
    audit = json.loads((ctx.root / "face-audit.json").read_text())
    return {"assemble_job": value["assemble_job"], "pass": audit["pass"], "setups": audit["setups"], "flags": audit["flags"],
            "samples": audit["samples"], "caption_band_top_px": top}


def _locked_words(asr_words, duration):
    """Edited-audio ASR word timings -> caption words James' caption_layer accepts (ordered, positive)."""
    words, adjusted, last = [], 0, 0.0
    for w in asr_words:
        token = str(w.get("word", "")).strip()
        if not token:
            continue
        start = max(float(w["start"]), last)
        end = min(max(float(w["end"]), start + 0.02), duration)
        if start >= duration - 0.01:
            adjusted += 1
            continue
        if end <= start:
            end = min(duration, start + 0.02)
        adjusted += (start, end) != (float(w["start"]), float(w["end"]))
        words.append({"word": token, "start": round(start, 3), "end": round(end, 3)})
        last = start
    return words, adjusted


def _final_render(ctx, value, source, metadata):
    root = ctx.root
    asm, _ = ctx.lookup(value["assemble_job"], {"pcm-assemble"})
    frames = int(asm["result"]["summary"]["frames"])
    if float(asm["result"]["summary"]["duration_s"]) > MAX_OUTPUT_S:
        raise Rejected(f"edited video is {asm['result']['summary']['duration_s']:.0f} s; the output limit is {MAX_OUTPUT_S:.0f} s")
    use_motion = "proof_job" in value
    ensure_resources(frames * (2 if use_motion else 1), "final-render", memory_bytes=(2560 if use_motion else 1536) * 1024**2)
    edit_map, _ = ctx.ref(value["assemble_job"], {"pcm-assemble"}, "edit-map.json", "edit-map.json")
    ctx.ref(value["assemble_job"], {"pcm-assemble"}, "edited.wav", "edited.wav")
    ctx.ref(value["assemble_job"], {"pcm-assemble"}, "source.wav", "source.wav")
    ledger, _ = ctx.ref(value["crop_job"], {"face-crop"}, "crop-ledger.json", "crop-ledger.json")
    ctx.ref(value["crop_job"], {"face-crop"}, "face-audit.json", "face-audit.json")
    asr, _ = ctx.ref(value["edited_asr_job"], {"asr"}, "asr.json", "edited-asr.json")
    style = _caption_style(ctx, value)
    mapped = json.loads(edit_map.read_text())
    words, adjusted = _locked_words(json.loads(asr.read_text())["words"], float(mapped["duration"]))
    if not words:
        raise Rejected("the edited-audio transcript has no words; captions need at least one")
    ctx.write("caption-style.json", style)
    ctx.write("locked-timeline.json", {"duration": mapped["duration"], "fps": mapped["fps"], "frames": mapped["frames"],
                                       "canvas": list(CANVAS), "words": words, "transcript": " ".join(w["word"] for w in words),
                                       "word_source": "Transcriber ASR of the edited audio (apply_cuts' edited-asr job)",
                                       "timing_adjustments": adjusted})
    work = cap_checks = proof = None
    if use_motion:
        proof, _ = ctx.lookup(value["proof_job"], {"motion-capture"})
        ctx.source = source
        work, st, plan, _m, timeline, _s, _ = _motion_root(ctx, {**value, "composition_sha256": proof["result"]["summary"]["composition_sha256"]}, "full")
        cap = _capture(ctx, work, "full")
        cap_checks = _capture_checks(cap, plan, float(__import__("fractions").Fraction(str(mapped["fps"]))))
        if cap["errors"] or not cap_checks["caption_suppression_matches_plan"] or not cap_checks["insert_mode_declared"]:
            raise Rejected(f"full capture disagrees with the plan: {cap_checks}; page errors: {cap['errors'][:3]}")
        (work / "picture-frames").rename(root / "picture-frames")
        for name in ("capture-full.json", "visual-plan.json", "locked-timeline.json", "base-map.json"):
            shutil.copyfile(work / name, root / name)
        ledger = root / "crop-ledger.json"
        ledger.unlink()
        shutil.copyfile(work / "crop-ledger.json", ledger)
        motion_info = {"composition_sha256": st["composition_sha256"], "proof_job": value["proof_job"], "beats": len(plan["beats"]),
                       "inserts": len(plan.get("inserts", [])), "caption_suppress": plan.get("caption_suppress", []),
                       "capture_seconds": cap["seconds"], "reverse_seek_checked": len(cap["reverse_seek_checked"]),
                       "blocked_requests": cap.get("blocked_requests", []), "browser": browser_status().get("browser")}
    else:
        # No motion composition submitted: an explicit empty plan, so encode.py's suppression check has nothing to allow.
        ctx.write("visual-plan.json", {"beats": [], "caption_suppress": [],
                                       "note": "No HTML/SVG/GSAP motion composition submitted: live footage only, captions never suppressed."})
        ctx.app("final_render.py", ["render", source, edit_map, ledger, root], timeout=3600, cpu=7200, as_limit=4 * 1024**3,
                nofile=128, file_limit=64 * 1024**2, threads="2")
        motion_info = None
    big = dict(timeout=7200, cpu=28800, as_limit=6 * 1024**3, nofile=256, file_limit=8 * 1024**3, max_log=1024 * 1024, threads="2")
    helper("caption_layer")
    ctx.used["caption_layer"] = HELPERS["caption_layer"][1]
    try:
        ctx.run("encode", [root], flags=("-s", "-E"), **big)
        if use_motion:
            ctx.app("motion_frames.py", ["check", root / "final.mp4", root / "base-map.json", root, work / "base_frames",
                                         root / "picture-frames", root / "motion-check.json", "--caption-dir", helper("encode").parent],
                    timeout=1200, cpu=2400, as_limit=6 * 1024**3, nofile=128, file_limit=64 * 1024**2, threads="2")
    finally:
        shutil.rmtree(root / "picture-frames", ignore_errors=True)
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    code, out, err = ctx.run("encode", [root, "--verify-only"], flags=("-s", "-E"), check=False, **big)
    if code:
        raise Rejected("encode.py --verify-only failed: " + _tail(err))
    verified = json.loads(out)
    if not use_motion:
        ctx.app("final_render.py", ["check", source, edit_map, ledger, root, "--caption-dir", helper("encode").parent],
                timeout=1200, cpu=2400, as_limit=4 * 1024**3, nofile=128, file_limit=64 * 1024**2, threads="2")
    with wave.open(str(root / "edited.wav")) as w:
        channels = w.getnchannels()
    ctx.native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-n", "-threads", "1", "-i", root / "final.mp4", "-map", "0:a:0",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", str(channels), root / "final-audio.wav"],
               timeout=300, cpu=600, file_limit=1024**3, as_limit=2 * 1024**3, cwd=root)
    md5 = ctx.native(["/usr/bin/ffmpeg", "-v", "error", "-xerror", "-threads", "1", "-i", root / "final.mp4", "-map", "0:v:0",
                      "-f", "framemd5", "-"], timeout=900, cpu=1800, as_limit=2 * 1024**3, max_log=8 * 1024 * 1024, cwd=root)
    frame_hashes = [line.rsplit(",", 1)[1].strip() for line in md5.decode().splitlines() if line and not line.startswith("#")]
    regions = json.loads(ctx.app("final_render.py", ["regions", root / "source.wav", root / "final-audio.wav", edit_map],
                                 timeout=300, cpu=600, as_limit=4 * 1024**3, nofile=64))
    live = json.loads((root / ("motion-check.json" if use_motion else "live-check.json")).read_text())
    composite = json.loads((root / "caption-composite.json").read_text())
    capture = json.loads((root / "capture-full.json").read_text())
    with wave.open(str(root / "final-audio.wav")) as w:
        final_samples = w.getnframes()
    ctx.write("decoded-final.json", {"final_sha256": sha(root / "final.mp4"), "video_frames_decoded": len(frame_hashes),
                                     "video_framemd5_sha256": __import__("hashlib").sha256("\n".join(frame_hashes).encode()).hexdigest(),
                                     "audio_pcm": "final-audio.wav", "audio_pcm_sha256": sha(root / "final-audio.wav"),
                                     "audio_samples": final_samples, "decoder": "ffmpeg -xerror (framemd5 + PCM s16 48 kHz)"})
    picture_ok = (live["crop_matches_ledger"] and (not use_motion or live["pass"]) and capture["indices"] == list(range(mapped["frames"]))
                  and len(frame_hashes) == mapped["frames"] == verified["frames"])
    integrity = {"full_decode_pass": verified["full_decode_pass"] is True and len(frame_hashes) == mapped["frames"],
                 "caption_bounds_pass": composite.get("caption_bounds_pass") is True and live["caption_band_changes_with_cues"],
                 "picture_map_verified": bool(picture_ok), "source_regions": regions,
                 "media_verification_sha256": sha(root / "media-verification.json"),
                 "picture_check": "motion-check.json" if use_motion else "live-check.json",
                 "picture_check_sha256": sha(root / ("motion-check.json" if use_motion else "live-check.json")),
                 "scope": "encode.py --verify-only, full FFmpeg decode, decoded-pixel crop/caption checks and source-region audio "
                          "correlation; machine evidence, not a viewing or listening review."}
    ctx.write("final-integrity.json", integrity)
    face = json.loads((root / "face-audit.json").read_text())
    return {"assemble_job": value["assemble_job"], "crop_job": value["crop_job"], "width": verified["width"], "height": verified["height"],
            "frames": verified["frames"], "fps": verified["fps"], "duration_s": round(verified["audio_duration"], 3),
            "final_sha256": verified["sha256"], "final_bytes": (root / "final.mp4").stat().st_size,
            "captions": {"cues": live.get("caption_cues"), "words": len(words), "frames_with_cue": live["cue_on_frames"],
                         "font": style["font_path"], "timing_adjustments": adjusted},
            "crop": {"setups": face["setups"], "face_pass": face["pass"], "flags": face["flags"]},
            "checks": {"full_decode": integrity["full_decode_pass"], "caption_bounds_and_band": integrity["caption_bounds_pass"],
                       "crop_matches_ledger": live["crop_matches_ledger"], "picture_map_verified": integrity["picture_map_verified"],
                       "min_source_region_correlation": min(r["correlation"] for r in regions)},
            "motion_layer": "none: no motion composition submitted; live footage only" if not use_motion else {
                **motion_info, "capture_checks": cap_checks,
                "no_motion_outside_planned_windows": live["no_motion_outside_planned_windows"],
                "beats_show_motion": live["beats_show_motion"], "inserts_show_media": live["inserts_show_media"],
                "captions_suppressed_where_declared": live["captions_suppressed_where_declared"], "motion_check_pass": live["pass"]}}


# ---------- motion graphics (James' piece 3) ----------

def _proof_indices(frames, fps, duration, plan):
    """capture.cjs proof frame choice (start, .25 s, end, each beat start/mid/end), with both roundings to be safe."""
    pts = [0, .25, duration - 1 / fps]
    for b in plan["beats"]:
        pts += [b["start"], (b["start"] + b["end"]) / 2, b["end"] - 1 / fps]
    out = set()
    for t in pts:
        for v in (math.floor(t * fps), math.ceil(t * fps)):
            out.add(max(0, min(frames - 1, v)))
    return sorted(out)


def _motion_root(ctx, value, mode):
    """Assemble James' capture project: composition + generated ledger/GSAP + timeline + plan + crop ledger + base frames."""
    from fractions import Fraction
    project = ctx.root.parent
    st = motion.status(project)
    if not st["submitted"]:
        raise Rejected("no motion composition submitted (submit_motion)")
    if "composition_sha256" in value and st["composition_sha256"] != value["composition_sha256"]:
        raise Rejected("the motion composition changed since this capture was requested; capture again")
    if not CAPTURE_SCRIPT.is_file() or not GSAP.is_file():
        raise Rejected("capture runtime missing from the image")
    # Hash-verified reads in place (no links into ctx.root: final-render already linked these names).
    edit_map, _ = ctx.ref(value["assemble_job"], {"pcm-assemble"}, "edit-map.json")
    ledger_path, _ = ctx.ref(value["crop_job"], {"face-crop"}, "crop-ledger.json")
    ctx.ref(value["crop_job"], {"face-crop"}, "face-audit.json")
    asr, _ = ctx.ref(value["edited_asr_job"], {"asr"}, "asr.json")
    mapped = json.loads(edit_map.read_text())
    if float(mapped["duration"]) > MAX_OUTPUT_S:
        raise Rejected(f"edited video is {mapped['duration']:.0f} s; the limit is {MAX_OUTPUT_S:.0f} s of output")
    plan = motion.validate_plan(st["plan"], float(mapped["duration"]), {r["path"] for r in st["files"]})
    fps = float(Fraction(str(mapped["fps"])))
    frames = int(mapped["frames"])
    work = ctx.root.with_suffix(".work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(mode=0o700)
    motion.materialize(project, work)
    (work / "defleur").mkdir(exist_ok=True)
    shutil.copyfile(GSAP, work / "defleur" / "gsap.min.js")
    ids, windows = motion.base_map(mapped, plan)
    (work / "defleur" / "ledger.js").write_text(motion.ledger_js(mapped, plan, ids, CANVAS))
    resolved = ctx.root / "preset-resolution.json"
    style = json.loads(resolved.read_text())["preset"]["caption"] if resolved.is_file() else _caption_style(ctx, value)
    words, adjusted = _locked_words(json.loads(asr.read_text())["words"], float(mapped["duration"]))
    if not words:
        raise Rejected("the edited-audio transcript has no words; captions need at least one")
    timeline = {"duration": mapped["duration"], "fps": mapped["fps"], "frames": frames, "canvas": list(CANVAS), "words": words,
                "transcript": " ".join(w["word"] for w in words), "word_source": "Transcriber ASR of the edited audio (apply_cuts' edited-asr job)",
                "timing_adjustments": adjusted}
    ledger = json.loads(ledger_path.read_text())
    ledger["fullscreen_exceptions"] = [{"start": r["start"], "end": r["end"], "reason": r["reason"], "asset": r["asset"]} for r in plan.get("inserts", [])]
    for name, obj in (("locked-timeline.json", timeline), ("visual-plan.json", plan), ("crop-ledger.json", ledger),
                      ("caption-style.json", style), ("package.json", {"private": True, "description": "DeFleur Video capture project"}),
                      ("base-map.json", {"base_frames": ids, "source_frames": mapped["source_frame_indices"], "inserts": windows})):
        (work / name).write_text(json.dumps(obj, indent=2))
    code, out, err = ctx.run("validate_project", [work], timeout=60, check=False)
    if code:
        raise Rejected("James' validate_project.py rejected the plan: " + _tail(err))
    if mode == "smoke":
        wanted = list(range(min(frames, math.ceil(6 * fps))))
    elif mode == "proof":
        wanted = _proof_indices(frames, fps, float(mapped["duration"]), plan)
    else:
        wanted = list(range(frames))
    (work / "wanted.json").write_text(json.dumps(wanted))
    ctx.app("motion_frames.py", ["base", ctx.source, edit_map, work / "crop-ledger.json", work / "base-map.json", work / "wanted.json",
                                 work, motion.src_dir(project)], timeout=deadline_for("final-render"), cpu=36000,
            as_limit=8 * 1024**3, nofile=256, file_limit=2 * 1024**3, threads="2")
    return work, st, plan, mapped, timeline, style, json.loads(validate_out(out))


def validate_out(out):
    text = out.decode() if isinstance(out, bytes) else out
    return text.strip().splitlines()[-1] if text.strip() else "{}"


def _capture(ctx, work, mode):
    """Run James' capture.cjs (adapted to the shared Browser app) on the capture project."""
    try:
        url = browser_url()
    except Rejected as e:
        raise Rejected(str(e)) from None
    status = browser_status()
    if not status["reachable"]:
        raise Rejected(f"the Browser app is not reachable at {url} ({status.get('error')}). {BROWSER_HINT}")
    helper("capture")  # James' original is bundled unchanged; the adaptation is pinned by hash too
    if sha(CAPTURE_SCRIPT) != CAPTURE_ADAPTED_SHA256:
        raise Rejected("adapted capture.cjs hash mismatch")
    ctx.used["capture"] = HELPERS["capture"][1]
    ctx.used["capture-remote.cjs (James' capture.cjs adapted for the Browser app; see NOTICE)"] = CAPTURE_ADAPTED_SHA256
    started = time.monotonic()
    code, out, err = ctx.native([NODE, CAPTURE_SCRIPT, work, mode], timeout=deadline_for("final-render"), cwd=work, check=False,
                                env_extra={**ctx.env(), "BROWSER_URL": url, "NODE_PATH": str(CAPTURE_DIR / "node_modules"),
                                           "NODE_OPTIONS": "--max-old-space-size=2048"},
                                cpu=36000, as_limit=64 * 1024**3, nofile=1024, file_limit=256 * 1024**2, max_log=1024 * 1024,
                                threads="2", explain=True)
    if code:
        raise Rejected(f"capture.cjs {mode} failed: " + _tail(err))
    cap = json.loads((work / f"capture-{mode}.json").read_text())
    cap["seconds"] = round(time.monotonic() - started, 1)
    return cap


def _capture_checks(cap, plan, fps):
    """Compare the page's declared captionSuppressed/visualMode with the plan, per captured frame."""
    sup = plan.get("caption_suppress", [])
    ins = plan.get("inserts", [])
    inside = lambda t, rows: any(r["start"] <= t < r["end"] for r in rows)
    bad_sup, bad_mode = [], []
    for g in cap["geometry"]:
        t = g["frame"] / fps
        if bool(g.get("captionSuppressed")) != inside(t, sup):
            bad_sup.append(g["frame"])
        if inside(t, ins) and g.get("mode") not in ("fullscreen-insert", "fullscreen", "insert"):
            bad_mode.append(g["frame"])
    return {"caption_suppression_matches_plan": not bad_sup, "suppression_mismatch_frames": bad_sup[:20],
            "insert_mode_declared": not bad_mode, "insert_mode_mismatch_frames": bad_mode[:20]}


def _capture_outputs(ctx, work, mode, fps):
    """Contact sheet + frame thumbnails for the agent. Runs entirely in venv helper children (Pillow is not in the service Python)."""
    frames_dir = work / ("proof-raw" if mode == "proof" else "picture-frames")
    ctx.app("motion_frames.py", ["sheet", work / f"capture-{mode}.json", frames_dir, ctx.root / f"{mode}-sheet.png"],
            timeout=300, cpu=600, as_limit=4 * 1024**3, nofile=128, file_limit=256 * 1024**2)
    # Pillow lives only in the helper venv: thumbnails run as a venv child, never in the service process.
    picks = json.loads(ctx.app("motion_frames.py", ["thumbs", work / f"capture-{mode}.json", frames_dir, ctx.root, "--prefix", mode],
                               timeout=300, cpu=600, as_limit=4 * 1024**3, nofile=128, file_limit=256 * 1024**2))["frames"]
    frames_out = [{"frame": f, "t": round(f / fps, 3), "image": f"{mode}-frame-{f:06d}.png"} for f in picks]
    return frames_out


def _motion_capture(ctx, value, source, metadata):
    ctx.source = source
    from fractions import Fraction
    mode = value["mode"]
    work = None
    try:
        work, st, plan, mapped, timeline, style, _ = _motion_root(ctx, value, mode)
        cap = _capture(ctx, work, mode)
        fps = float(Fraction(str(mapped["fps"])))
        checks = _capture_checks(cap, plan, fps)
        frames_out = _capture_outputs(ctx, work, mode, fps)
        shutil.copyfile(work / f"capture-{mode}.json", ctx.root / f"capture-{mode}.json")
        for name in ("visual-plan.json", "locked-timeline.json", "base-map.json"):
            shutil.copyfile(work / name, ctx.root / name)
        ok = not cap["errors"] and checks["caption_suppression_matches_plan"] and checks["insert_mode_declared"]
        return {"mode": mode, "pass": ok, "frames_captured": cap["frame_count"], "reverse_seek_checked": len(cap["reverse_seek_checked"]),
                "determinism": "every reverse-seek re-render matched its forward capture byte-for-byte (capture.cjs)",
                "page_errors": cap["errors"], "blocked_requests": cap.get("blocked_requests", []), "capture_seconds": cap["seconds"],
                "checks": checks, "frames": frames_out, "sheet": f"{mode}-sheet.png",
                "composition_sha256": st["composition_sha256"], "assemble_job": value["assemble_job"], "crop_job": value["crop_job"],
                "edited_asr_job": value["edited_asr_job"], "beats": len(plan["beats"]), "inserts": len(plan.get("inserts", [])),
                "browser": browser_status().get("browser")}
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


def _delivery_gate(ctx, value, source, metadata):
    root = ctx.root
    gate_job = value["dialogue_gate_job"]
    dialogue, gate_dir = ctx.lookup(gate_job, {"dialogue-gate"})
    base = json.loads((gate_dir / "audio-gate.json").read_text())
    for key in ("source", "edited", "edit_map", "phonetic_regions", "cut_regression", "filler_review", "edited_acoustic_scan"):
        ctx.ref(gate_job, {"dialogue-gate"}, base[key]["path"], base[key]["path"])
    for edge in base["reviewed_edges"]:
        for kind in ("waveform", "spectrogram"):
            if edge.get(f"{kind}_path"):
                ctx.ref(gate_job, {"dialogue-gate"}, edge[f"{kind}_path"], edge[f"{kind}_path"])
    rj = value["render_job"]
    for name in ("final.mp4", "decoded-final.json", "final-integrity.json", "final-audio.wav", "edited-asr.json"):
        ctx.ref(rj, {"final-render"}, name, name)
    ctx.ref(value["final_asr_job"], {"asr"}, "asr.json", "final-asr.json")
    windows, _ = ctx.ref(value["final_scan_job"], {"acoustic-scan"}, "acoustic-windows.json")
    review = {r["window"]: r["findings"] for r in value.get("acoustic_review") or []}
    final_words = json.loads((root / "final-asr.json").read_text())["words"]
    edited_words = json.loads((root / "edited-asr.json").read_text())["words"]
    rows = []
    for w in json.loads(windows.read_text())["windows"]:
        wave_path, _ = ctx.ref(value["final_scan_job"], {"acoustic-scan"}, w["waveform"], "final-" + w["waveform"])
        spec_path, _ = ctx.ref(value["final_scan_job"], {"acoustic-scan"}, w["spectrogram"], "final-" + w["spectrogram"])
        heard = " ".join(x["word"] for x in final_words if x["start"] < w["end"] and x["end"] > w["start"])[:300]
        rows.append({"start": w["start"], "end": w["end"], "window": w["index"], "rms_dbfs": w["rms_dbfs"],
                     "findings": review.get(w["index"]) or (f"Automated: final audio {w['start']:.2f}-{w['end']:.2f} s, RMS "
                                                            f"{w['rms_dbfs'] if w['rms_dbfs'] is not None else 'digital silence'} dBFS; "
                                                            f"final ASR: '{heard}'. Not human listening."),
                     "waveform_sha256": sha(wave_path), "spectrogram_sha256": sha(spec_path)})
    ctx.write("final-acoustic-scan.json", rows)
    lost, added, f_lost, f_added = _words_diff([w["word"] for w in edited_words], [w["word"] for w in final_words], True)
    ctx.write("final-asr-compare.json", {"edited_words": len(edited_words), "final_words": len(final_words),
                                         "words_lost": lost, "words_added": added,
                                         "fillers_in_edited_only": f_lost, "fillers_heard_in_final_only": f_added,
                                         "basis": "Transcriber ASR of the edited WAV vs the decoded final MP4 audio, normalized word sequence diff"})
    receipt = dict(base)
    for key, name in [("final", "final.mp4"), ("decoded_final", "decoded-final.json"), ("final_asr", "final-asr.json"),
                      ("final_acoustic_scan", "final-acoustic-scan.json"), ("final_integrity", "final-integrity.json")]:
        receipt[key] = {"path": name, "sha256": sha(root / name)}
    ctx.write("audio-gate.json", receipt)
    code, out, err = ctx.run("audio_gate", [root, "--stage", "delivery"], timeout=120, check=False, as_limit=2 * 1024**3)
    result = {"pass": code == 0, "exit_code": code, "stage": "delivery", "output": json.loads(out) if code == 0 else None,
              "error": None if code == 0 else _tail(err), "receipt_sha256": sha(root / "audio-gate.json"),
              "words_lost_vs_edited": lost, "words_added_vs_edited": added,
              "scope": "Evidence completeness and custody per audio_gate.py --stage delivery; not human listening approval."}
    ctx.write("delivery-gate-result.json", result)
    del dialogue
    return {"delivery_gate_pass": result["pass"], "error": result["error"], "words_lost_vs_edited": lost,
            "words_added_vs_edited": added, "final_scan_windows": len(rows), "render_job": rj}


STAGE_RUNNERS = {
    "source-audio": _source_audio, "resolve-preset": _resolve_preset, "preflight": _preflight, "asr": _asr,
    "align": _align, "acoustic-ctc": _ctc, "pcm-assemble": _pcm_assemble, "speech-cut-audit": _speech_cut_audit,
    "acoustic-scan": _acoustic_scan, "dialogue-gate": _dialogue_gate, "validate-project": _validate_project,
    "face-crop": _face_crop, "final-render": _final_render, "delivery-gate": _delivery_gate, "motion-capture": _motion_capture,
}
