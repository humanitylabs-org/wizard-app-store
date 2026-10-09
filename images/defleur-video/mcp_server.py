#!/usr/bin/env python3
"""MCP (Streamable HTTP) front door for DeFleur Video.

Runs on loopback (MCP_INTERNAL_PORT, default 8788) inside the same container;
service.py proxies /mcp on port 8787 to it and applies VIDEO_API_TOKEN. Every
tool calls the existing internal HTTP API on loopback, so no pipeline logic is
duplicated here. Hermes (or any MCP client) is the editor; this app never calls
an LLM.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))  # run with -I: make the app's pure helpers importable
from editing import (FILLERS, HANDLE_S, PAUSE_S, REPORT_FILLERS, align_words, candidates_from,  # noqa: E402,F401
                     cut_regions, cut_sound_check, delivery_word_review, diff_words, edit_word_review,
                     recheck_result, recheck_windows)
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

API = os.environ.get("VIDEO_INTERNAL_API", "http://127.0.0.1:8787")
TOKEN = os.environ.get("VIDEO_API_TOKEN", "")
PUBLIC_URL = os.environ.get("VIDEO_PUBLIC_URL", "").rstrip("/")
RUNS = Path(os.environ.get("VIDEO_DATA_DIR", "/data")) / "mcp-runs"
VERSION = os.environ.get("VIDEO_VERSION", "")
ID = re.compile(r"^[a-f0-9]{32}$")
RUN_ID = re.compile(r"^run-[a-f0-9]{32}$")
LOCK = threading.Lock()
LANG_NAMES = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it", "portuguese": "pt",
              "dutch": "nl", "japanese": "ja", "chinese": "zh", "korean": "ko", "russian": "ru", "arabic": "ar", "hindi": "hi"}

NOT_BUILT = ["human viewing and listening review (always the owner's job)",
             "animated (moving) crops: James' contract forbids detector-driven pans; reframing is one fixed crop per setup"]

# The setup DeFleur Video is built and tested for. One place: the agent check, GUIDE, SKILL.md and the app card quote it.
INTENDED = {"harness": "Hermes Agent", "model": "Claude Opus 5.5", "model_id": "claude-opus-5-5"}
# MCP clientInfo names of other harnesses (lower-case substrings). The Python MCP SDK's default name is "mcp".
OTHER_CLIENTS = {"claude-code": "Claude Code", "claude-ai": "Claude (claude.ai / desktop)", "cursor": "Cursor", "codex": "OpenAI Codex",
                 "openai": "OpenAI", "visual studio code": "VS Code", "vscode": "VS Code", "windsurf": "Windsurf", "goose": "Goose",
                 "cline": "Cline", "continue": "Continue", "zed": "Zed", "librechat": "LibreChat", "n8n": "n8n", "openclaw": "OpenClaw"}


def _norm_model(m: str) -> str:
    m = re.sub(r"\[.*?\]", "", m.strip().lower())          # claude-opus-5-5[1m] -> claude-opus-5-5
    m = re.split(r"[/:]", m)[-1] if re.search(r"[/:]", m) else m  # anthropic/claude-opus-5-5, bedrock:...
    m = re.sub(r"^(anthropic|us|eu|apac|global)\.", "", m)     # bedrock-style prefixes
    return re.sub(r"[\s._]+", "-", m).strip("-")


def model_matches(model: str | None) -> bool | None:
    if not model or not str(model).strip():
        return None
    n = _norm_model(str(model))
    return bool(re.fullmatch(r"(claude-)?opus-5-5(-\d{8}|-v\d+(-\d+)?|-latest)?", n))


def harness_matches(harness: str | None) -> bool | None:
    if not harness or not str(harness).strip():
        return None
    return "hermes" in re.sub(r"[^a-z]", "", str(harness).lower())


def detected_harness(client: dict | None) -> dict:
    """What the MCP initialize clientInfo says (server-side; the model is never in MCP)."""
    if not client or not client.get("name"):
        return {"harness": None, "verdict": "unknown", "basis": "no MCP clientInfo seen for this connection"}
    name = str(client["name"]).lower()
    if "hermes" in name:
        return {"harness": "Hermes Agent", "verdict": "intended", "basis": f"clientInfo name '{client['name']}'"}
    for key, label in OTHER_CLIENTS.items():
        if key in name:
            return {"harness": label, "verdict": "other", "basis": f"clientInfo name '{client['name']}'"}
    if name == "mcp":
        return {"harness": None, "verdict": "unknown", "basis": "clientInfo is the Python MCP SDK default ('mcp'), which Hermes Agent "
                                                                 "sends but so can other Python agents: consistent with Hermes, not proof"}
    return {"harness": client["name"], "verdict": "unknown", "basis": f"unrecognised clientInfo name '{client['name']}'"}


def agent_check(harness: str | None, model: str | None, client: dict | None) -> dict:
    det = detected_harness(client)
    h, m = harness_matches(harness), model_matches(model)
    if det["verdict"] == "other":
        h = False
    match = False if False in (h, m) else (True if h and m else "unknown")
    out = {"intended": INTENDED, "detected_client": {**(client or {}), **det},
           "claimed": {"agent_harness": harness or None, "agent_model": model or None, "harness_matches": h, "model_matches": m},
           "match": match, "requires_owner_confirmation": match is not True,
           "model_note": "MCP does not carry the model name, so the model is only what the agent reports; a missing model counts as unknown."}
    if match is True:
        out["warning"] = None
        out["next"] = "Intended setup. Continue with capabilities."
    else:
        you = (harness or det.get("harness") or "an unknown agent") + " with " + (model or "an unknown model")
        out["warning"] = (f"DeFleur Video is built for {INTENDED['harness']} with {INTENDED['model']}. You're using {you}. "
                          "You can continue, but results may vary; you'll get the best results with the intended setup. Continue?")
        out["next"] = ("Before importing anything, show the owner `warning` word for word and WAIT for a yes. "
                       + ("If you did not pass agent_harness and agent_model, call workflow_guide again with your own harness name and "
                          "exact model id first. " if not (harness and model) else "")
                       + "If they say yes, continue with capabilities; otherwise stop.")
    return out


def client_from(ctx) -> dict | None:
    """clientInfo for this caller: the SDK session (stateful) or the header the app's /mcp proxy adds (stateless)."""
    try:
        cp = ctx.session.client_params  # type: ignore[union-attr]
        ci = getattr(cp, "client_info", None) if cp else None
        if ci is not None and getattr(ci, "name", None):
            return {"name": ci.name, "version": getattr(ci, "version", None), "source": "MCP initialize (session)"}
    except Exception:
        pass
    try:
        raw = ctx.request_context.request.headers.get("x-defleur-mcp-client")  # type: ignore[union-attr]
        if raw:
            d = json.loads(raw)
            if isinstance(d, dict):
                return {**{k: str(v)[:80] for k, v in d.items() if k in ("name", "version", "title", "user_agent", "protocol_version")},
                        "source": "MCP initialize (seen by the app proxy for this peer)"}
    except Exception:
        pass
    return None


MOTION_CONTRACT = {
    "what": ("Motion graphics, on by default (James DeFleur's defleur-motion piece). YOU author a small project-local HTML/SVG/GSAP page; "
             "the app captures it frame-by-frame with James' capture.cjs in the shared Browser app, burns captions and encodes. "
             "Without a submission render_final makes live footage plus captions (plain), which is only for the cases in default_edit."),
    "page_rules": [
        "index.html must include <script src=\"defleur/ledger.js\"></script> (app-generated: defines window.sourceFrameForOutputFrame(frame) from the locked source-frame map, plus window.DEFLEUR with fps, frames, duration, beats, inserts) and <script src=\"defleur/gsap.min.js\"></script> (vendored GSAP 3.15.0) BEFORE your own script.",
        "Canvas is exactly 1080x1920 CSS px; body margin 0; overflow hidden.",
        "<img id=\"live\"> is the live footage: the app sets its src to the already-cropped 1080x1920 frame for every output frame (and to the insert media during an insert window). Keep it full-canvas (position:absolute; inset:0; width:1080px; height:1920px) unless a beat deliberately shrinks/moves it.",
        "window.renderFrame = (t) => {...}: SYNCHRONOUS, deterministic state reconstruction for second t. Reset or hide EVERY scene node on each call, then set them for t. Build GSAP timelines paused and call tl.seek(t, false) / tl.progress(); never rely on playback, Date, Math.random or requestAnimationFrame. Seeking backward after late scenes must not leave their nodes visible (capture.cjs re-renders frames in reverse and fails on any byte difference).",
        "window.captionSuppressed = (t) => bool: true only inside plan.caption_suppress ranges (the default from ledger.js already does this; capture fails if the page disagrees with the plan).",
        "window.visualMode = (t) => 'live' | 'beat' | 'fullscreen-insert' (default from ledger.js; inside an insert window it must return 'fullscreen-insert').",
        "No network: every file must be in the submission (fonts as .woff2). Requests outside the composition are blocked and reported.",
        "Outside beat and insert windows the picture must be the plain live frame: hide all overlays there (checked in decoded pixels).",
        "Keep text inside the essential rect x 120-960, y 220-1180; captions live in y 1240-1430 (James' neutral preset), so do not put graphics there while captions show.",
    ],
    "beat_rules": (
        "Every beat makes an EXPLANATORY change: route a cause to an effect, replace a state, accumulate a quantity that changes behaviour, "
        "transform a topology, reveal a comparison, or return to the source with new meaning. No static title cards or opacity-only labels. "
        "Each beat in plan.beats needs numeric start/end (seconds of the EDITED timeline) and text fields spoken_anchor (the words it explains), "
        "viewer_inference, visual_family (documentary|diagram|photographic-metaphor|typographic-explanation|illustration), state_before, "
        "state_after, causal_action, caption_treatment ('show' or 'suppress') and speaker_return. Give readable content dwell time."),
    "captions": ("Captions are burned from the edited-audio words. Suppress them ONLY where the visual itself carries the same spoken words: "
                 "list the range in plan.caption_suppress [{start, end, reason}] inside a beat whose caption_treatment is 'suppress'."),
    "inserts": ("Fullscreen inserts / B-roll: upload the media (create_asset_upload for .mp4/.jpg/.png/.webp, or base64 in submit_motion for small "
                "images) and list plan.inserts [{start, end, asset: 'assets/clip.mp4', fit: 'cover'|'contain', clip_start_s, reason}]. During an "
                "insert window #live shows the insert media (cropped to fill 1080x1920 for cover) instead of the speaker; audio stays the speaker's. "
                "Fullscreen ranges are James' explicit exceptions to the live crop policy and are recorded in crop-ledger fullscreen_exceptions."),
    "sequence": ["submit_motion(project_id, files, plan)", "capture_motion(project_id, 'smoke') - first ~6 s; look at the returned frame images",
                 "fix the page if anything looks wrong and submit again", "capture_motion(project_id, 'proof') - starts, middles and ends of every beat plus reverse-seek determinism; look at the frames and the contact sheet",
                 "render_final(project_id, {'motion': true}) - full capture (every frame), captions, encode, checks, delivery gate"],
    "skeleton": (
        "<!doctype html><html><head><meta charset=\"utf-8\"><link rel=\"stylesheet\" href=\"style.css\"></head><body>"
        "<img id=\"live\" alt=\"\"><div id=\"beat1\" class=\"scene\">...</div>"
        "<script src=\"defleur/ledger.js\"></script><script src=\"defleur/gsap.min.js\"></script><script src=\"main.js\"></script></body></html>  "
        "main.js: const tl = gsap.timeline({paused: true}); tl.set('.scene', {autoAlpha: 0}, 0); tl.fromTo('#beat1', {autoAlpha: 0, y: 40}, {autoAlpha: 1, y: 0, duration: 0.4}, 2.0) ... ; "
        "window.renderFrame = (t) => { tl.seek(t, false); };"),
    "files": ("Allowed paths: lowercase a-z0-9_- names, up to 3 levels (e.g. index.html, main.js, style.css, assets/chart.svg, assets/clip.mp4). "
              "Kinds: .html .css .js .svg .json (UTF-8 text, 2 MiB each) and .png .jpg .jpeg .webp (32 MiB) .woff2 (8 MiB) .mp4 (2 GiB, upload URL only). "
              "Reserved: defleur/, base_frames/, timeline/plan/capture files. Inline submission total 3 MiB."),
}

