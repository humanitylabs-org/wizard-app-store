#!/usr/bin/env python3
"""End-to-end through MCP only: the Transcriber and DeFleur Video Runtipi recipes on one
shared network, real synthesized speech, and an agent's flow done purely with MCP tool calls
plus the curl upload that create_upload hands out:

  workflow_guide -> capabilities -> create_upload -> curl -> start_edit -> get_status...
  -> choose cuts from its candidates -> apply_cuts -> get_status... -> checks

Also uploads an HEVC variant of the fixture and proves it is normalized to H.264 CFR (with the
original's SHA-256 in provenance) and still transcribes. Reuses e2e-video-audio.py's fixture,
recipe translation and memory sampler. Needs the official `mcp` SDK client: set
E2E_MCP_PYTHON to a Python that has mcp>=2, or the script makes a venv with uv/pip.
"""
import asyncio
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


def ensure_mcp():
    try:
        import mcp.client.streamable_http  # noqa: F401
        return
    except ImportError:
        pass
    py = os.environ.get("E2E_MCP_PYTHON")
    if not py:
        venv = Path(os.environ.get("E2E_CACHE") or tempfile.gettempdir()) / "mcp-client-venv"
        py = str(venv / "bin/python")
        if not Path(py).is_file():
            if shutil.which("uv"):
                subprocess.run(["uv", "venv", "-q", "--python", sys.executable, str(venv)], check=True)
                subprocess.run(["uv", "pip", "install", "-q", "--python", py, "mcp==2.0.0"], check=True)
            else:
                subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
                subprocess.run([py, "-m", "pip", "install", "-q", "mcp==2.0.0"], check=True)
    os.execv(py, [py, *sys.argv])


ensure_mcp()
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

spec = importlib.util.spec_from_file_location("e2e_audio", HERE / "e2e-video-audio.py")
assert spec and spec.loader
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)
run, http_call, norm, IMAGE, OUT = e2e.run, e2e.http_call, e2e.norm, e2e.IMAGE, e2e.OUT


async def tool(session, name, args=None):
    res = await session.call_tool(name, args or {})
    data = json.loads(res.content[0].text)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{name}: {data['error']}")
    return data


async def wait_run(session, rid, log, budget=2400):
    end, calls = time.monotonic() + budget, 0
    while time.monotonic() < end:
        st = await tool(session, "get_status", {"job_or_project": rid})
        calls += 1
        if st["state"] == "done":
            log.append({"run": rid, "get_status_calls": calls, "elapsed_s": st["elapsed_s"], "stages": st["stages_done"]})
            return st["result"]
        if st["state"] == "failed":
            raise RuntimeError(f"run {rid} failed: {st['error']}")
    raise RuntimeError(f"run {rid} still running after {budget}s")


# Public-domain NASA portrait (Wikimedia Commons, "Ilan Ramon, NASA photo portrait in orange suit.jpg"), pinned by hash.
FACE_URL = "https://upload.wikimedia.org/wikipedia/commons/4/48/Ilan_Ramon%2C_NASA_photo_portrait_in_orange_suit.jpg"
FACE_SHA256 = "b30593be9af9ee744beaf48e6a00f5a3639d0e937a3ddc8ae92d4631da33f1c0"


def face_fixture(fixture):
    """1920x1080 talking-head: a real face photo, slowly panned and scaled, muxed with the real speech fixture."""
    out = fixture / "talking-1080p.mp4"
    if out.is_file():
        return out
    photo = fixture / "face.jpg"
    if not photo.is_file() or hashlib.sha256(photo.read_bytes()).hexdigest() != FACE_SHA256:
        data = http_call("GET", FACE_URL, headers={"User-Agent": "wizard-app-store-e2e/1.0 (CI fixture)"}, timeout=120)[1]
        assert hashlib.sha256(data).hexdigest() == FACE_SHA256, "face photo hash changed upstream"
        photo.write_bytes(data)
        os.chmod(photo, 0o666)
    graph = ("color=c=0x2b3440:s=1920x1080:r=30[bg];[0:v]scale=-2:880,format=yuv420p[p];"
             "[p]scale=w='trunc(iw*(1+0.03*sin(t*0.7))/2)*2':h=-2:eval=frame[s];"
             "[bg][s]overlay=x='560+60*sin(t*0.5)':y='120+15*sin(t*0.9)':shortest=1,format=yuv420p[v]")
    e2e.ff("ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-i", "face.jpg", "-i", "speech.wav",
           "-filter_complex", graph, "-map", "[v]", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "22", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
           "talking-1080p.mp4", cwd=fixture)
    return out


