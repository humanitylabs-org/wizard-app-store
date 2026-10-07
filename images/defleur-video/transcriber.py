"""Adapter for the shared Transcriber app (unmodified Speaches, OpenAI-compatible).

The video image does not bundle faster-whisper. This module sends server-owned
audio to the Transcriber and rewrites its verbose_json answer into exactly the
receipt schema of James DeFleur's asr.py, plus provenance fields.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import time
import uuid
from urllib.parse import quote, urlsplit

from editing import Rejected

DEFAULT_URL = "http://transcriber:8000"
DEFAULT_MODEL = "Systran/faster-whisper-small"
LIMITATION = "ASR can omit fillers or miss words; it is a navigation and scan input, not a complete editorial truth."
INSTALL_HINT = ("Install the Transcriber app from the Wizard App Store on the same Runtipi host "
                "(reachable as http://transcriber:8000), or set TRANSCRIBER_URL in this app's settings.")


def config():
    url = os.environ.get("TRANSCRIBER_URL", "").strip() or DEFAULT_URL
    model = os.environ.get("TRANSCRIBER_MODEL", "").strip() or DEFAULT_MODEL
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Rejected("TRANSCRIBER_URL must be an http(s) origin without credentials, query or fragment")
    return parsed, model, os.environ.get("TRANSCRIBER_API_KEY", "")


def _request(parsed, key, method, path, body=None, headers=None, timeout=30):
    cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    base = parsed.path.rstrip("/")
    c = cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        h = dict(headers or {})
        if key:
            h["Authorization"] = "Bearer " + key
        c.request(method, base + path, body=body, headers=h)
        r = c.getresponse()
        data = r.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise Rejected("Transcriber response exceeds 64 MiB")
        return r.status, data
    finally:
        c.close()


def status():
    """Non-throwing capability probe for /v1/capabilities."""
    try:
        parsed, model, key = config()
    except Rejected as exc:
        return {"configured": False, "error": str(exc)}
    out = {"url_host": parsed.netloc, "model": model, "api_key_set": bool(key)}
    try:
        code, data = _request(parsed, key, "GET", "/v1/models", timeout=3)
        ids = [m.get("id") for m in json.loads(data).get("data", [])] if code == 200 else []
        out.update({"reachable": code == 200, "model_installed": model in ids})
    except (OSError, http.client.HTTPException, ValueError) as exc:
        out.update({"reachable": False, "error": type(exc).__name__})
    return out


def transcribe(wav, language, deadline):
    parsed, model, key = config()
    try:
        code, data = _request(parsed, key, "GET", "/v1/models", timeout=10)
    except (OSError, http.client.HTTPException) as exc:
        raise Rejected(f"Transcriber not reachable at {parsed.netloc} ({type(exc).__name__}). {INSTALL_HINT}")
    if code == 401:
        raise Rejected("Transcriber rejected the request (401): set TRANSCRIBER_API_KEY to the Transcriber's key")
    if code != 200:
        raise Rejected(f"Transcriber at {parsed.netloc} answered HTTP {code} on /v1/models. {INSTALL_HINT}")
    try:
        installed = [m.get("id") for m in json.loads(data).get("data", [])]
    except (ValueError, AttributeError):
        raise Rejected("Transcriber /v1/models returned invalid JSON")
    if model not in installed:
        raise Rejected(f"Transcriber model {model!r} is not installed. Download it once with "
                       f"POST {parsed.scheme}://{parsed.netloc}/v1/models/{model} (or set it as the Transcriber app's "
                       f"startup model), or set TRANSCRIBER_MODEL to one of: {', '.join(i for i in installed if i)[:300]}")
    audio = wav.read_bytes()
    audio_sha = hashlib.sha256(audio).hexdigest()
    boundary = uuid.uuid4().hex
    fields = [("model", model), ("response_format", "verbose_json"), ("temperature", "0"),
              ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
    if language != "auto":
        fields.append(("language", language))
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields)
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
             "Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    remaining = deadline - time.monotonic()
    if remaining < 5:
        raise Rejected("job wall-time limit before transcription")
    requested_at = time.time()
    started = time.monotonic()
    try:
        code, data = _request(parsed, key, "POST", "/v1/audio/transcriptions", body,
                              {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=remaining)
    except (OSError, http.client.HTTPException) as exc:
        raise Rejected(f"Transcriber request failed ({type(exc).__name__}); check the Transcriber app is running")
    seconds = round(time.monotonic() - started, 3)
    if code != 200:
        raise Rejected(f"Transcriber HTTP {code}: {data[:200].decode(errors='replace')}")
    try:
        raw = json.loads(data)
    except ValueError:
        raise Rejected("Transcriber returned invalid JSON")
    words = []
    for w in raw.get("words") or []:
        if not all(isinstance(w.get(k), (int, float)) for k in ("start", "end")) or not isinstance(w.get("word"), str):
            raise Rejected("Transcriber returned malformed word timings")
        words.append({"id": len(words), "word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"]),
                      "probability": w.get("probability")})
    rows = []
    for s in raw.get("segments") or []:
        start, end = float(s.get("start", 0)), float(s.get("end", 0))
        rows.append({"start": start, "end": end, "text": s.get("text", ""), "words": []})
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        target = next((r for r in rows if r["start"] <= mid <= r["end"]), None) or \
            min(rows, key=lambda r: min(abs(r["start"] - mid), abs(r["end"] - mid)), default=None)
        if target is not None:
            target["words"].append(w)
    receipt = {
        "model_requested": model, "model_resolved": model,
        "device": "remote: Transcriber app (Speaches CPU)", "compute_type": "set by the Transcriber app (store default int8)",
        "language_requested": language, "language_detected": raw.get("language"),
        "language_probability": raw.get("language_probability"),
        "duration": raw.get("duration"), "words": words, "segments": rows, "seconds": seconds,
        "limitation": LIMITATION + " Speaches verbose_json does not report language probability; null means not reported, not zero.",
        "provenance": {"transcriber_url_host": parsed.netloc, "speaches_model_id": model, "request_time_unix": requested_at,
                       "audio_sha256": audio_sha, "audio_bytes": len(audio), "audio_format": "PCM s16le WAV, 16 kHz mono",
                       "endpoint": "/v1/audio/transcriptions", "response_format": "verbose_json",
                       "timestamp_granularities": ["word", "segment"], "temperature": 0,
                       "note": "Replaces asr.py's local faster-whisper call (beam_size=5, vad_filter=True) with the shared Transcriber; decoding options are the Transcriber's."},
    }
    return receipt, raw


def model_path(model):
    return quote(model, safe="/")
