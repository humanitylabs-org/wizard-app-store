#!/usr/bin/env python3
"""Three-container end-to-end through MCP only: the Transcriber, Browser and DeFleur Video
Runtipi recipes (real Runtipi 4.8.0 translation) on one shared network.

  upload the real-face fixture -> start_edit -> apply_cuts -> preview_framing (two setups)
  -> create_asset_upload (B-roll clip) -> submit_motion (small real GSAP composition: one
  explanatory beat with captions suppressed + one fullscreen insert) -> capture_motion smoke
  -> capture_motion proof -> render_final {'motion': true}

Checks: final 1080x1920 H.264/AAC decodes fully; motion pixels change only inside planned
windows; captions suppressed exactly where declared; capture determinism (reverse seeks);
no non-local requests; two fixed-crop setups with passing face audits; delivery gate passes;
no words lost. An independent face check confirms the insert replaced the speaker.

--long SECONDS builds a talking-head source of that length (default fixture looped) and runs
the same flow to measure the app's cgroup memory peak and wall time.
Reuses e2e-video-mcp.py / e2e-video-audio.py helpers. Needs Docker/Compose, node, internet.
"""
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("e2e_mcp", HERE / "e2e-video-mcp.py")
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)  # re-execs into an mcp-capable Python if needed
e2e, run, http_call, norm, IMAGE, OUT = m.e2e, m.run, m.http_call, m.norm, m.IMAGE, m.OUT
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

LONG = float(sys.argv[sys.argv.index("--long") + 1]) if "--long" in sys.argv else 0.0

STYLE = """html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#000}
#live{position:absolute;left:0;top:0;width:1080px;height:1920px}
.scene{position:absolute;left:120px;top:260px;width:840px;height:860px;visibility:hidden}
.card{position:absolute;inset:0;background:rgba(12,20,34,.86);border-radius:36px}
.label{position:absolute;left:60px;width:720px;color:#fff;font:700 64px/1.1 sans-serif}
"""
INDEX = """<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body>
<img id="live" alt="">
<div id="beat" class="scene"><div class="card"></div>
 <div class="label" id="before" style="top:70px">Raw take</div>
 <svg width="840" height="860" style="position:absolute;left:0;top:0">
  <rect x="80" y="300" width="160" height="420" fill="#e5484d" id="raw"/>
  <path id="arrow" d="M280 510 L540 510" stroke="#fff" stroke-width="18" fill="none" stroke-dasharray="260" stroke-dashoffset="260"/>
  <rect x="600" y="300" width="160" height="420" fill="#30a46c" id="clean" transform="scale(1,0)" style="transform-origin:680px 720px"/>
 </svg>
 <div class="label" id="after" style="top:760px;opacity:0">Clean cut</div>
</div>
<script src="defleur/ledger.js"></script><script src="defleur/gsap.min.js"></script><script src="main.js"></script>
</body></html>"""
MAIN = """// Explanatory beat: the raw take (red) routes through a cut (arrow) and becomes a clean take (green bar grows).
const B = window.DEFLEUR.beats[0];
const d = B.end - B.start;
const tl = gsap.timeline({paused: true});
tl.set('#beat', {visibility: 'hidden'}, 0)
  .set('#beat', {visibility: 'visible'}, B.start)
  .fromTo('#arrow', {attr: {'stroke-dashoffset': 260}}, {attr: {'stroke-dashoffset': 0}, duration: d * 0.35, ease: 'none'}, B.start + d * 0.1)
  .fromTo('#raw', {opacity: 1}, {opacity: 0.25, duration: d * 0.3, ease: 'none'}, B.start + d * 0.3)
  .fromTo('#clean', {scaleY: 0}, {scaleY: 1, duration: d * 0.4, ease: 'none'}, B.start + d * 0.35)
  .fromTo('#after', {opacity: 0}, {opacity: 1, duration: d * 0.2, ease: 'none'}, B.start + d * 0.55)
  .set('#beat', {visibility: 'hidden'}, B.end);
window.renderFrame = (t) => { tl.seek(t, false); };
"""


def broll(path):
    """A 3 s 1280x720 synthetic B-roll clip (lavfi test pattern, no face)."""
    e2e.ff("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-preset", "veryfast", "-movflags", "+faststart", path.name, cwd=path.parent)
    os.chmod(path, 0o666)


def long_fixture(fixture, seconds):
    """Loop the real-face talking fixture to `seconds` (re-encoded, CFR, 1080p)."""
    out = fixture / f"talking-{int(seconds)}s.mp4"
    if not out.is_file():
        base = m.face_fixture(fixture)
        e2e.ff("ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", base.name, "-t", str(seconds), "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "22", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
               "-movflags", "+faststart", out.name, cwd=fixture)
        os.chmod(out, 0o666)
    return out