FACE_CHECK = r"""
import cv2, json, subprocess, sys, numpy as np
path, top = sys.argv[1], int(sys.argv[2])
n = int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                 "stream=nb_read_frames", "-of", "csv=p=0", path], text=True))
picks = [round(i * (n - 1) / 7) for i in range(8)]
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "select='" + "+".join(f"eq(n\,{i})" for i in picks) + "',scale=540:960",
                      "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], check=True, capture_output=True).stdout
d = cv2.FaceDetectorYN.create("/opt/models/yunet.onnx", "", (540, 960), 0.6)
rows = []
for k, f in enumerate(picks):
    img = np.frombuffer(raw[k * 540 * 960 * 3:(k + 1) * 540 * 960 * 3], np.uint8).reshape(960, 540, 3)
    _, faces = d.detect(img)
    box = None if faces is None else [float(v) * 2 for v in max(faces, key=lambda r: r[2] * r[3])[:4]]
    rows.append({"frame": f, "box": box, "inside_canvas": bool(box and box[0] >= 0 and box[1] >= 0 and box[0] + box[2] <= 1080 and box[1] + box[3] <= 1920),
                 "above_captions": bool(box and box[1] + box[3] <= top)})
print(json.dumps({"frames": n, "samples": rows}))
"""


def curl_upload(cmd_text, path):
    """Run the exact curl command create_upload returned, with the file path substituted."""
    assert cmd_text.count("/path/to/video.mp4") == 1, cmd_text
    out = subprocess.run(["sh", "-c", cmd_text.replace("/path/to/video.mp4", "'" + str(path) + "'")],
                         check=True, capture_output=True, text=True, timeout=900).stdout
    return json.loads(out)