RULES = [
    "Edit for a coherent, faithful thought: keep claims, context, speaker meaning and sentence syntax. Never stitch words into a new meaning.",
    "Every deletion needs a truthful reason (filler, long pause, false start/restart, repeat, off-topic aside the owner approved).",
    "Remove fillers (um/uh/erm) and shorten long pauses, but cut in the silence around them: keep ~0.1 s of handle so no consonant, vowel tail or breath release is clipped.",
    "If a tiny cut threatens a word, restore the whole clause instead of shaving it.",
    "ASR can omit fillers and even whole sentences: start_edit proposes a pause only after measuring it near-silent; gaps with sound go to untranscribed_sound for the owner to review, never into proposed_cuts.",
    "apply_cuts measures every cut you send (including hand-written ones); a cut with speech-like sound the transcript does not explain fails the reported gate unless the owner listened and you mark it owner_approved_sound: true.",
    "Fillers (um/uh/er/oh/ah) heard in only one transcript are reported separately (ASR can omit them); they are not lost content.",
    "Infer the language from ASR; ask the owner when it is uncertain.",
    "After assembly, re-transcribe the edited audio and check that no kept word was lost (apply_cuts does this and reports it). A word lost within 0.5 s of a cut fails the gate; a word missed far from every cut is identical audio, so it is listed under asr_variance_far_from_cuts (ASR variance) and does not fail.",
    "The dialogue gate checks evidence completeness and custody. It is not human listening approval: tell the owner to listen before using the edit.",
]

GUIDE = {
    "what_this_app_does": (
        "DeFleur Video runs James DeFleur's complete short-form video workflow on this server: upload (up to 20 min, up to 4K; "
        "HEVC, VFR and larger-than-1080p footage is normalized to 1080p H.264 CFR), 48 kHz PCM extraction, speech-to-text through "
        "the separate Transcriber app, local word alignment, sample-exact audio cutting with per-edge evidence, re-transcription "
        "and James' dialogue gate; then fixed per-setup face crops (optionally choosing which speaker each segment frames), optional "
        "HTML/SVG/GSAP motion graphics and fullscreen inserts captured by James' capture.cjs in the shared Browser app, burned "
        "captions, his 1080x1920 encode and delivery gate. You (the agent) are the editor and motion author; the app never calls an LLM."),
    "skill": "The editing judgment for this app is in SKILL.md (MCP resource defleur-video://SKILL.md, or GET /SKILL.md on this app). It agrees with these steps.",
    "default_edit": ("A DeFleur edit = the owner's approved cuts + motion graphics (James DeFleur's motion contract: your HTML/SVG/GSAP "
                     "beats and any fullscreen inserts) + burned captions + the fixed 9:16 crop. Motion graphics are ON by default: they "
                     "are the point of this editor. Go plain (render_final({})) ONLY if the owner asks for plain / no motion, the Browser "
                     "app is missing (relay capabilities' fix), or motion capture still fails after a reasonable retry; then tell the "
                     "owner exactly why."),
    "steps": [
        "0. Agent check: call workflow_guide(agent_harness=<your harness, e.g. 'Hermes Agent'>, agent_model=<your exact model id>). "
        "If agent_check.requires_owner_confirmation, show the owner agent_check.warning in plain words and WAIT for a yes before importing anything.",
        "1. capabilities - the Transcriber must be ready; motion_ready must be true for motion graphics (if not, relay the Browser fix to the owner).",
        "2. Get the video: list_files() to find the owner's file in Files -> Videos (match the name, ignoring case), then import_file(path); it returns the project id. "
        "Fallback only (no Files app): create_upload. Video bytes never travel through MCP.",
        "3. start_edit(project_id) -> get_status(run_id) until 'done': transcript, word timings, proposed cuts, untranscribed_sound.",
        "4. Draft the motion plan from the transcript (3-6 beats for a 1-3 minute video, plus any fullscreen inserts): for each beat the "
        "source time range, the spoken words it explains, and what the viewer sees change (see motion_contract.beat_rules). Times are "
        "SOURCE seconds for now; they are converted to edited seconds in step 7.",
        "5. ONE approval question: show the cut list (time, words, reason, and any untranscribed_sound gaps) AND the motion plan together; "
        "ask the owner to approve or change either. Do not skip the cut approval. Do not apply cuts before the answer.",
        "6. apply_cuts(project_id, approved cuts) -> get_status until 'done'. If words_lost_near_cuts is non-empty or the dialogue gate "
        "failed, fix the cuts and apply again; asr_variance_far_from_cuts are untouched audio the second ASR pass missed (mention, not lost).",
        "7. Author the motion composition (motion_contract) with beat/insert times in EDITED seconds: convert each approved source "
        "time with apply_cuts' time_map (edited = edited_start_s + (source - source_start_s) inside a kept segment) or read them off "
        "edited_words. submit_motion -> capture_motion 'smoke' -> LOOK at the frames -> fix if needed -> capture_motion 'proof' -> LOOK at the contact sheet and frames.",
        "8. Optional framing for two-person shots: preview_framing(project_id, framing); pass the same framing to capture_motion and render_final.",
        "9. render_final(project_id, {'motion': true}) after a passing proof (plain: {} only for the reasons in default_edit). Poll get_status: "
        "elapsed_s, step, sub_stage and estimate_remaining_s are live; a motion render of a 2-minute video takes ~15 min on 4 CPUs.",
        "10. Report in plain words: resolution, duration, the motion beats and inserts delivered (times and what each shows), caption count "
        "and suppressions, crop result (if a framing flag appears, look at several frames across the video, not one), delivery gate "
        "pass/fail with the reason, words lost, and where the video is (Files -> Videos -> Edited, plus the final_mp4 link). If you "
        "rendered plain, say why. Ask the owner to watch it on a phone before posting.",
    ],
    "motion_contract": MOTION_CONTRACT,
    "long_work": "start_edit, apply_cuts, capture_motion and render_final return immediately with a run_id. Keep calling get_status(run_id) (each call waits up to ~55 s) until state is 'done' or 'failed'. Transcription and alignment of a few minutes of speech can take several minutes on CPU.",
    "not_built_yet": NOT_BUILT,
    "outputs_today": ("apply_cuts: edited 48 kHz WAV, edit map, cut evidence images, dialogue gate receipt and a low-resolution 9:16 preview. "
                      "capture_motion: captured frame images and a contact sheet to look at. render_final: the finished 1080x1920 H.264/AAC MP4 "
                      "(fixed crop per setup, optional motion graphics and fullscreen inserts, burned-in captions), crop ledger, face audit, "
                      "decode/pixel/motion-window checks and James' delivery gate receipt."),
    "files": ("The Files app is the owner's shared folder on this server (Runtipi's media folder, mounted here at /media). "
              "Source videos normally live in Files -> Videos; finished videos are saved to Files -> Videos -> Edited as "
              "<source name>-edited-<id>.mp4 (never overwriting). Paths you pass are relative to Files, e.g. 'Videos/IMG_5644.mov'."),
    "limits": ("One video and one audio stream per upload, at most 20 minutes and 8 GiB, up to 4K (edited at 1080p); finished video up to 6 minutes; "
               "8 projects at a time. capabilities reports host RAM, free disk and per-job estimates."),
}


# ---------- loopback API ----------