def plan_for(words, duration):
    """One explanatory beat over the first spoken phrase (captions suppressed: the card says it), one insert later."""
    ws = [w for w in words if w["end"] > w["start"]]
    a, b = ws[1]["start"], ws[min(len(ws) - 1, 5)]["end"]
    beat_start, beat_end = round(max(0.3, a - 0.1), 3), round(min(duration - 2.5, b + 0.2), 3)
    ins_start = round(beat_end + 0.8, 3)
    ins_end = round(min(duration - 0.6, ins_start + 1.4), 3)
    assert beat_end - beat_start > 1.0 and ins_end - ins_start > 0.8, (beat_start, beat_end, ins_start, ins_end, duration)
    spoken = " ".join(w["word"].strip() for w in ws if beat_start <= w["start"] and w["end"] <= beat_end)
    beat = {"start": beat_start, "end": beat_end, "spoken_anchor": spoken or "test of the video editor",
            "viewer_inference": "a messy take becomes a clean one by cutting",
            "visual_family": "diagram", "state_before": "red bar: raw take with a filler", "state_after": "green bar: clean take",
            "causal_action": "the cut (arrow) routes the raw take into the clean take", "caption_treatment": "suppress",
            "speaker_return": "card disappears and the speaker returns full frame"}
    sup = {"start": round(beat_start + 0.2, 3), "end": round(beat_end - 0.05, 3),
           "reason": "the card's labels carry the spoken idea; captions would collide with it"}
    ins = {"start": ins_start, "end": ins_end, "asset": "assets/broll.mp4", "fit": "cover", "clip_start_s": 0.5,
           "reason": "fullscreen B-roll illustrating the edit"}
    return {"beats": [beat], "caption_suppress": [sup], "inserts": [ins]}