async def flow(url, fixture, truth, report):
    expected = {norm(w) for k, v in e2e.PARTS if k == "speech" for w in v.split()} - {"um"}
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            tools = {t.name: t.description or "" for t in (await s.list_tools()).tools}
            report["server"] = {"name": init.server_info.name, "version": init.server_info.version, "tools": sorted(tools)}
            assert set(tools) == {"workflow_guide", "capabilities", "create_upload", "start_edit", "apply_cuts", "render_final",
                                  "get_status", "list_projects", "delete_project", "preview_framing", "submit_motion",
                                  "create_asset_upload", "capture_motion"}, tools
            assert "motion" in tools["render_final"].lower() and "1080x1920" in tools["render_final"]
            assert "approval" in tools["start_edit"] and "get_status" in tools["start_edit"]
            guide = await tool(s, "workflow_guide")
            assert "renderFrame" in json.dumps(guide["motion_contract"]) and not any("motion" in x.lower() and "not" in x.lower() for x in guide["not_built_yet"])
            assert not any("burned captions" in x.lower() or "1080x1920 encode" in x.lower() for x in guide["not_built_yet"]), guide["not_built_yet"]
            assert any("render_final" in x for x in guide["steps"])
            caps = await tool(s, "capabilities")
            report["capabilities"] = {k: caps[k] for k in ("version", "ready", "fix", "transcriber")}
            assert caps["ready"], caps

            # Upload: one-time URL + the exact curl command; bytes never go through MCP.
            up = await tool(s, "create_upload")
            t0 = time.monotonic()
            talking = face_fixture(fixture)
            report["face_fixture"] = {"sha256": hashlib.sha256(talking.read_bytes()).hexdigest(), "photo_sha256": FACE_SHA256,
                                      "photo": "NASA portrait of Ilan Ramon (public domain, Wikimedia Commons)", "size": "1920x1080"}
            project = curl_upload(up["curl"], talking)
            report["upload"] = {"seconds": round(time.monotonic() - t0, 2), "id": project["id"], "normalized": "normalization" in project}
            reuse = subprocess.run(["sh", "-c", up["curl"].replace("/path/to/video.mp4", str(fixture / "source.mp4"))], capture_output=True, text=True)
            assert reuse.returncode != 0 and "403" in reuse.stderr, "upload URL must be one-time"
            pid = project["id"]

            log = []
            t0 = time.monotonic()
            started = await tool(s, "start_edit", {"project_id": pid, "language": "en"})
            assert time.monotonic() - t0 < 100
            edit = await wait_run(s, started["run_id"], log)
            report["start_edit"] = {"seconds": round(time.monotonic() - t0, 1), "language": edit["language"], "transcript": edit["transcript"],
                                    "words": len(edit["words"]), "candidates": edit["candidates"], "proposed_cuts": edit["proposed_cuts"],
                                    "rules": len(edit["editorial_rules"])}
            # The agent's choice (stands in for owner approval): every filler/pause candidate start_edit proposed.
            cuts = edit["proposed_cuts"]
            assert cuts, "start_edit proposed no cuts for a clip with a filler and a 0.9 s pause"
            covers_um = any(c["start_s"] <= truth["um"]["start_s"] + 0.05 and c["end_s"] >= truth["um"]["end_s"] - 0.05 for c in cuts)
            report["chosen_cuts"] = {"segments": cuts, "covers_synthesized_um": covers_um}
            t0 = time.monotonic()
            applied = await tool(s, "apply_cuts", {"project_id": pid, "segments": cuts})
            assert time.monotonic() - t0 < 100
            result = await wait_run(s, applied["run_id"], log)
            report["apply_cuts"] = {"seconds": round(time.monotonic() - t0, 1),
                                    **{k: result[k] for k in ("seconds_removed", "source_duration_s", "edited_duration_s", "words_removed_by_cuts",
                                                              "words_lost_vs_source", "words_added_vs_source", "fillers_still_heard",
                                                              "cut_audit_pass", "dialogue_gate", "preview", "downloads")}}
            report["runs"] = log
            edited = json.loads(http_call("GET", result["downloads"]["edited_transcript_json"])[1])
            got = [norm(x["word"]) for x in edited["words"]]
            report["edited_asr"] = {"text": " ".join(got), "um_present": "um" in got, "missing": sorted(expected - set(got))}
            wav = http_call("GET", result["downloads"]["edited_audio_wav"])[1]
            report["edited_wav_bytes"] = len(wav)
            if "preview_9x16_mp4" in result["downloads"]:
                report["preview_bytes"] = len(http_call("GET", result["downloads"]["preview_9x16_mp4"])[1])
            assert result["dialogue_gate"]["pass"], result["dialogue_gate"]
            assert result["cut_audit_pass"]
            assert "um" not in got and not result["fillers_still_heard"], report["edited_asr"]
            assert not result["words_lost_vs_source"], result["words_lost_vs_source"]
            assert not (expected - set(got)), report["edited_asr"]
            assert result["seconds_removed"] > 0.5
            assert "render_final" in result["next"]

            # Piece 2: the finished vertical short through MCP only.
            t0 = time.monotonic()
            rendered = await tool(s, "render_final", {"project_id": pid})
            assert time.monotonic() - t0 < 100
            final = await wait_run(s, rendered["run_id"], log, budget=3600)
            render_s = round(time.monotonic() - t0, 1)
            mp4 = fixture / "final-from-mcp.mp4"
            mp4.write_bytes(http_call("GET", final["downloads"]["final_mp4"], timeout=300)[1])
            os.chmod(mp4, 0o666)
            assert hashlib.sha256(mp4.read_bytes()).hexdigest() == final["final"]["sha256"]
            probe = json.loads(e2e.ff("ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", mp4.name, cwd=fixture))
            vid = next(x for x in probe["streams"] if x["codec_type"] == "video")
            aud = next(x for x in probe["streams"] if x["codec_type"] == "audio")
            e2e.ff("ffmpeg", "-v", "error", "-xerror", "-i", mp4.name, "-f", "null", "-", cwd=fixture)  # full decode or raise
            ledger = json.loads(http_call("GET", final["downloads"]["crop_ledger_json"])[1])
            gate = json.loads(http_call("GET", final["downloads"]["delivery_gate_result_json"])[1])
            top = 1240  # James' neutral preset caption safe_rect top
            faces = json.loads(run("docker", "run", "--rm", "--network", "none", "--read-only", "--mount",
                                   f"type=bind,source={fixture},target=/w,readonly", "--entrypoint", "/opt/venv/bin/python",
                                   IMAGE, "-I", "-c", FACE_CHECK, "/w/" + mp4.name, str(top)))
            report["render_final"] = {
                "seconds": render_s, "final": final["final"], "crop": final["crop"], "captions": final["captions"],
                "delivery_gate": final["delivery_gate"], "motion_graphics": final["motion_graphics"],
                "independent_probe": {"video": [vid["codec_name"], vid["width"], vid["height"], vid["nb_read_frames"], vid["r_frame_rate"]],
                                      "audio": [aud["codec_name"], aud["sample_rate"], aud.get("duration")], "full_decode": True},
                "independent_face_check": faces, "ledger_ranges": len(ledger["ranges"]), "gate_file_pass": gate["pass"]}
            assert (vid["codec_name"], vid["width"], vid["height"], aud["codec_name"]) == ("h264", 1080, 1920, "aac"), report["render_final"]
            assert int(vid["nb_read_frames"]) == final["final"]["frames"]
            assert abs(final["final"]["duration_s"] - result["edited_duration_s"]) < 0.05
            assert final["crop"]["face_inside_crop_all_samples"] and not final["crop"]["flags"], final["crop"]
            assert final["crop"]["crop_matches_ledger_in_decoded_pixels"]
            assert all(r["box"] and r["inside_canvas"] and r["above_captions"] for r in faces["samples"]), faces
            assert final["captions"]["cues"] >= 2 and final["captions"]["caption_band_changes_with_cues"], final["captions"]
            assert final["delivery_gate"]["pass"] and gate["pass"], final["delivery_gate"]
            assert final["delivery_gate"]["words_lost_vs_edited_audio"] == [], final["delivery_gate"]
            mp4.unlink()

            # HEVC phone-style variant: normalized on upload, then editable.
            hevc = fixture / "source-hevc.mp4"
            if not hevc.is_file():
                e2e.ff("ffmpeg", "-v", "error", "-y", "-i", "source.mp4", "-c:v", "libx265", "-x265-params", "log-level=error",
                       "-tag:v", "hvc1", "-c:a", "copy", "source-hevc.mp4", cwd=fixture)
            up = await tool(s, "create_upload")
            t0 = time.monotonic()
            hp = curl_upload(up["curl"], hevc)
            st = await tool(s, "get_status", {"job_or_project": hp["id"], "wait_s": 0})
            report["hevc"] = {"upload_seconds": round(time.monotonic() - t0, 2), "project": st["project"],
                              "original_sha256_matches": st["project"]["original"]["sha256"] == hashlib.sha256(hevc.read_bytes()).hexdigest()}
            assert st["project"]["video_codec"] == "h264" and "HEVC video" in st["project"]["normalization"]["reasons"]
            assert st["project"]["normalization"]["frame_rate_mode"] == "constant" and report["hevc"]["original_sha256_matches"]
            started = await tool(s, "start_edit", {"project_id": hp["id"]})  # language auto-detected
            hedit = await wait_run(s, started["run_id"], log)
            hw = {norm(w[1]) for w in hedit["words"]}
            report["hevc"]["start_edit"] = {"language": hedit["language"], "transcript": hedit["transcript"], "missing": sorted(expected - hw)}
            assert hedit["language"] == "en" and len(expected - hw) <= 1, report["hevc"]

            projects = await tool(s, "list_projects")
            assert {pid, hp["id"]} <= {p["id"] for p in projects["projects"]}
            for p in (pid, hp["id"]):
                await tool(s, "delete_project", {"project_id": p})
            assert not (await tool(s, "list_projects"))["projects"]