def api(method: str, path: str, body: Any = None, raw: bool = False, timeout: float = 70):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode(errors="replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise ToolError(f"{method} {path.split('?')[0]} -> HTTP {e.code}: {detail}") from None
    except OSError as e:
        raise ToolError(f"internal API unreachable: {type(e).__name__}") from None
    return content if raw else json.loads(content)


class ToolError(Exception):
    pass


def media_fix(caps: dict) -> str | None:
    m = caps.get("media") or {}
    return m.get("fix")


def artifact(job: str, name: str):
    return json.loads(api("GET", f"/v1/jobs/{job}/stage-artifacts/{name}", raw=True))


def norm(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum())


def base_url(ctx: Context | None) -> str:
    if PUBLIC_URL:
        return PUBLIC_URL
    try:
        headers = ctx.request_context.request.headers  # type: ignore[union-attr]
        host = headers.get("x-forwarded-host") or headers.get("host")
        if host and re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", host):
            return "http://" + host
    except Exception:
        pass
    return "http://127.0.0.1:8787"


# ---------- background runs ----------

def run_path(rid: str) -> Path:
    if not RUN_ID.fullmatch(rid):
        raise ToolError("run id must look like run-<32 hex>")
    return RUNS / (rid + ".json")


def save(run: dict):
    RUNS.mkdir(parents=True, exist_ok=True, mode=0o700)
    run["updated"] = time.time()
    tmp = RUNS / (run["id"] + ".tmp")
    tmp.write_text(json.dumps(run))
    tmp.replace(run_path(run["id"]))


def load(rid: str) -> dict:
    try:
        return json.loads(run_path(rid).read_text())
    except FileNotFoundError:
        raise ToolError(f"unknown run {rid}") from None


def runs_for(project: str, kind: str | None = None, state: str | None = None) -> list[dict]:
    out = []
    for p in RUNS.glob("run-*.json") if RUNS.is_dir() else []:
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if r.get("project") == project and (kind is None or r.get("kind") == kind) and (state is None or r.get("state") == state):
            out.append(r)
    return sorted(out, key=lambda r: r["created"])


def start_run(kind: str, project: str, params: dict, target) -> dict:
    run = {"id": "run-" + uuid.uuid4().hex, "kind": kind, "project": project, "params": params,
           "state": "running", "step": "queued", "steps": [], "created": time.time(), "result": None, "error": None}
    save(run)

    def body():
        try:
            run["result"] = target(run)
            run["state"], run["step"] = "done", "done"
        except Exception as e:  # report every failure to the agent, plainly
            run["state"], run["error"] = "failed", f"{run['step']}: {e}"[:1500]
        save(run)
    threading.Thread(target=body, daemon=True).start()
    return run


def stage(run: dict, op: str, body: dict, wait_s: float = 2400) -> dict:
    run["step"] = op
    save(run)
    deadline = time.monotonic() + 30
    while True:  # the API allows two active jobs; retry briefly while another run holds the queue
        try:
            job = api("POST", f"/v1/projects/{run['project']}/stages/{op}", body)
            break
        except ToolError as e:
            if "queue full" not in str(e) or time.monotonic() > deadline:
                raise
            time.sleep(2)
    end = time.monotonic() + wait_s
    run["stage_started"], run["progress"] = time.time(), None
    save(run)
    last_saved = time.monotonic()
    while job["state"] in ("queued", "running"):
        if time.monotonic() > end:
            raise ToolError(f"{op} job {job['id']} still running after {wait_s:.0f} s")
        time.sleep(0.5)
        job = api("GET", f"/v1/jobs/{job['id']}")
        prog = job.get("progress")
        if prog != run.get("progress") and (time.monotonic() - last_saved > 2 or (prog or {}).get("phase") != (run.get("progress") or {}).get("phase")):
            run["progress"], last_saved = prog, time.monotonic()
            save(run)
    run["progress"] = None
    run["steps"].append({"stage": op, "job": job["id"], "state": job["state"],
                         "elapsed_s": (job.get("result") or {}).get("elapsed_s")})
    save(run)
    if job["state"] != "needs_review":
        raise ToolError(f"{op} job {job['id']} failed: {job.get('error')}")
    return job


def interrupted_runs():
    """A restart kills run threads; never leave a run looking alive."""
    for p in RUNS.glob("run-*.json") if RUNS.is_dir() else []:
        try:
            r = json.loads(p.read_text())
            if r.get("state") == "running":
                r["state"], r["error"] = "failed", "interrupted by an app restart; start it again"
                save(r)
        except (OSError, ValueError):
            pass


# ---------- start_edit ----------

def do_start_edit(run: dict) -> dict:
    lang = run["params"].get("language") or "auto"
    src = stage(run, "source-audio", {})
    summary = src["result"]["summary"]
    asr = stage(run, "asr", {"audio_job": src["id"], "language": lang})
    detected = asr["result"]["summary"].get("language_detected") or (lang if lang != "auto" else None)
    detected = LANG_NAMES.get(str(detected).lower(), str(detected).lower()) if detected else None
    if not detected or not re.fullmatch(r"[a-z]{2,3}", detected):
        raise ToolError("ASR did not report a language; call start_edit again with language='en' (or the right code)")
    pre = stage(run, "preflight", {"language": detected})
    al = stage(run, "align", {"asr_job": asr["id"], "language": detected})
    aligned = artifact(al["id"], "aligned.json")
    words = [{"word": w["word"].strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
             for s in aligned.get("segments", []) for w in s.get("words", []) if w.get("word", "").strip()]
    duration = float(summary["duration_s"])
    env = artifact(src["id"], "energy.json")
    cands, proposed, untranscribed, screen = candidates_from(words, duration, env)
    asr_receipt = artifact(asr["id"], "asr.json")
    return {
        "project_id": run["project"], "duration_s": round(duration, 3), "language": detected,
        "language_probability": asr_receipt.get("language_probability"),
        "constant_frame_rate": summary.get("constant_frame_rate"),
        "transcript": " ".join(w["word"] for w in words),
        "words": [[i, w["word"], w["start"], w["end"]] for i, w in enumerate(words)],
        "words_format": "[index, word, start_s, end_s] from local stable-ts alignment of the Transcriber ASR",
        "candidates": cands,
        "proposed_cuts": proposed,
        "untranscribed_sound": untranscribed,
        "untranscribed_sound_note": ("Gaps between transcribed words that contain speech-like sound: the ASR may have skipped a "
                                     "sentence or a filler there. They are NOT in proposed_cuts. Tell the owner about each one "
                                     "(time, words around it) and ask them to listen before cutting any of it."),
        "pause_screen": screen,
        "editorial_rules": RULES,
        "preflight": {k: pre["result"]["summary"].get(k) for k in ("helper_passed", "missing")},
        "jobs": {"source_audio": src["id"], "asr": asr["id"], "align": al["id"]},
        "asr_limitation": asr_receipt.get("limitation") or "ASR can omit fillers or miss words.",
        "next": ("Show the owner proposed_cuts as a readable list (time range, the words around it, reason). "
                 + (f"Also tell them about the {len(untranscribed)} untranscribed_sound gap(s): there is sound the transcript does not "
                    "show (maybe a skipped sentence); they stay in unless the owner listens and asks to cut them. " if untranscribed else "")
                 + "ALSO draft the motion plan now (workflow_guide step 4: 3-6 explanatory beats, each with its source time range, the "
                 "spoken words it explains and what the viewer sees change, plus any fullscreen inserts) and show the cuts and the motion "
                 "plan together in ONE question. Motion graphics are the default; only skip them if the owner asks for a plain video. "
                 "After the owner approves, call apply_cuts(project_id, segments=<approved ranges to REMOVE>). "
                 "Do not call apply_cuts without the owner's approval."),
    }


# ---------- apply_cuts ----------

def clean_cuts(segments: Any, duration: float) -> list[dict]:
    if not isinstance(segments, list) or len(segments) > 300:
        raise ToolError("segments must be a list of 0..300 {start_s, end_s, reason} ranges to REMOVE ([] = no cuts, keep the whole source)")
    rows = []
    for s in segments:
        if not isinstance(s, dict):
            raise ToolError("each segment must be an object {start_s, end_s, reason}")
        try:
            a, b = float(s["start_s"]), float(s["end_s"])
        except (KeyError, TypeError, ValueError):
            raise ToolError("each segment needs numeric start_s and end_s (seconds in the source)") from None
        reason = str(s.get("reason", "")).strip()
        if not reason:
            raise ToolError("every cut needs a truthful reason")
        a, b = max(0.0, a), min(duration, b)
        if b - a < 0.01:
            raise ToolError(f"cut {s} is shorter than 10 ms or outside the {duration:.3f} s source")
        row = {"start_s": round(a, 6), "end_s": round(b, 6), "reason": reason[:500]}
        if s.get("owner_approved_sound") is True:
            row["owner_approved_sound"] = True
        rows.append(row)
    rows.sort(key=lambda r: r["start_s"])
    merged: list[dict] = []
    for r in rows:
        if merged and r["start_s"] <= merged[-1]["end_s"]:
            merged[-1]["end_s"] = max(merged[-1]["end_s"], r["end_s"])
            merged[-1]["reason"] += "; " + r["reason"]
            if not r.get("owner_approved_sound"):
                merged[-1].pop("owner_approved_sound", None)  # an override covers only the range the owner approved
        else:
            merged.append(dict(r))
    return merged


def keeps_from(cuts: list[dict], duration: float) -> list[dict]:
    keeps, cursor = [], 0.0
    for c in cuts:
        if c["start_s"] - cursor >= 0.01:
            keeps.append({"start_s": round(cursor, 6), "end_s": c["start_s"], "reason": "kept speech"})
        cursor = c["end_s"]
    if duration - cursor >= 0.01:
        keeps.append({"start_s": round(cursor, 6), "end_s": round(duration, 6), "reason": "kept speech"})
    if not keeps:
        raise ToolError("those cuts remove the whole source")
    return keeps


PREVIEW_MAX_S = 60.0  # service.submit's low-resolution preview limit


def preview_keeps(keeps: list[dict]) -> list[dict]:
    """The kept spans the 270x480 preview can show: the first PREVIEW_MAX_S seconds of the edit."""
    out, total = [], 0.0
    for k in keeps:
        room = PREVIEW_MAX_S - total
        if room < 0.1:
            break
        end = round(min(k["end_s"], k["start_s"] + room), 6)
        if end - k["start_s"] >= 0.1:
            out.append({"start_s": k["start_s"], "end_s": end, "reason": k["reason"]})
            total += end - k["start_s"]
    return out


def in_cut(t: float, cuts: list[dict]) -> bool:
    return any(c["start_s"] <= t <= c["end_s"] for c in cuts)


def do_apply_cuts(run: dict) -> dict:
    edit = run["params"]["edit"]
    cuts, duration = run["params"]["cuts"], run["params"]["duration_s"]
    keeps = keeps_from(cuts, duration)
    words = [{"word": w[1], "start": w[2], "end": w[3]} for w in edit["words"]]
    lang = edit["language"]
    asm = stage(run, "pcm-assemble", {"audio_job": edit["jobs"]["source_audio"], "segments": keeps})
    # Regions come from the assembled (sample-exact) segments, the same list the audio was built from.
    blocks = artifact(asm["id"], "edit-map.json")["segments"]
    regions, removed, kept_words = cut_regions(words, blocks, duration, timed=True)
    audit = stage(run, "speech-cut-audit", {"assemble_job": asm["id"], "regions": regions[:2000]})
    cut_receipt = artifact(audit["id"], "cut-regression.json")
    scan = stage(run, "acoustic-scan", {"assemble_job": asm["id"]})
    windows = artifact(scan["id"], "acoustic-windows.json")["windows"]
    easr = stage(run, "asr", {"audio_job": asm["id"], "language": lang})
    edited_words = [w for w in artifact(easr["id"], "asr.json")["words"]]
    got = [norm(w["word"]) for w in edited_words if norm(w["word"])]
    review_words = edit_word_review(kept_words, got, blocks, duration, words)
    lost, added, variants = review_words["lost"], review_words["added"], review_words["variants"]
    fillers_source_only, fillers_edit_only = review_words["fillers_source_only"], review_words["fillers_edit_only"]
    lost_near = review_words["lost_near_cuts"]
    # A long ASR pass can merge or re-segment words next to a splice. Give each near-cut lost word a focused second
    # opinion on the SAME edited audio (RECHECK_PAD_S around it): it counts as present only if heard in place.
    rechecks = []
    if lost_near:
        run["step"] = "local re-check of words near cuts"
        save(run)
        edited_len = float(asm["result"]["summary"]["duration_s"])
        for win in recheck_windows(lost_near, blocks, edited_len):
            wj = stage(run, "asr", {"audio_job": asm["id"], "language": lang, "start_s": win[0], "end_s": win[1]})
            toks = [w["word"] for w in artifact(wj["id"], "asr.json")["words"]]
            heard = set(recheck_result(win, kept_words, blocks, toks, lost_near))
            rechecks.append({"edited_window_s": win, "asr_job": wj["id"], "text": " ".join(toks)[:600],
                             "heard_in_place": [r["word"] for r in lost_near if r.get("source_index") in heard]})
            for r in lost_near:
                if r.get("source_index") in heard:
                    r["heard_on_local_recheck"] = {"edited_window_s": win, "asr_job": wj["id"]}
        recovered = [r for r in lost_near if r.get("heard_on_local_recheck")]
        lost_near = [r for r in lost_near if not r.get("heard_on_local_recheck")]
        review_words.update(lost_near_cuts=lost_near, lost_near_cuts_heard_on_local_recheck=recovered, fail=bool(lost_near))
    fillers_left = [w for w in got if w in FILLERS]
    sound = cut_sound_check(cuts, artifact(edit["jobs"]["source_audio"], "energy.json"), words)

    cand_rows = []
    for c in edit["candidates"]:
        if c["kind"] not in ("filler", "repeat"):
            continue
        gone = in_cut((c["start_s"] + c["end_s"]) / 2, cuts)
        cand_rows.append({"word": c["word"], "source_start_s": c["start_s"], "source_end_s": c["end_s"],
                          "action": "removed" if gone else "retained_with_reason",
                          "reason": c["reason"] + ("; inside an approved cut" if gone else "; not in the owner-approved cut list")})
    for w in edited_words:
        if norm(w["word"]) in FILLERS:
            cand_rows.append({"word": w["word"], "edited_start_s": w["start"], "edited_end_s": w["end"], "action": "retained_with_reason",
                              "reason": "filler heard by ASR in the edited audio; not in the owner-approved cut list"})
    filler_review = {"full_pass_reviewed": True, "candidates": cand_rows, "none_found": not cand_rows,
                     "basis": "Automated by the app from source ASR+alignment candidates and a re-transcription of the edited audio; not human listening."}
    edited_text = lambda a, b: " ".join(w["word"] for w in edited_words if w["start"] < b and w["end"] > a)[:300]
    acoustic_review = [{"window": w["index"], "findings": (
        f"Automated: edited {w['start']:.2f}-{w['end']:.2f} s, RMS {w['rms_dbfs'] if w['rms_dbfs'] is not None else 'digital silence'} dBFS; "
        f"edited ASR: '{edited_text(w['start'], w['end'])}'. Waveform/spectrogram images exist; not human listening.")} for w in windows]
    failed_regions = [r for r in cut_receipt.get("candidate", []) if not r.get("pass")]
    edges = []
    for e in cut_receipt.get("edges", []):
        t = float(e["source_s"])
        near = min(words, key=lambda w: min(abs(w["start"] - t), abs(w["end"] - t)), default=None)
        gap = min(abs(near["start"] - t), abs(near["end"] - t)) if near else None
        edges.append({"segment": int(str(e["waveform"]).split("-")[0]), "edge": e["edge"], "decision": "keep",
                      "findings": (f"Automated: {e['edge']} edge at source {t:.3f} s; nearest aligned word '{near['word'] if near else '-'}' "
                                   f"{gap:.3f} s away; keep/drop coverage {'passed' if not failed_regions else 'FAILED'}. "
                                   "Images rendered (waveform+spectrogram); not human listening.")})
    gate = stage(run, "dialogue-gate", {"assemble_job": asm["id"], "audit_job": audit["id"], "scan_job": scan["id"],
                                        "edited_asr_job": easr["id"], "filler_review": filler_review,
                                        "acoustic_review": acoustic_review, "reviewed_edges": edges})
    gsum = gate["result"]["summary"]
    if failed_regions:
        r0 = failed_regions[0]
        gsum = {**gsum, "error": (gsum.get("error") or "") + f" - {len(failed_regions)} cut-audit region(s) failed; first: {r0['mode']} "
                f"{float(r0['start_s']):.3f}-{float(r0['end_s']):.3f} s{' (' + r0['word'] + ')' if r0.get('word') else ''} should retain "
                f"{(float(r0['end_s']) - float(r0['start_s'])) if r0['mode'] == 'keep' else 0:.3f} s but the assembly retained {float(r0['retained_s']):.3f} s"}
    base = run["params"]["base_url"]
    dl = lambda j, n: f"{base}/v1/jobs/{j}/stage-artifacts/{n}"
    names = {a["name"] for a in asm["result"]["artifacts"]}
    downloads = {"edited_audio_wav": dl(asm["id"], "edited.wav"), "edit_map_json": dl(asm["id"], "edit-map.json"),
                 "cut_evidence_json": dl(audit["id"], "cut-regression.json"),
                 "dialogue_gate_result_json": dl(gate["id"], "dialogue-gate-result.json"),
                 "edited_transcript_json": dl(easr["id"], "asr.json")}
    if "edit-map.json" not in names:
        downloads.pop("edit_map_json")
    preview_note = "skipped: the preview renderer supports at most 8 kept segments of at least 0.1 s"
    pkeeps = preview_keeps(keeps)
    if pkeeps and len(pkeeps) <= 8 and all(k["end_s"] - k["start_s"] >= 0.1 for k in pkeeps):
        run["step"] = "preview"
        save(run)
        try:
            job = api("POST", f"/v1/projects/{run['project']}/previews", {"segments": pkeeps})
            end = time.monotonic() + 600
            while job["state"] in ("queued", "running") and time.monotonic() < end:
                time.sleep(0.5)
                job = api("GET", f"/v1/jobs/{job['id']}")
            if job["state"] == "needs_review":
                downloads["preview_9x16_mp4"] = f"{base}/v1/jobs/{job['id']}/preview"
                preview_note = ("low-resolution 9:16 letterboxed preview of the cut (not the final 1080x1920 encode)"
                                + (f"; shows the first {PREVIEW_MAX_S:.0f} s of the edit" if pkeeps != keeps else ""))
            else:
                preview_note = f"preview failed: {job.get('error')}"
        except ToolError as e:
            preview_note = f"preview failed: {e}"
    edit_map = artifact(asm["id"], "edit-map.json")
    return {
        "project_id": run["project"],
        "seconds_removed": round(duration - float(edit_map["duration"]), 3),
        "source_duration_s": round(duration, 3), "edited_duration_s": round(float(edit_map["duration"]), 3),
        "cuts_applied": cuts, "kept_segments": len(keeps),
        "time_map": [{"source_start_s": round(float(b["start_s"]), 3), "source_end_s": round(float(b["end_s"]), 3),
                      "edited_start_s": round(float(b["output_start"]), 3), "edited_end_s": round(float(b["output_end"]), 3)} for b in blocks],
        "time_map_note": "Kept source spans and where they land in the edited video: edited = edited_start_s + (source - source_start_s). Motion beat/insert times are EDITED seconds.",
        "no_cuts": not cuts,
        "words_removed_by_cuts": removed,
        "words_lost_vs_source": lost, "words_added_vs_source": added,
        "words_lost_near_cuts": lost_near,
        "words_near_cuts_heard_on_local_recheck": review_words.get("lost_near_cuts_heard_on_local_recheck", []),
        "local_rechecks": rechecks,
        "asr_variance_far_from_cuts": review_words["asr_variance_far_from_cuts"],
        "lost_word_basis": review_words["basis"],
        "fillers_still_heard": fillers_left,
        "fillers_heard_in_edit_only": fillers_edit_only, "fillers_in_source_only": fillers_source_only,
        "asr_spelling_variants": variants,
        "filler_note": "ASR can omit fillers (James' asr.py), so a filler heard in only one transcript is listed here, not as lost/added content.",
        "cut_sound_check": sound,
        "cut_audit_pass": bool(audit["result"]["summary"].get("pass")),
        "cut_audit_failures": failed_regions[:20],
        # The app's reported pass also requires no lost words; James' audio_gate.py itself checks evidence only.
        "dialogue_gate": {"pass": bool(gsum["dialogue_gate_pass"]) and not review_words["fail"] and sound["pass"],
                          "reason": "; ".join(x for x in (
                              (f"{len(lost_near)} kept word(s) near a cut missing from the re-transcribed edit: "
                               + " ".join(f"{r['word']}@{r['source_start_s']:.2f}s" for r in lost_near[:20])) if lost_near else "",
                              (f"{len(review_words['asr_variance_far_from_cuts'])} word(s) missed by the second ASR pass far from "
                               f"every cut (identical audio; ASR variance, not a gate failure): "
                               + " ".join(r["word"] for r in review_words["asr_variance_far_from_cuts"][:20]))
                              if review_words["asr_variance_far_from_cuts"] and not lost_near else "",
                              "; ".join(sound["failures"][:10]) + (" (listen; if the owner approves removing it, resend that cut with "
                                                                   "owner_approved_sound: true)" if sound["failures"] else ""),
                              gsum.get("error") or "") if x) or "all required evidence present and fresh",
                          "audio_gate_script_pass": bool(gsum["dialogue_gate_pass"]),
                          "scope": "Evidence completeness and custody (James' audio_gate.py --stage dialogue); edge/window findings were written by the app automatically, not by a human listener."},
        "downloads": downloads, "preview": preview_note,
        "auth_note": "Downloads need 'Authorization: Bearer <VIDEO_API_TOKEN>' when the app has a token set." if TOKEN else None,
        "jobs": {"pcm_assemble": asm["id"], "speech_cut_audit": audit["id"], "acoustic_scan": scan["id"], "edited_asr": easr["id"], "dialogue_gate": gate["id"]},
        "next": ("Tell the owner in plain words: seconds removed, any words lost or added, gate pass/fail with the reason, and the download links. "
                 "Ask them to listen to the edited audio/preview. If words were lost or the gate failed, propose adjusted cuts and call apply_cuts again. "
                 "When the cut is good: convert the approved motion plan to edited seconds with time_map, author the composition "
                 "(workflow_guide.motion_contract), submit_motion -> capture_motion 'smoke' -> look -> 'proof' -> look, then "
                 "render_final(project_id, {'motion': true}). Use render_final(project_id, {}) (plain) only if the owner asked for no motion, "
                 "the Browser app is missing, or capture keeps failing - and tell the owner why."),
    }


# ---------- render_final ----------

def crop_body(jobs: dict, framing: dict | None) -> dict:
    body = {"assemble_job": jobs["pcm_assemble"]}
    if framing:
        body["framing"] = framing
    return body


def do_preview_framing(run: dict) -> dict:
    jobs = run["params"]["cut"]["jobs"]
    crop = stage(run, "face-crop", crop_body(jobs, run["params"].get("framing")), wait_s=1900)
    cs = crop["result"]["summary"]
    base = run["params"]["base_url"]
    dl = lambda n: f"{base}/v1/jobs/{crop['id']}/stage-artifacts/{n}"
    return {"project_id": run["project"], "framing": run["params"].get("framing") or {},
            "setups": [{**{k: s[k] for k in ("setup", "segments", "crop", "zoom", "detected", "samples", "pass", "flags")},
                        "evidence_image": dl(f"{s['setup']}-crop.png")} for s in cs["setups"]],
            "face_inside_crop_all_samples": cs["pass"], "flags": cs["flags"], "crop_job": crop["id"],
            "face_audit_json": dl("face-audit.json"), "crop_ledger_json": dl("crop-ledger.json"),
            "next": ("Look at each evidence_image (green = fixed crop, red = detected faces, yellow = caption band). If a two-person "
                     "segment frames the wrong person, call preview_framing again with framing.targets for that kept-segment index. "
                     "Pass the same framing to capture_motion / render_final.")}


def do_capture_motion(run: dict) -> dict:
    p = run["params"]
    jobs = p["cut"]["jobs"]
    crop = stage(run, "face-crop", crop_body(jobs, p.get("framing")), wait_s=1900)
    cap = stage(run, "motion-capture", {"assemble_job": jobs["pcm_assemble"], "crop_job": crop["id"], "edited_asr_job": jobs["edited_asr"],
                                        "mode": p["mode"], "composition_sha256": p["composition_sha256"]}, wait_s=3700)
    cs = cap["result"]["summary"]
    base = p["base_url"]
    dl = lambda n: f"{base}/v1/jobs/{cap['id']}/stage-artifacts/{n}"
    return {"project_id": run["project"], "mode": p["mode"], "pass": cs["pass"], "frames_captured": cs["frames_captured"],
            "determinism": {"reverse_seek_frames_checked": cs["reverse_seek_checked"], "result": cs["determinism"]},
            "page_errors": cs["page_errors"], "blocked_requests": cs["blocked_requests"], "checks": cs["checks"],
            "frame_images": [{**f, "url": dl(f["image"])} for f in cs["frames"]], "contact_sheet": dl(cs["sheet"]),
            "capture_json": dl(f"capture-{p['mode']}.json"), "composition_sha256": cs["composition_sha256"],
            "capture_seconds": cs["capture_seconds"], "crop_job": crop["id"], "capture_job": cap["id"], "framing": p.get("framing") or {},
            "next": ("LOOK at the frame images and the contact sheet (download them and view them). Check: overlays appear only in "
                     "planned beats, text is readable at phone size and inside x 120-960 / y 220-1180, inserts fill the frame, nothing "
                     "is left over after a beat. Fix and submit_motion again if needed. "
                     + ("Then run capture_motion(project_id, 'proof')." if p["mode"] == "smoke" else
                        "If it all looks right, call render_final(project_id, {'motion': true}" + (", 'framing': <same framing>" if p.get("framing") else "") + ")."))}


def do_render_final(run: dict) -> dict:
    cut = run["params"]["cut"]
    jobs = cut["jobs"]
    t0 = time.monotonic()
    proof = run["params"].get("proof")
    if proof:
        crop = api("GET", f"/v1/jobs/{proof['crop_job']}")
        body = {"assemble_job": jobs["pcm_assemble"], "crop_job": proof["crop_job"], "edited_asr_job": jobs["edited_asr"],
                "proof_job": proof["capture_job"]}
    else:
        crop = stage(run, "face-crop", crop_body(jobs, run["params"].get("framing")), wait_s=1900)
        body = {"assemble_job": jobs["pcm_assemble"], "crop_job": crop["id"], "edited_asr_job": jobs["edited_asr"]}
    render = stage(run, "final-render", body, wait_s=14500)
    lang = run["params"]["language"]
    fasr = stage(run, "asr", {"audio_job": render["id"], "language": lang})
    fscan = stage(run, "acoustic-scan", {"assemble_job": render["id"]})
    gate_job = None
    run["step"] = "delivery-gate"
    save(run)
    try:
        gate_job = stage(run, "delivery-gate", {"render_job": render["id"], "final_asr_job": fasr["id"],
                                                "final_scan_job": fscan["id"], "dialogue_gate_job": jobs["dialogue_gate"]})
    except ToolError as e:
        gate_error = str(e)
    else:
        gate_error = None
    rs, cs = render["result"]["summary"], crop["result"]["summary"]
    gs = gate_job["result"]["summary"] if gate_job else {}
    base = run["params"]["base_url"]
    dl = lambda j, n: f"{base}/v1/jobs/{j}/stage-artifacts/{n}"
    # The final-render job's crop-ledger.json is the delivered one: with motion it adds fullscreen_exceptions for inserts.
    downloads = {"final_mp4": dl(render["id"], "final.mp4"), "crop_ledger_json": dl(render["id"], "crop-ledger.json"),
                 "face_audit_json": dl(crop["id"], "face-audit.json"), "final_integrity_json": dl(render["id"], "final-integrity.json"),
                 "media_verification_json": dl(render["id"], "media-verification.json"),
                 "pixel_check_json": dl(render["id"], "motion-check.json" if proof else "live-check.json")}
    if not proof:
        downloads["frame_sample_png"] = dl(render["id"], "final-frame-sample.png")
    downloads.update({f"crop_evidence_{s['setup']}_png": dl(crop["id"], f"{s['setup']}-crop.png") for s in cs["setups"]})
    if gate_job:
        downloads["delivery_gate_result_json"] = dl(gate_job["id"], "delivery-gate-result.json")
        downloads["delivery_audio_gate_receipt_json"] = dl(gate_job["id"], "audio-gate.json")
    run["step"] = "save-to-files"
    save(run)
    try:
        saved = api("POST", "/v1/media/save-final", {"job": render["id"]}, timeout=600)
        files = {"saved": True, "path": saved["saved_to"], "bytes": saved["bytes"], "sha256": saved["sha256"],
                 "where_to_tell_the_owner": "It's in Files -> Videos -> Edited -> " + saved["name"]}
    except ToolError as e:
        files = {"saved": False, "error": str(e), "where_to_tell_the_owner": "Not saved to Files; use the final_mp4 download link."}
    plan = (run["params"].get("proof") or {}).get("plan") or {}
    beats_delivered = [{"start": b.get("start"), "end": b.get("end"), "spoken_anchor": b.get("spoken_anchor"), "shows": b.get("state_after"),
                        "visual_family": b.get("visual_family")} for b in plan.get("beats", [])] if proof else []
    inserts_delivered = [{k: r.get(k) for k in ("start", "end", "asset", "reason")} for r in plan.get("inserts", [])] if proof else []
    lost = gs.get("words_lost_vs_edited") or []
    # Older gate summaries (no lost_words_fail) keep the strict rule: any lost word fails.
    words_fail = bool(gs.get("lost_words_fail", bool(lost)))
    failed_checks = [k for k, v in rs["checks"].items() if v is False]
    mg = rs.get("motion_layer")
    if isinstance(mg, dict):
        failed_checks += [f"motion: {k}" for k in ("no_motion_outside_planned_windows", "captions_suppressed_where_declared", "motion_check_pass")
                          if mg.get(k) is False]
        failed_checks += [f"motion: {k} not shown" for d in ("beats_show_motion", "inserts_show_media") for k, v in (mg.get(d) or {}).items() if not v]
    return {
        "project_id": run["project"],
        "final": {"resolution": f"{rs['width']}x{rs['height']}", "codec": "H.264 video + AAC audio (James' encode.py)",
                  "duration_s": rs["duration_s"], "frames": rs["frames"], "fps": rs["fps"], "bytes": rs["final_bytes"],
                  "sha256": rs["final_sha256"], "full_decode": rs["checks"]["full_decode"]},
        "crop": {"setups": [{k: s[k] for k in ("setup", "segments", "crop", "zoom", "detected", "samples", "pass", "flags")} for s in cs["setups"]],
                 "face_inside_crop_all_samples": cs["pass"], "flags": cs["flags"],
                 "crop_matches_ledger_in_decoded_pixels": rs["checks"]["crop_matches_ledger"],
                 "basis": "[x, y, w, h] source-pixel crop, fixed per setup; faces checked on sampled frames (YuNet) with a 15% margin and above the caption band."},
        "captions": {"cues": rs["captions"]["cues"], "words": rs["captions"]["words"], "frames_with_caption": rs["captions"]["frames_with_cue"],
                     "font": rs["captions"]["font"], "caption_band_changes_with_cues": rs["checks"]["caption_bounds_and_band"],
                     "word_source": "Transcriber ASR of the edited audio (apply_cuts)"},
        "delivery_gate": {"pass": bool(gs.get("delivery_gate_pass")) and not words_fail and not failed_checks,
                          "audio_gate_script_pass": bool(gs.get("delivery_gate_pass")),
                          "reason": ((f"{gs.get('lost_words_reason') or str(len(lost or [])) + ' word(s) lost'}: {' '.join(lost[:20])}; ") if words_fail else
                                     (f"{len(lost)} word(s) missed by the final ASR pass, scattered (ASR variance; the final audio is the "
                                      f"edited WAV re-encoded, custody by source-region correlation): {' '.join(lost[:20])}; " if lost else ""))
                                    + (gate_error or gs.get("error") or "all delivery evidence present and fresh")
                                    + (f" (failing picture checks: {', '.join(failed_checks)}; see pixel_check_json)" if failed_checks else ""),
                          "failed_checks": failed_checks,
                          "words_lost_vs_edited_audio": lost, "words_added_vs_edited_audio": gs.get("words_added_vs_edited"),
                          "words_lost_located": gs.get("words_lost_located") or [],
                          "asr_variance": gs.get("asr_variance") or [],
                          "lost_words_rule": f"fail when more than {gs.get('lost_words_limit', 3)} (max(3, 5% of words)) are lost or 3 lost words fall within 2 s",
                          "asr_spelling_variants": gs.get("asr_spelling_variants") or [],
                          "fillers_heard_in_final_only": gs.get("fillers_heard_in_final_only") or [],
                          "min_source_region_correlation": rs["checks"]["min_source_region_correlation"],
                          "scope": "James' audio_gate.py --stage delivery: evidence completeness, custody and thresholds. Final acoustic-window findings are app-written; it is not human viewing or listening approval."},
        "motion_graphics": rs["motion_layer"],
        "saved_to_files": files,
        "downloads": downloads,
        "auth_note": "Downloads need 'Authorization: Bearer ***' when the app has a token set." if TOKEN else None,
        "render_seconds": round(time.monotonic() - t0, 1),
        "stage_seconds": {st["stage"]: st.get("elapsed_s") for st in run.get("steps", [])},
        "final_render_phase_seconds": rs.get("phase_seconds"),
        "jobs": {"face_crop": crop["id"], "final_render": render["id"], "final_asr": fasr["id"], "final_scan": fscan["id"],
                 "delivery_gate": gate_job["id"] if gate_job else None},
        "beats_delivered": beats_delivered,
        "inserts_delivered": inserts_delivered,
        "next": ("Tell the owner in plain words: resolution, duration, the motion beats and inserts delivered (beats_delivered: time "
                 "and what each shows; say so plainly if this render is plain and why), caption count, how the speaker is framed (if a "
                 "crop flag appears, look at several frames across the video before judging it), delivery gate pass/fail with the "
                 "reason, any words lost, and where the video is (saved_to_files.where_to_tell_the_owner, else the final_mp4 link). "
                 "Ask them to watch it on a phone before posting. Do not call the video approved."),
    }


# ---------- MCP tools ----------

mcp = MCPServer("defleur-video", version=VERSION, instructions=(
    "DeFleur Video edits talking-head videos on the owner's own server into finished 1080x1920 shorts WITH motion graphics. "
    "Start with workflow_guide(agent_harness, agent_model) and follow its agent_check: if it asks for owner confirmation, show its warning and wait for a yes. "
    "Default flow: capabilities -> list_files -> import_file -> start_edit -> get_status -> draft cuts AND a motion plan -> ONE owner approval "
    "for both -> apply_cuts -> get_status -> submit_motion -> capture_motion smoke -> look -> proof -> look -> render_final({'motion': true}) -> "
    "get_status (live progress) -> report the beats delivered and where the MP4 is (Files -> Videos -> Edited). Render plain ({}) only if the "
    "owner asks, the Browser app is missing, or capture keeps failing, and say why. Editing judgment: SKILL.md (resource defleur-video://SKILL.md)."))


SKILL_FILE = Path(__file__).with_name("SKILL.md")


@mcp.resource("defleur-video://SKILL.md", name="SKILL.md", title="DeFleur Video editing skill", mime_type="text/markdown",
              description="Editing judgment for DeFleur Video (Agent Skills format): agent check, combined cut + motion approval, gates, report.")
def skill_md() -> str:
    return SKILL_FILE.read_text()


def _result(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ToolError as e:
        return {"error": str(e)}


@mcp.tool(description=(
    "Call this FIRST when the user wants to edit a video, with agent_harness = the agent harness you run in (e.g. 'Hermes Agent', "
    "'Claude Code', 'Cursor') and agent_model = your exact model id. Returns agent_check (intended setup: Hermes Agent + Claude Opus 5.5; "
    "if requires_owner_confirmation, show the owner its warning and wait for a yes before importing), the default edit (approved cuts "
    "+ motion graphics + captions + crop), the exact tool order (one combined cut + motion-plan approval, then apply_cuts, submit_motion, "
    "capture_motion smoke/proof, render_final({'motion': true})), James DeFleur's motion_contract, limits and what is not automated."))
def workflow_guide(ctx: Context, agent_harness: str | None = None, agent_model: str | None = None) -> dict:
    return {"agent_check": agent_check(agent_harness, agent_model, client_from(ctx)), **GUIDE}


@mcp.tool(description=(
    "Check the app is ready before editing (second step, after workflow_guide). Reports app version, limits, whether the "
    "Transcriber app is reachable and has its speech model installed, whether the Browser app (needed only for motion graphics) "
    "is reachable, whether the shared Files folder is readable/writable (files), alignment model cache, host RAM / free disk / "
    "per-job estimates, and the exact fix to relay to the owner when something is broken."))
def capabilities() -> dict:
    def go():
        caps = api("GET", "/v1/capabilities")
        wf = caps["workflow"]
        t = wf.get("transcriber", {})
        if not t.get("configured", True):
            fix = f"Transcriber settings invalid: {t.get('error')}. Set TRANSCRIBER_URL in this app's Runtipi settings."
        elif not t.get("reachable"):
            fix = ("Install and start the Transcriber app from the Wizard App Store on this same Runtipi server (it answers as "
                   "http://transcriber:8000), or set TRANSCRIBER_URL in DeFleur Video's settings to where it runs.")
        elif not t.get("model_installed"):
            fix = (f"The Transcriber is up but model '{t.get('model')}' is not installed. Download it in the Transcriber app "
                   f"(POST /v1/models/{t.get('model')} on the Transcriber), or set TRANSCRIBER_MODEL here to an installed model.")
        else:
            fix = None
        al = wf.get("alignment", {})
        b = wf.get("motion", {}).get("browser", {})
        browser = {**b, "fix": None if b.get("reachable") else ("Install the Browser app from the Wizard App Store on this same Runtipi server "
                                                                   "(it answers as http://browser:9222), or set BROWSER_URL in DeFleur Video's settings."),
                   "needed_for": "motion graphics and fullscreen inserts only; plain render_final works without it"}
        files = {**(caps.get("media") or {}), "needed_for": "list_files, import_file and saving finished videos to Files -> Videos -> Edited; "
                                                           "create_upload works without it"}
        return {"version": caps["version"], "ready": fix is None, "transcriber": t, "fix": fix, "browser": browser, "files": files,
                "motion_ready": bool(b.get("reachable")) and bool(wf.get("motion", {}).get("gsap_present")),
                "resources": wf.get("resources"),
                "alignment": {"model": al.get("model"), "cached": al.get("cached"),
                              "note": None if al.get("cached") else "First alignment downloads the Whisper checkpoint (needs internet once, ~1-2 GB for turbo)."},
                "limits": caps["limits"], "not_built_yet": NOT_BUILT, "ai_calls": False}
    return _result(go)


@mcp.tool(description=(
    "Fallback when the video is not in the Files app (prefer list_files + import_file): get a one-time upload URL (expires in 30 minutes) plus an exact curl command for the owner's video file, "
    "and the browser upload page URL. Video bytes never go through MCP. Run the curl command yourself if you have the file on "
    "a machine that can reach this server, or give it to the owner. The upload answers with JSON containing the project id "
    "('id'); pass it to start_edit. HEVC/variable-frame-rate phone footage is converted to H.264 constant frame rate on upload."))
def create_upload(ctx: Context) -> dict:
    def go():
        base = base_url(ctx)
        u = api("POST", "/v1/uploads", {})
        url = base + u["path"]
        return {"upload_url": url, "expires_in_s": u["expires_in_s"], "one_time": True,
                "curl": f"curl -fS -X POST -H 'Content-Type: video/mp4' -T /path/to/video.mp4 '{url}'",
                "browser_page": base + "/upload",
                "accepts": "MP4/MOV with one video and one audio stream, at most 20 minutes and 8 GiB, up to 4K (normalized to 1080p for editing)",
                "next": "After the upload returns {\"id\": ...}, call start_edit(project_id=<id>). If this URL expires or was used, call create_upload again."}
    return _result(go)


@mcp.tool(description=(
    "Step 2 (normal path): list the video files in the owner's Files app (the shared folder on this server). folder is relative "
    "to Files, default 'Videos' (subfolders included, newest first; 'Videos/Edited' holds finished videos). Use it to find the file "
    "the owner named (e.g. IMG_5644.mov), then call import_file with its path. If Files is not available, the result says how to fix it."))
def list_files(folder: str = "Videos") -> dict:
    def go():
        try:
            r = api("GET", "/v1/media?" + urllib.parse.urlencode({"folder": folder}))
        except ToolError as e:
            if "404" in str(e):
                raise ToolError(f"folder '{folder}' not found in Files; try list_files('Videos') or list_files('')") from None
            raise
        r["next"] = ("Find the owner's file (match the name they gave, ignoring case) and call import_file(path=<its path>). "
                     "If it is not listed, ask the owner to put it in Files -> Videos." if r["files"] else
                     "No videos here. Ask the owner to upload the video into the Files app -> Videos, then call list_files again.")
        return r
    return _result(go)


@mcp.tool(description=(
    "Step 2 (normal path): make an edit project from a video in the owner's Files app. path is relative to Files, e.g. "
    "'Videos/IMG_5644.mov' (from list_files). The file is copied and checked exactly like an upload (limits: 20 min, 8 GiB; iPhone "
    ".mov, HEVC, HDR and variable frame rate are converted to 1080p H.264 constant frame rate); the original in Files is never "
    "changed. Absolute paths, '..', symlinks and non-regular files are refused. Large phone videos can take a few minutes to "
    "convert. Returns the project id ('id'); pass it to start_edit."))
def import_file(path: str) -> dict:
    def go():
        if not isinstance(path, str) or not path.strip():
            raise ToolError("path is required, e.g. 'Videos/IMG_5644.mov' (see list_files)")

        def work(run):
            run["step"] = "copy-check-convert"
            save(run)
            p = api("POST", "/v1/media/import", {"path": path}, timeout=7500)
            keep = ("id", "duration", "width", "height", "video_codec", "audio_codec", "imported_from", "normalization", "original")
            return {**{k: p.get(k) for k in keep if k in p}, "project_id": p["id"],
                    "next": f"Call start_edit(project_id='{p['id']}') (language optional)."}
        run = start_run("import_file", "files", {"path": path}, work)
        end = time.monotonic() + 50
        while time.monotonic() < end:
            r = load(run["id"])
            if r["state"] != "running":
                if r["state"] == "failed":
                    raise ToolError(r["error"].split(": ", 1)[-1])
                return r["result"]
            time.sleep(0.5)
        return {"run_id": run["id"], "state": "running",
                "next": f"Still converting (large phone videos take a few minutes). Call get_status('{run['id']}') until 'done'; "
                        "its result has the project id."}
    return _result(go)


@mcp.tool(description=(
    "Step 3: analyse an uploaded project. Runs source audio extraction, speech-to-text (Transcriber), preflight and local word "
    "alignment in the background and returns a run_id immediately. Then call get_status(run_id) repeatedly until state is "
    "'done'; the result has the transcript with word timings, filler / long-pause / repeat candidates, proposed_cuts and James "
    "DeFleur's editorial rules. IMPORTANT: draft the motion plan from the transcript too, show the owner the proposed cut list "
    "AND the motion plan in ONE question and get their approval (or changes) BEFORE calling apply_cuts. language is optional (e.g. 'en'); default is auto-detect."))
def start_edit(project_id: str, language: str | None = None) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex id returned by the upload")
        api("GET", f"/v1/projects/{project_id}")
        if language is not None and not re.fullmatch(r"[a-z]{2,3}", language):
            raise ToolError("language must be an ISO code such as 'en' or omitted for auto-detect")
        with LOCK:
            if runs_for(project_id, state="running"):
                raise ToolError("a run is already in progress for this project; call get_status(project_id)")
            run = start_run("start_edit", project_id, {"language": language}, do_start_edit)
        return {"run_id": run["id"], "state": "running",
                "next": f"Call get_status('{run['id']}') now and keep calling it until state is 'done' (each call waits up to ~55 s)."}
    return _result(go)


@mcp.tool(description=(
    "Step 6, only AFTER the owner approved the cut list (and motion plan) from start_edit. segments = the time ranges to REMOVE from the source, "
    "each {start_s, end_s, reason} in source seconds (start_edit's proposed_cuts already has this shape). Runs sample-exact "
    "audio assembly, per-edge cut audit, acoustic scan, re-transcription of the edited audio and the dialogue gate in the "
    "background; returns a run_id immediately. Keep calling get_status(run_id) until 'done' for the report: seconds removed, "
    "words lost/added vs the source, gate pass/fail with reasons and download URLs. segments=[] means NO cuts (keep the whole "
    "source, captions/framing only); use it to return to an uncut edit. The report's time_map converts source seconds to the "
    "edited seconds that submit_motion's plan uses."))
def apply_cuts(project_id: str, segments: list[dict], ctx: Context) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        done = runs_for(project_id, "start_edit", "done")
        if not done:
            raise ToolError("run start_edit for this project first and wait for it to finish (get_status)")
        edit = done[-1]["result"]
        cuts = clean_cuts(segments, edit["duration_s"])
        keeps_from(cuts, edit["duration_s"])
        with LOCK:
            if runs_for(project_id, state="running"):
                raise ToolError("a run is already in progress for this project; call get_status(project_id)")
            run = start_run("apply_cuts", project_id, {"cuts": cuts, "duration_s": edit["duration_s"], "edit": edit,
                                                       "base_url": base_url(ctx)}, do_apply_cuts)
        return {"run_id": run["id"], "state": "running", "cuts": cuts,
                "next": f"Call get_status('{run['id']}') now and keep calling it until state is 'done' (each call waits up to ~55 s)."}
    return _result(go)


def latest_cut(project_id: str) -> dict:
    cuts = runs_for(project_id, "apply_cuts", "done")
    if not cuts:
        raise ToolError("run apply_cuts for this project first and wait for it to finish (get_status)")
    return cuts[-1]


def latest_proof(project_id: str, cut_run: str) -> dict:
    current = api("GET", f"/v1/projects/{project_id}/motion")
    if not current.get("submitted"):
        raise ToolError("no motion composition submitted; call submit_motion first or render without {'motion': true}")
    for r in reversed(runs_for(project_id, "capture_motion", "done")):
        res = r["result"]
        if res["mode"] == "proof" and r["params"]["cut"]["run"] == cut_run:
            if res["composition_sha256"] != current["composition_sha256"]:
                raise ToolError("the composition changed after the last proof capture; run capture_motion(project_id, 'proof') again")
            if not res["pass"]:
                raise ToolError("the last proof capture did not pass; fix the composition and capture a proof again")
            return {"crop_job": res["crop_job"], "capture_job": res["capture_job"], "framing": res["framing"],
                    "plan": {k: current.get("plan", {}).get(k, []) for k in ("beats", "inserts")}}
    raise ToolError("no passing proof capture for the current cut; run capture_motion(project_id, 'smoke') then 'proof' first")


def check_framing(framing):
    if framing is None:
        return None
    if not isinstance(framing, dict) or set(framing) - {"targets", "new_setup_at"}:
        raise ToolError("framing must be {'targets': {'<kept segment index>': 'largest'|'left'|'right'|'center'}, 'new_setup_at': [index]}")
    return framing


@mcp.tool(description=(
    "Optional, after apply_cuts: preview the fixed 9:16 crop of every camera setup with face-audit evidence images, and choose "
    "which person each kept segment frames in a two-person shot. framing (optional): {'targets': {'<kept segment index>': "
    "'largest'|'left'|'right'|'center'}, 'new_setup_at': [kept segment index]}; segments are numbered from 0 in the kept "
    "order (apply_cuts reports kept_segments). Each setup gets ONE fixed crop (no animated pans, per James' contract); a "
    "change of target starts a new setup. Returns a run_id; call get_status until 'done', then look at each evidence_image."))
def preview_framing(project_id: str, ctx: Context, framing: dict | None = None) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        cut = latest_cut(project_id)
        with LOCK:
            if runs_for(project_id, state="running"):
                raise ToolError("a run is already in progress for this project; call get_status(project_id)")
            run = start_run("preview_framing", project_id, {"cut": {"jobs": cut["result"]["jobs"], "run": cut["id"]},
                                                            "framing": check_framing(framing), "base_url": base_url(ctx)}, do_preview_framing)
        return {"run_id": run["id"], "state": "running", "next": f"Call get_status('{run['id']}') until 'done'."}
    return _result(go)


@mcp.tool(description=(
    "Motion graphics step 1 (default for every DeFleur edit, after apply_cuts; James DeFleur's defleur-motion contract, condensed in workflow_guide.motion_contract). "
    "Upload YOUR composition for this project: files = {path: text} for index.html, .css, .js, .svg, .json, or "
    "{path: {'base64': ...}} for small .png/.jpg/.webp/.woff2 (use create_asset_upload for video clips and big images). "
    "plan = James' visual-plan: {'beats': [{start, end, spoken_anchor, viewer_inference, visual_family, state_before, "
    "state_after, causal_action, caption_treatment: 'show'|'suppress', speaker_return}], 'caption_suppress': [{start, end, "
    "reason}], 'inserts': [{start, end, asset, fit: 'cover'|'contain', clip_start_s, reason}]}, times in seconds of the EDITED "
    "video. index.html MUST load defleur/ledger.js (app-generated sourceFrameForOutputFrame + DEFLEUR data) and "
    "defleur/gsap.min.js (vendored GSAP 3.15.0), have <img id=\"live\"> and define window.renderFrame(t) as synchronous "
    "deterministic state reconstruction (paused GSAP timeline + seek); optional window.visualMode(t) and "
    "window.captionSuppressed(t). Every beat must make an explanatory change (cause->effect, state replacement, accumulation, "
    "topology change, comparison, return to source with new meaning), not a static title card. No network: everything local. "
    "replace (default true) drops earlier text files but keeps uploaded media. Then capture_motion 'smoke'."))
def submit_motion(project_id: str, files: dict, plan: dict, replace: bool = True) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        if runs_for(project_id, state="running"):
            raise ToolError("a run is in progress for this project; wait for it with get_status first")
        st = api("POST", f"/v1/projects/{project_id}/motion", {"files": files, "plan": plan, "replace": replace})
        return {**{k: v for k, v in st.items() if k != "plan"},
                "next": "Call capture_motion(project_id, 'smoke') and look at the returned frames. The capture checks the page contract at runtime and reports any error."}
    return _result(go)


@mcp.tool(description=(
    "Motion graphics: get a one-time upload URL (30 minutes) and curl command for ONE larger asset of the composition, e.g. a "
    "B-roll clip for a fullscreen insert or a big image. path is where it lands in the composition, e.g. 'assets/broll.mp4' "
    "(.mp4 up to 2 GiB; .png/.jpg/.webp up to 32 MiB; .woff2 up to 8 MiB). Reference it from index.html or plan.inserts[].asset. "
    "Bytes never go through MCP."))
def create_asset_upload(project_id: str, path: str, ctx: Context) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        u = api("POST", f"/v1/projects/{project_id}/asset-uploads", {"path": path})
        url = base_url(ctx) + u["path"]
        return {"upload_url": url, "asset_path": u["asset_path"], "expires_in_s": u["expires_in_s"], "max_bytes": u["max_bytes"],
                "curl": f"curl -fS -X POST -H 'Content-Type: application/octet-stream' -T /path/to/file '{url}'",
                "next": "After the upload answers 201, reference the asset_path in your composition or plan.inserts, then submit_motion."}
    return _result(go)


@mcp.tool(description=(
    "Motion graphics: capture the submitted composition with James' capture.cjs in the shared Browser app. mode 'smoke' = "
    "the first ~6 s; 'proof' = start, 0.25 s, end and the start/middle/end of every beat, plus James' reverse-seek determinism "
    "check (a mismatch fails). Returns a run_id; call get_status until 'done' for frame image URLs and a contact sheet. LOOK AT "
    "THEM before continuing. Needs the Browser app (capabilities shows it). framing as in preview_framing (optional)."))
def capture_motion(project_id: str, mode: str, ctx: Context, framing: dict | None = None) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        if mode not in ("smoke", "proof"):
            raise ToolError("mode must be 'smoke' or 'proof' (render_final does the full capture)")
        cut = latest_cut(project_id)
        st = api("GET", f"/v1/projects/{project_id}/motion")
        if not st.get("submitted"):
            raise ToolError("no motion composition submitted; call submit_motion first")
        with LOCK:
            if runs_for(project_id, state="running"):
                raise ToolError("a run is already in progress for this project; call get_status(project_id)")
            run = start_run("capture_motion", project_id, {"cut": {"jobs": cut["result"]["jobs"], "run": cut["id"]}, "mode": mode,
                                                           "composition_sha256": st["composition_sha256"], "framing": check_framing(framing),
                                                           "base_url": base_url(ctx)}, do_capture_motion)
        return {"run_id": run["id"], "state": "running", "next": f"Call get_status('{run['id']}') until 'done', then look at the frames."}
    return _result(go)


@mcp.tool(description=(
    "Step 9, after apply_cuts and a passing capture_motion 'proof'. Default options: {'motion': true} (motion graphics are the default "
    "DeFleur edit). Renders the finished vertical short in the background and "
    "returns a run_id: face audit and one fixed 9:16 crop per setup (centered and flagged if no face is found), burned-in "
    "captions from the edited-audio word timings (James' caption_layer.py), the 1080x1920 H.264/AAC encode and --verify-only "
    "(James' encode.py), full decode, decoded-pixel crop/caption checks, re-transcription of the final audio and James' "
    "delivery gate. Keep calling get_status(run_id) until 'done' for resolution, duration, crop summary, caption count, gate "
    "result, words lost, beats_delivered and download URLs. get_status shows live elapsed_s, sub_stage and estimate_remaining_s. "
    "options: {} = plain live footage + captions, ONLY when the owner asked for no motion, the Browser app is missing or capture keeps "
    "failing (pass 'plain_reason': '<why>' and tell the owner); "
    "{'motion': true} after a passing capture_motion 'proof' of the current composition (full capture of every frame, "
    "motion-window and caption-suppression checks); {'framing': {...}} as in preview_framing (with motion, the proof's "
    "framing is used)."))
def render_final(project_id: str, ctx: Context, options: dict | None = None) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        opts = options or {}
        if not isinstance(opts, dict) or set(opts) - {"motion", "framing", "plain_reason"}:
            raise ToolError("options may contain only 'motion' (bool), 'framing' (object) and 'plain_reason' (text)")
        cuts = runs_for(project_id, "apply_cuts", "done")
        if not cuts:
            raise ToolError("run apply_cuts for this project first and wait for it to finish (get_status)")
        cut = cuts[-1]
        proof = None
        if opts.get("motion"):
            proof = latest_proof(project_id, cut["id"])
            if opts.get("framing") and opts["framing"] != proof["framing"]:
                raise ToolError("framing differs from the proof capture's framing; capture a new proof with this framing")
        edits = runs_for(project_id, "start_edit", "done")
        lang = cut["params"]["edit"].get("language") or (edits[-1]["result"]["language"] if edits else "auto")
        with LOCK:
            if runs_for(project_id, state="running"):
                raise ToolError("a run is already in progress for this project; call get_status(project_id)")
            run = start_run("render_final", project_id, {"cut": {"jobs": cut["result"]["jobs"], "run": cut["id"]},
                                                         "language": lang, "base_url": base_url(ctx), "proof": proof,
                                                         "framing": opts.get("framing")}, do_render_final)
        out = {"run_id": run["id"], "state": "running", "from_apply_cuts_run": cut["id"], "motion": bool(proof),
               "next": f"Call get_status('{run['id']}') now and keep calling it until state is 'done' (each call waits up to ~55 s; "
                       "elapsed_s, sub_stage and estimate_remaining_s move while it works). "
                       + ("With motion, expect ~8 min of render per output minute on a 4-CPU server." if proof else
                          "Plain render: about 1.5-3x the video length.")}
        if not proof:
            out["plain_note"] = ("This is a PLAIN render (no motion graphics). Motion graphics are the default DeFleur edit: tell the owner "
                                 "why this one is plain" + (f" ({str(opts['plain_reason'])[:200]})" if opts.get("plain_reason") else
                                                            " (owner asked / Browser app missing / capture failed)") + ".")
        return out
    return _result(go)


# Rough share of a render_final run per app stage (measured on 4 vCPU); used only for a remaining-time hint.
RENDER_PLAN = ["face-crop", "final-render", "asr", "acoustic-scan", "delivery-gate", "save-to-files"]


def public_run(r: dict, now: float | None = None) -> dict:
    """Run status with LIVE timings: elapsed is computed at read time, not when the run file was last saved."""
    now = time.time() if now is None else now
    out = {k: r.get(k) for k in ("id", "kind", "project", "state", "step", "error")}
    running = r["state"] == "running"
    out["elapsed_s"] = round((now if running else (r.get("updated") or now)) - r["created"], 1)
    out["stages_done"] = [s["stage"] for s in r.get("steps", [])]
    if r["state"] == "done":
        out["result"] = r["result"]
    elif running:
        if r.get("stage_started"):
            out["step_elapsed_s"] = round(now - r["stage_started"], 1)
        prog = r.get("progress") or {}
        if prog:
            sub = {k: prog[k] for k in ("phase", "phases_done", "frames_total", "frames_captured") if k in prog}
            if prog.get("phase_elapsed_s") is not None:  # recomputed from the save time so it keeps moving between saves
                sub["phase_elapsed_s"] = round(prog["phase_elapsed_s"] + max(0.0, now - (r.get("updated") or now)), 1)
            out["sub_stage"] = sub
            if prog.get("estimate_remaining_s") is not None:
                left = max(0, round(prog["estimate_remaining_s"] - max(0.0, now - (r.get("updated") or now))))
                out["estimate_remaining_s"] = left
                out["estimate_note"] = "rough, from measured runs on a 4-vCPU server; final checks add ~1-2 min"
        if r.get("kind") == "render_final" and r.get("step") in RENDER_PLAN:
            out["stages_left"] = RENDER_PLAN[RENDER_PLAN.index(r["step"]) + 1:]
        what = r["step"] + (f" / {out['sub_stage']['phase']}" if out.get("sub_stage", {}).get("phase") else "")
        out["next"] = f"Still working on '{what}' (it is progressing; elapsed_s is live). Call get_status('{r['id']}') again."
    return out


@mcp.tool(description=(
    "Poll long work. Pass a run_id from start_edit/apply_cuts/render_final (waits up to wait_s, default 55, max 60, for it to finish), a "
    "project id (latest run plus project info) or a stage job id. While state is 'running', call get_status again: analysis "
    "and checks of a few minutes of video can take several minutes."))
def get_status(job_or_project: str, wait_s: float = 55) -> dict:
    def go():
        ident = (job_or_project or "").strip()
        wait = max(0.0, min(float(wait_s), 60.0))
        if RUN_ID.fullmatch(ident):
            end = time.monotonic() + wait
            r = load(ident)
            while r["state"] == "running" and time.monotonic() < end:
                time.sleep(1)
                r = load(ident)
            return public_run(r)
        if not ID.fullmatch(ident):
            raise ToolError("pass a run id (run-...), a project id or a job id")
        try:
            project = api("GET", f"/v1/projects/{ident}")
        except ToolError as e:
            if "404" not in str(e):
                raise
            job = api("GET", f"/v1/jobs/{ident}")
            return {"job": ident, "state": job["state"], "stage": job["plan"].get("workflow_stage", "preview"),
                    "error": job.get("error"), "summary": (job.get("result") or {}).get("summary")}
        runs = runs_for(ident)
        latest = public_run(runs[-1]) if runs else None
        if latest and latest.get("state") == "running" and wait:
            return get_status(latest["id"], wait)
        return {"project": {k: project.get(k) for k in ("id", "duration", "width", "height", "video_codec", "source_sha256", "normalization", "original")},
                "latest_run": latest, "runs": [{"id": r["id"], "kind": r["kind"], "state": r["state"]} for r in runs]}
    return _result(go)


@mcp.tool(description="List edit projects (id, duration, size, created, the Files path it was imported from) and the state of each project's latest run.")
def list_projects() -> dict:
    def go():
        rows = api("GET", "/v1/projects")["projects"]
        for p in rows:
            runs = runs_for(p["id"])
            p["latest_run"] = {"id": runs[-1]["id"], "kind": runs[-1]["kind"], "state": runs[-1]["state"]} if runs else None
        return {"projects": rows}
    return _result(go)


@mcp.tool(description="Permanently delete a project, its uploaded video and every derived file. Ask the owner first. Fails while a run is in progress.")
def delete_project(project_id: str) -> dict:
    def go():
        if not ID.fullmatch(project_id or ""):
            raise ToolError("project_id must be the 32-hex project id")
        if runs_for(project_id, state="running"):
            raise ToolError("a run is in progress for this project; wait for it with get_status first")
        api("DELETE", f"/v1/projects/{project_id}")
        for r in runs_for(project_id):
            run_path(r["id"]).unlink(missing_ok=True)
        return {"deleted": project_id}
    return _result(go)


if __name__ == "__main__":
    import uvicorn
    interrupted_runs()
    app = mcp.streamable_http_app(stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MCP_INTERNAL_PORT", "8788")), log_level="warning",
                access_log=False)