async def flow(url, fixture, truth, report):
    tool, wait_run = m.tool, m.wait_run
    expected = {norm(w) for k, v in e2e.PARTS if k == "speech" for w in v.split()} - {"um"}
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name: t.description or "" for t in (await s.list_tools()).tools}
            for name in ("submit_motion", "capture_motion", "create_asset_upload", "preview_framing"):
                assert name in tools, tools
            assert "renderFrame" in tools["submit_motion"] and "explanatory" in tools["submit_motion"]
            guide = await tool(s, "workflow_guide")
            mc = guide["motion_contract"]
            assert "#live" in json.dumps(mc) or 'id=\\"live\\"' in json.dumps(mc)
            assert "sourceFrameForOutputFrame" in json.dumps(mc) and "captionSuppressed" in json.dumps(mc) and "visualMode" in json.dumps(mc)
            assert any("proof" in x for x in mc["sequence"])
            caps = await tool(s, "capabilities")
            report["capabilities"] = {k: caps.get(k) for k in ("version", "ready", "motion_ready", "browser", "resources", "limits")}
            assert caps["ready"] and caps["motion_ready"] and caps["browser"]["reachable"], caps

            up = await tool(s, "create_upload")
            src = long_fixture(fixture, LONG) if LONG else m.face_fixture(fixture)
            t0 = time.monotonic()
            project = m.curl_upload(up["curl"], src)
            pid = project["id"]
            report["upload"] = {"seconds": round(time.monotonic() - t0, 2), "duration": project["duration"], "source": src.name}
            log = []
            timings = {}
            t0 = time.monotonic()
            edit = await wait_run(s, (await tool(s, "start_edit", {"project_id": pid, "language": "en"}))["run_id"], log, budget=7200)
            timings["start_edit"] = round(time.monotonic() - t0, 1)
            cuts = edit["proposed_cuts"]
            assert cuts
            t0 = time.monotonic()
            cut = await wait_run(s, (await tool(s, "apply_cuts", {"project_id": pid, "segments": cuts}))["run_id"], log, budget=7200)
            timings["apply_cuts"] = round(time.monotonic() - t0, 1)
            assert cut["dialogue_gate"]["pass"] and not cut["words_lost_vs_source"], cut["dialogue_gate"]
            report["apply_cuts"] = {k: cut[k] for k in ("seconds_removed", "edited_duration_s", "kept_segments", "words_lost_vs_source")}
            edited = json.loads(http_call("GET", cut["downloads"]["edited_transcript_json"])[1])
            words = [{"word": x["word"], "start": float(x["start"]), "end": float(x["end"])} for x in edited["words"]]
            duration = float(cut["edited_duration_s"])

            # Per-setup reframing: force a second fixed-crop setup at kept segment 1.
            framing = {"new_setup_at": [1]} if cut["kept_segments"] >= 2 else {}
            t0 = time.monotonic()
            fr = await wait_run(s, (await tool(s, "preview_framing", {"project_id": pid, "framing": framing}))["run_id"], log)
            timings["preview_framing"] = round(time.monotonic() - t0, 1)
            report["framing"] = {"framing": framing, "setups": [{k: x[k] for k in ("setup", "segments", "crop", "pass", "flags")} for x in fr["setups"]],
                                 "pass": fr["face_inside_crop_all_samples"]}
            assert fr["face_inside_crop_all_samples"] and (len(fr["setups"]) >= 2 if framing else True), report["framing"]
            assert http_call("GET", fr["setups"][0]["evidence_image"])[1][:4] == b"\x89PNG"

            # Fullscreen insert media through the one-time asset upload.
            clip = fixture / "broll.mp4"
            if not clip.is_file():
                broll(clip)
            au = await tool(s, "create_asset_upload", {"project_id": pid, "path": "assets/broll.mp4"})
            out = subprocess.run(["sh", "-c", au["curl"].replace("/path/to/file", str(clip))], capture_output=True, text=True, timeout=300)
            assert out.returncode == 0, out.stderr
            plan = plan_for(words, duration)
            if LONG:  # also exercise a second beat window? keep one beat; long runs measure resources
                pass
            files = {"index.html": INDEX, "style.css": STYLE, "main.js": MAIN}
            sub = await tool(s, "submit_motion", {"project_id": pid, "files": files, "plan": plan})
            report["motion_plan"] = plan
            assert sub["submitted"] and sub["inserts"] == 1

            res = {}
            for mode in ("smoke", "proof"):
                t0 = time.monotonic()
                c = await wait_run(s, (await tool(s, "capture_motion", {"project_id": pid, "mode": mode, "framing": framing}))["run_id"], log, budget=3600)
                timings[f"capture_{mode}"] = round(time.monotonic() - t0, 1)
                res[mode] = {k: c[k] for k in ("pass", "frames_captured", "determinism", "page_errors", "blocked_requests", "checks", "capture_seconds")}
                img = http_call("GET", c["frame_images"][0]["url"])[1]
                sheet = http_call("GET", c["contact_sheet"])[1]
                res[mode]["frame_image_png"] = img[:4] == b"\x89PNG"
                res[mode]["contact_sheet_png"] = sheet[:4] == b"\x89PNG"
                assert c["pass"] and not c["page_errors"] and not c["blocked_requests"], res[mode]
                assert c["determinism"]["reverse_seek_frames_checked"] > 0
            report["captures"] = res

            t0 = time.monotonic()
            final = await wait_run(s, (await tool(s, "render_final", {"project_id": pid, "options": {"motion": True, "framing": framing}}))["run_id"],
                                   log, budget=14400)
            timings["render_final"] = round(time.monotonic() - t0, 1)
            mp4 = fixture / "final-motion.mp4"
            mp4.write_bytes(http_call("GET", final["downloads"]["final_mp4"], timeout=600)[1])
            os.chmod(mp4, 0o666)
            assert hashlib.sha256(mp4.read_bytes()).hexdigest() == final["final"]["sha256"]
            probe = json.loads(e2e.ff("ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", mp4.name, cwd=fixture))
            vid = next(x for x in probe["streams"] if x["codec_type"] == "video")
            aud = next(x for x in probe["streams"] if x["codec_type"] == "audio")
            e2e.ff("ffmpeg", "-v", "error", "-xerror", "-i", mp4.name, "-f", "null", "-", cwd=fixture)
            mcheck = json.loads(http_call("GET", final["downloads"]["pixel_check_json"])[1])
            ledger = json.loads(http_call("GET", final["downloads"]["crop_ledger_json"])[1])
            mg = final["motion_graphics"]
            # Independent check: a face is visible mid-beat-free live frame, not mid-insert.
            fps = 30.0
            ins = plan["inserts"][0]
            live_t = min(duration - 0.3, ins["end"] + 0.3) if ins["end"] + 0.3 < duration else 0.15
            faces = json.loads(run("docker", "run", "--rm", "--network", "none", "--read-only", "--mount",
                                   f"type=bind,source={fixture},target=/w,readonly", "--entrypoint", "/opt/venv/bin/python",
                                   IMAGE, "-I", "-c", FACE_AT, "/w/" + mp4.name,
                                   str(round((ins["start"] + ins["end"]) / 2 * fps)), str(round(0.15 * fps)), str(round(live_t * fps))))
            report["render_final"] = {
                "final": final["final"], "crop": final["crop"], "captions": final["captions"], "delivery_gate": final["delivery_gate"],
                "motion_graphics": {k: v for k, v in mg.items() if k != "caption_suppress"} if isinstance(mg, dict) else mg,
                "independent_probe": [vid["codec_name"], vid["width"], vid["height"], vid["nb_read_frames"], aud["codec_name"]],
                "motion_check": {k: mcheck[k] for k in ("pass", "no_motion_outside_planned_windows", "beats_show_motion", "inserts_show_media",
                                                         "caption_band_changes_with_cues", "captions_suppressed_where_declared",
                                                         "suppressed_samples_with_speech", "live_max_capture_vs_base", "encode_matches_capture",
                                                         "caption_band_changed_fraction")},
                "ledger": {"ranges": [{k: r.get(k) for k in ("start", "end", "setup", "crop")} for r in ledger["ranges"]],
                           "setups": sorted({r["setup"] for r in ledger["ranges"]}), "fullscreen_exceptions": ledger["fullscreen_exceptions"]},
                "independent_face_check": faces}
            assert (vid["codec_name"], vid["width"], vid["height"], aud["codec_name"]) == ("h264", 1080, 1920, "aac")
            assert int(vid["nb_read_frames"]) == final["final"]["frames"]
            assert mcheck["pass"] and mcheck["no_motion_outside_planned_windows"] and all(mcheck["beats_show_motion"].values())
            assert all(mcheck["inserts_show_media"].values()) and mcheck["captions_suppressed_where_declared"]
            assert mcheck["caption_band_changes_with_cues"] and mcheck["suppressed_samples_with_speech"] > 0
            cb = mcheck["caption_band_changed_fraction"]
            assert cb["suppressed_cue_on"] == 0 and cb["suppressed_max"] < cb["cue_on_min"] / 3, cb
            assert final["delivery_gate"]["pass"] and final["delivery_gate"]["words_lost_vs_edited_audio"] == [], final["delivery_gate"]
            assert len(ledger["fullscreen_exceptions"]) == 1 and len({r["setup"] for r in ledger["ranges"]}) >= (2 if framing else 1)
            assert faces["insert"] is None and faces["live"] is not None, faces
            if not LONG:
                got = {norm(x["word"]) for x in words}
                assert not (expected - got), sorted(expected - got)
            mp4.unlink()
            report["timings_s"] = timings
            report["final_frames"] = final["final"]["frames"]
            report["runs"] = log
            await tool(s, "delete_project", {"project_id": pid})