def main():
    name = "defleur-mcp-" + secrets.token_hex(4)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"test": "MCP-only agent flow against two translated Runtipi recipes on one network; real speech", "image": IMAGE}
    t_all = time.monotonic()
    tc, vc = e2e.translate("transcriber"), e2e.translate("defleur-video")
    ts, vs = tc["services"]["transcriber"], vc["services"]["defleur-video"]
    for c in (tc, vc):
        c["networks"]["tipi_main_network"] = {"name": name, "external": True}
    ts["ports"], vs["ports"] = ["127.0.0.1::8000"], ["127.0.0.1::8787"]
    vs["image"], vs["pull_policy"] = IMAGE, "never"
    cache = os.environ.get("E2E_CACHE")
    work = Path(tempfile.mkdtemp(prefix=name + "-", dir=os.environ.get("TMPDIR")))
    tdata = Path(cache) / "transcriber" if cache else work / "transcriber"
    vdata = work / "video"
    tdata.mkdir(parents=True, exist_ok=True)
    vdata.mkdir()
    if cache:
        (Path(cache) / "models").mkdir(exist_ok=True)
        os.chmod(Path(cache) / "models", 0o777)
        vs["volumes"].append(f"{Path(cache) / 'models'}:/data/models")
    model = json.loads((e2e.ROOT / "apps/transcriber/config.json").read_text())["form_fields"][0]["default"]
    venv = {**os.environ, "APP_DATA_DIR": str(vdata), "TRANSCRIBER_URL": "http://transcriber:8000", "TRANSCRIBER_MODEL": model}
    tenv = {**os.environ, "APP_DATA_DIR": str(tdata), "TRANSCRIBER_MODEL": model}
    (work / "t.json").write_text(json.dumps(tc))
    (work / "v.json").write_text(json.dumps(vc))
    tcmd = ["docker", "compose", "-p", name + "-t", "-f", str(work / "t.json")]
    vcmd = ["docker", "compose", "-p", name + "-v", "-f", str(work / "v.json")]

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
    peak = None
    try:
        run(*tcmd, "up", "-d", env=tenv)
        chmod(tdata, ts["image"])
        run(*vcmd, "up", "-d", env=venv)
        chmod(vdata, IMAGE)
        vcid = run(*vcmd, "ps", "-aq", env=venv)
        ready(tcmd, tenv, "transcriber", 8000, "/health", 900)
        vbase = ready(vcmd, venv, "defleur-video", 8787, "/healthz", 60)
        fixture, truth = e2e.build_fixture(ts["image"], tdata)
        report["fixture"] = {"duration_s": truth["duration_s"], "um": truth["um"], "pause": truth["pause"]}
        peak = e2e.Peak(vcid)
        peak.start()
        t0 = time.monotonic()
        asyncio.run(flow(vbase + "/mcp", fixture, truth, report))
        report["mcp_flow_wall_s"] = round(time.monotonic() - t0, 1)
        report["wall_time_s"] = round(time.monotonic() - t_all, 1)
        time.sleep(1.5)
        report["video_memory"] = {"cgroup_peak_bytes": peak.peak, "max_sampled_current_bytes": peak.max_current,
                                  "limit_bytes": json.loads(run("docker", "inspect", vcid))[0]["HostConfig"]["Memory"]}
    finally:
        if peak:
            peak.stop.set()
        for cmd, env in ((vcmd, venv), (tcmd, tenv)):
            if "--keep" not in sys.argv:
                logs = subprocess.run([*cmd, "logs", "--no-color", "--tail", "200"], env=env, capture_output=True, text=True).stdout
                (OUT / f"{cmd[3]}.log").write_text(logs)
                subprocess.run([*cmd, "down", "--remove-orphans"], env=env, capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        chmod(vdata, IMAGE)
        chmod(tdata, ts["image"])
        shutil.rmtree(work, ignore_errors=True)
        (OUT / "mcp-report.json").write_text(json.dumps(report, indent=2, default=str))
    summary = {k: report.get(k) for k in ("server", "capabilities", "upload", "face_fixture", "chosen_cuts", "apply_cuts", "edited_asr",
                                          "render_final", "hevc",
                                          "runs", "mcp_flow_wall_s", "wall_time_s", "video_memory")}
    print(json.dumps(summary, indent=2, default=str)[:20000])


if __name__ == "__main__":
    main()