FACE_AT = r"""
import cv2, json, subprocess, sys, numpy as np
path, picks = sys.argv[1], [int(x) for x in sys.argv[2:]]
d = cv2.FaceDetectorYN.create("/opt/models/yunet.onnx", "", (540, 960), 0.6)
out = {}
for name, f in zip(("insert", "start", "live"), picks):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select='eq(n\,{f})',scale=540:960", "-fps_mode", "passthrough",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], check=True, capture_output=True).stdout
    _, faces = d.detect(np.frombuffer(raw, np.uint8).reshape(960, 540, 3))
    out[name] = None if faces is None else [round(float(v) * 2) for v in max(faces, key=lambda r: r[2] * r[3])[:4]]
print(json.dumps(out))
"""


def main():
    name = "defleur-motion-" + secrets.token_hex(4)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"test": "MCP-only motion flow: Transcriber + Browser + DeFleur Video translated Runtipi recipes on one network",
              "image": IMAGE, "long_source_s": LONG or None}
    t_all = time.monotonic()
    tc, bc, vc = e2e.translate("transcriber"), e2e.translate("browser"), e2e.translate("defleur-video")
    ts, bs, vs = tc["services"]["transcriber"], bc["services"]["browser"], vc["services"]["defleur-video"]
    for c in (tc, bc, vc):
        c["networks"]["tipi_main_network"] = {"name": name, "external": True}
    ts["ports"], vs["ports"], bs["ports"] = ["127.0.0.1::8000"], ["127.0.0.1::8787"], ["127.0.0.1::9222"]
    vs["image"], vs["pull_policy"] = IMAGE, "never"
    report["browser_image"] = bs["image"]
    cache = os.environ.get("E2E_CACHE")
    work = Path(tempfile.mkdtemp(prefix=name + "-", dir=os.environ.get("TMPDIR")))
    tdata = Path(cache) / "transcriber" if cache else work / "transcriber"
    vdata, bdata = work / "video", work / "browser"
    for d in (tdata, vdata, bdata):
        d.mkdir(parents=True, exist_ok=True)
    if cache:
        (Path(cache) / "models").mkdir(exist_ok=True)
        os.chmod(Path(cache) / "models", 0o777)
        vs["volumes"].append(f"{Path(cache) / 'models'}:/data/models")
    model = json.loads((e2e.ROOT / "apps/transcriber/config.json").read_text())["form_fields"][0]["default"]
    browser_default = next(f["default"] for f in json.loads((e2e.ROOT / "apps/defleur-video/config.json").read_text())["form_fields"]
                           if f["env_variable"] == "BROWSER_URL")
    venv = {**os.environ, "APP_DATA_DIR": str(vdata), "TRANSCRIBER_URL": "http://transcriber:8000", "TRANSCRIBER_MODEL": model,
            "BROWSER_URL": browser_default}
    tenv = {**os.environ, "APP_DATA_DIR": str(tdata), "TRANSCRIBER_MODEL": model}
    benv = {**os.environ, "APP_DATA_DIR": str(bdata)}
    cmds = {}
    for key, c in (("t", tc), ("b", bc), ("v", vc)):
        (work / f"{key}.json").write_text(json.dumps(c))
        cmds[key] = ["docker", "compose", "-p", f"{name}-{key}", "-f", str(work / f"{key}.json")]

    def chmod(app_dir, image):
        run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount", f"type=bind,source={app_dir},target=/fixture",
            "--entrypoint", "/bin/chmod", image, "-Rf", "a+rwx", "/fixture")

    def ready(cmd, env, svc, port, path, deadline_s):
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            try:
                base = "http://127.0.0.1:" + run(*cmd, "port", svc, str(port), env=env).rsplit(":", 1)[1]
                if http_call("GET", base + path, timeout=5)[0] == 200:
                    return base
            except Exception:
                pass
            time.sleep(2)
        print(run(*cmd, "logs", "--no-color", "--tail", "60", env=env), file=sys.stderr)
        raise RuntimeError(svc + " did not become healthy")

    run("docker", "network", "create", name)
    peaks = {}
    try:
        run(*cmds["t"], "up", "-d", env=tenv)
        chmod(tdata, ts["image"])
        run(*cmds["b"], "up", "-d", env=benv)
        run(*cmds["v"], "up", "-d", env=venv)
        chmod(vdata, IMAGE)
        vcid, bcid = run(*cmds["v"], "ps", "-aq", env=venv), run(*cmds["b"], "ps", "-aq", env=benv)
        ready(cmds["t"], tenv, "transcriber", 8000, "/health", 900)
        ready(cmds["b"], benv, "browser", 9222, "/json/version", 60)
        vbase = ready(cmds["v"], venv, "defleur-video", 8787, "/healthz", 60)
        fixture, truth = e2e.build_fixture(ts["image"], tdata)
        peaks = {"video": e2e.Peak(vcid), "browser": e2e.Peak(bcid)}
        for p in peaks.values():
            p.start()
        t0 = time.monotonic()
        asyncio.run(flow(vbase + "/mcp", fixture, truth, report))
        report["mcp_flow_wall_s"] = round(time.monotonic() - t0, 1)
        report["wall_time_s"] = round(time.monotonic() - t_all, 1)
        time.sleep(1.5)
        report["memory"] = {k: {"cgroup_peak_bytes": p.peak, "max_sampled_current_bytes": p.max_current} for k, p in peaks.items()}
        report["memory"]["video"]["limit_bytes"] = json.loads(run("docker", "inspect", vcid))[0]["HostConfig"]["Memory"]
        report["memory"]["browser"]["limit_bytes"] = json.loads(run("docker", "inspect", bcid))[0]["HostConfig"]["Memory"]
    finally:
        for p in peaks.values():
            p.stop.set()
        for key, env in (("v", venv), ("b", benv), ("t", tenv)):
            if "--keep" not in sys.argv:
                logs = subprocess.run([*cmds[key], "logs", "--no-color", "--tail", "200"], env=env, capture_output=True, text=True).stdout
                (OUT / f"motion-{key}.log").write_text(logs)
                subprocess.run([*cmds[key], "down", "--remove-orphans"], env=env, capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        chmod(vdata, IMAGE)
        chmod(tdata, ts["image"])
        shutil.rmtree(work, ignore_errors=True)
        (OUT / ("motion-long-report.json" if LONG else "motion-report.json")).write_text(json.dumps(report, indent=2, default=str))
    keys = ("capabilities", "upload", "apply_cuts", "framing", "captures", "render_final", "timings_s", "mcp_flow_wall_s", "wall_time_s", "memory")
    print(json.dumps({k: report.get(k) for k in keys}, indent=2, default=str)[:12000])


if __name__ == "__main__":
    main()
