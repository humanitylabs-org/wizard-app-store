#!/usr/bin/env python3
"""Real-file MCP flow: Files + Transcriber (real Speaches) + DeFleur Video, translated Runtipi recipes (as e2e-files-video.py).

Usage: e2e-real-source.py --real-source <path> [--name 'Videos/x.MP4'] [--keep]
The file is copied into the fake Runtipi media/Videos as uid 1000 (as Files would store an upload), then over MCP only:
import_file -> start_edit -> apply_cuts(proposed) -> apply_cuts([]) -> render_final({}).
Records wall time per stage, gate results, the video container's cgroup memory.peak, and checks:
 - no proposed cut overlaps a neighbouring non-filler word,
 - the dialogue gate passes (or the report says exactly which words near a cut were lost),
 - the low-res preview is produced,
 - apply_cuts([]) works, render_final({}) saves a 1080x1920 MP4 into Videos/Edited with the delivery gate passing.
Report: $E2E_OUT/real-source-report.json.
"""
import argparse
import asyncio
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


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fv = load("e2e_files_video", "e2e-files-video.py")
m, e2e, files_smoke = fv.m, fv.e2e, fv.files_smoke
tool, wait_run, run = m.tool, m.wait_run, e2e.run
ClientSession, streamable_http_client = m.ClientSession, m.streamable_http_client
FILLERS = {"um", "umm", "uhm", "uh", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm"}


def norm(w):
    return "".join(c for c in w.lower() if c.isalnum())


def overlaps(cuts, words):
    bad = []
    for c in cuts:
        for i, w, s, e in words:
            if norm(w) not in FILLERS and e - s > 0.005 and c["start_s"] < e and c["end_s"] > s:
                bad.append({"cut": c, "word": [i, w, s, e]})
    return bad


def mem_peak(cmd, env):
    try:
        return int(run(*cmd, "exec", "-T", "defleur-video", "cat", "/sys/fs/cgroup/memory.peak", env=env).strip())
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


async def flow(url, remote, report, peak):
    times = report["stage_seconds"] = {}

    async def timed(name, call, args, budget=3600):
        t0 = time.monotonic()
        res = await tool(s, call, args)
        if "run_id" in res:
            res = await wait_run(s, res["run_id"], [], budget=budget)
        times[name] = round(time.monotonic() - t0, 1)
        report["memory_peak_bytes_after_" + name] = peak()
        save()
        return res

    def save():
        (e2e.OUT / "real-source-report.json").write_text(json.dumps(report, indent=2, default=str))

    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if report.get("motion_dir"):  # step 0: the agent check, a mismatch and a match
                checks = {}
                for h, mdl in (("Hermes Agent", "gpt-5"), ("Hermes Agent", "claude-opus-5-5"), ("Hermes Agent", None)):
                    g = await tool(s, "workflow_guide", {"agent_harness": h, "agent_model": mdl} if mdl else {"agent_harness": h})
                    checks[f"{h} / {mdl}"] = g["agent_check"]
                report["agent_check"] = checks
                assert checks["Hermes Agent / gpt-5"]["match"] is False and checks["Hermes Agent / gpt-5"]["requires_owner_confirmation"]
                assert checks["Hermes Agent / claude-opus-5-5"]["match"] is True
                assert checks["Hermes Agent / None"]["match"] == "unknown"
                (Path(report["motion_dir"]) / "guide.json").write_text(json.dumps(g, indent=2))
            caps = await tool(s, "capabilities")
            assert caps["ready"], caps
            if report.get("motion_dir"):
                assert caps.get("motion_ready"), caps.get("browser")
            report["version"] = caps.get("version")
            imp = await timed("import_file", "import_file", {"path": remote}, budget=3600)
            report["import_file"] = {k: imp.get(k) for k in ("id", "video_codec", "width", "height", "duration", "fps", "normalization")}
            pid = imp["id"]
            edit = await timed("start_edit", "start_edit", {"project_id": pid})
            cuts = edit["proposed_cuts"]
            report["start_edit"] = {"duration_s": edit["duration_s"], "words": len(edit["words"]), "proposed_cuts": cuts,
                                    "candidates": [{k: c.get(k) for k in ("kind", "word", "start_s", "end_s", "cut")} for c in edit["candidates"]],
                                    "untranscribed_sound": edit.get("untranscribed_sound"),
                                    "cut_neighbour_overlaps": overlaps(cuts, edit["words"])}
            ctx = {}
            for c in cuts:
                ctx[f"{c['start_s']}-{c['end_s']}"] = [x for x in edit["words"] if c["start_s"] - 1.0 < x[3] and x[2] < c["end_s"] + 1.0]
            report["start_edit"]["cut_context_words"] = ctx
            save()
            if report.get("motion_dir"):
                (Path(report["motion_dir"]) / "edit.json").write_text(json.dumps(edit, indent=2))
            cut = await timed("apply_cuts_proposed", "apply_cuts", {"project_id": pid, "segments": cuts})
            keys = ("seconds_removed", "kept_segments", "words_lost_vs_source", "words_added_vs_source", "words_lost_near_cuts",
                    "asr_variance_far_from_cuts", "words_near_cuts_heard_on_local_recheck", "local_rechecks", "fillers_source_only", "fillers_edit_only", "dialogue_gate", "preview", "cut_sound_check")
            report["apply_cuts_proposed"] = {k: cut.get(k) for k in keys}
            save()
            if report.get("motion_dir"):
                await motion_flow(s, pid, Path(report["motion_dir"]), url.rsplit("/mcp", 1)[0], cut, timed, report, save)
                return
            empty = await timed("apply_cuts_empty", "apply_cuts", {"project_id": pid, "segments": []})
            report["apply_cuts_empty"] = {k: empty.get(k) for k in keys + ("no_cuts",)}
            save()
            final = await timed("render_final", "render_final", {"project_id": pid, "options": {}}, budget=5400)
            report["render_final"] = {k: final.get(k) for k in ("final", "delivery_gate", "saved_to_files", "captions", "crop",
                                                                 "stage_seconds", "final_render_phase_seconds")}
            save()


async def motion_flow(s, pid, mdir, vbase, cut, timed, report, save):
    """The agent's motion path, driven by command files so a human/agent can author and look between steps:
    mdir/cmd-<n>.json = {"op": "submit", "files": {...}, "plan": {...}} | {"op": "capture", "mode": "smoke"|"proof"} | {"op": "render"}.
    Each answer lands in mdir/result-<n>.json; capture frames and the contact sheet are downloaded to mdir/cap-<n>/."""
    (mdir / "cut.json").write_text(json.dumps(cut, indent=2))
    report["motion_steps"], n = [], 1
    while True:
        cmd_file = mdir / f"cmd-{n}.json"
        while not cmd_file.is_file():
            await asyncio.sleep(2)
        await asyncio.sleep(0.5)
        cmd = json.loads(cmd_file.read_text())
        t0 = time.monotonic()
        try:
            if cmd["op"] == "submit":
                res = await tool(s, "submit_motion", {"project_id": pid, "files": cmd["files"], "plan": cmd["plan"]})
            elif cmd["op"] == "capture":
                res = await timed(f"capture_motion_{cmd['mode']}_{n}", "capture_motion", {"project_id": pid, "mode": cmd["mode"]})
                out = mdir / f"cap-{n}"
                out.mkdir(exist_ok=True)
                for item in [{"image": "sheet.png", "url": res["contact_sheet"]}, *res["frame_images"]]:
                    (out / item["image"]).write_bytes(e2e.http_call("GET", item["url"].replace(item["url"].split("/v1/")[0], vbase), timeout=60)[1])
            elif cmd["op"] == "render":
                start = await tool(s, "render_final", {"project_id": pid, "options": {"motion": True}})
                samples, rid = [], start["run_id"]
                while True:
                    st = await tool(s, "get_status", {"job_or_project": rid, "wait_s": 20})
                    samples.append({"t": round(time.monotonic() - t0, 1), **{k: st.get(k) for k in (
                        "state", "step", "elapsed_s", "step_elapsed_s", "stages_done", "sub_stage", "estimate_remaining_s", "stages_left")}})
                    report["render_progress_samples"] = samples
                    save()
                    if st["state"] != "running":
                        break
                if st["state"] != "done":
                    raise RuntimeError(st.get("error"))
                res = st["result"]
                report["stage_seconds"]["render_final_motion"] = round(time.monotonic() - t0, 1)
                report["render_final"] = {k: res.get(k) for k in ("final", "delivery_gate", "saved_to_files", "captions", "crop", "motion_graphics",
                                                                  "beats_delivered", "inserts_delivered", "stage_seconds", "final_render_phase_seconds")}
            else:
                raise RuntimeError("unknown op")
        except Exception as e:  # noqa: BLE001 - the agent reads the error and decides
            res = {"error": str(e)}
        report["motion_steps"].append({"n": n, "op": cmd["op"], "mode": cmd.get("mode"), "seconds": round(time.monotonic() - t0, 1),
                                       "error": res.get("error"), "pass": res.get("pass")})
        (mdir / f"result-{n}.json").write_text(json.dumps(res, indent=2, default=str))
        save()
        n += 1
        if cmd["op"] == "render" and "error" not in res:
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-source", required=True, type=Path)
    ap.add_argument("--name", default="Videos/hormozi advice 7.MP4")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--motion-dir", type=Path, help="motion path: also start the Browser app and drive the motion steps from command files here")
    a = ap.parse_args()
    src = a.real_source.resolve()
    name = "real-video-" + secrets.token_hex(4)
    report: dict = {"test": "real source over MCP (Files + Transcriber + DeFleur Video)", "image": fv.IMAGE,
                    "source": str(src), "source_bytes": src.stat().st_size}
    if a.motion_dir:
        a.motion_dir.mkdir(parents=True, exist_ok=True)
        report["motion_dir"] = str(a.motion_dir.resolve())
    fc, tc, vc = e2e.translate("files"), e2e.translate("transcriber"), e2e.translate("defleur-video")
    fs, ts, vs = fc["services"]["files"], tc["services"]["transcriber"], vc["services"]["defleur-video"]
    for c in (fc, tc, vc):
        c["networks"]["tipi_main_network"] = {"name": name, "external": True}
    fs["ports"], ts["ports"], vs["ports"] = ["127.0.0.1::8080"], ["127.0.0.1::8000"], ["127.0.0.1::8787"]
    vs["image"], vs["pull_policy"] = fv.IMAGE, "never"
    cache = os.environ.get("E2E_CACHE")
    root = Path(tempfile.mkdtemp(prefix=name + "-", dir=os.environ.get("TMPDIR")))
    files_smoke.runtipi_root(root)
    tdata = Path(cache) / "transcriber" if cache else root / "app-data" / "transcriber"
    tdata.mkdir(parents=True, exist_ok=True)
    if cache:
        (Path(cache) / "models").mkdir(exist_ok=True)
        os.chmod(Path(cache) / "models", 0o777)
        vs["volumes"].append(f"{Path(cache) / 'models'}:/data/models")
    model = json.loads((e2e.ROOT / "apps/transcriber/config.json").read_text())["form_fields"][0]["default"]
    envs = {"t": {**os.environ, "APP_DATA_DIR": str(tdata), "TRANSCRIBER_MODEL": model},
            "v": {**os.environ, "APP_DATA_DIR": str(root / "app-data/video"), "ROOT_FOLDER_HOST": str(root),
                  "TRANSCRIBER_URL": "http://transcriber:8000", "TRANSCRIBER_MODEL": model}}
    cmds = {}
    stacks = [("t", tc), ("v", vc)]
    if a.motion_dir:
        bc = e2e.translate("browser")
        bc["networks"]["tipi_main_network"] = {"name": name, "external": True}
        bc["services"]["browser"]["ports"] = ["127.0.0.1::9222"]
        (root / "app-data" / "browser").mkdir(parents=True, exist_ok=True)
        envs["b"] = {**os.environ, "APP_DATA_DIR": str(root / "app-data" / "browser")}
        envs["v"]["BROWSER_URL"] = next(f["default"] for f in json.loads((e2e.ROOT / "apps/defleur-video/config.json").read_text())["form_fields"]
                                        if f["env_variable"] == "BROWSER_URL")
        stacks.append(("b", bc))
    for key, c in stacks:
        (root / f"{key}.json").write_text(json.dumps(c))
        cmds[key] = ["docker", "compose", "-p", f"{name}-{key}", "-f", str(root / f"{key}.json")]
    run("docker", "network", "create", name)
    fcmd = fenv = None
    try:
        fcmd, fenv, _, _ = files_smoke.start(name + "-f", root, "", fc)
        if "b" in cmds:
            run(*cmds["b"], "up", "-d", env=envs["b"])
        run(*cmds["t"], "up", "-d", env=envs["t"])
        run(*cmds["v"], "up", "-d", env=envs["v"])
        files_smoke.as_root(root, "chmod", "-Rf", "a+rwx", "/r/app-data/video")
        vbase = fv.m_ready(cmds["v"], envs["v"], "defleur-video", 8787, "/healthz", 90)
        fv.m_ready(cmds["t"], envs["t"], "transcriber", 8000, "/health", 900)
        # The exact uploaded bytes, stored as Files stores an upload (uid 1000, 0664).
        remote = a.name
        run("docker", "run", "--rm", "--network", "none", "--user", "0:0",
            "--mount", f"type=bind,source={root},target=/r", "--mount", f"type=bind,source={src},target=/in,readonly",
            files_smoke.HELPER, "sh", "-c", f"cp /in '/r/media/{remote}' && chown 1000:1000 '/r/media/{remote}' && chmod 664 '/r/media/{remote}'",
            timeout=900)
        peak_thread = e2e.Peak(run(*cmds["v"], "ps", "-aq", env=envs["v"]).strip())
        peak_thread.start()
        t0 = time.monotonic()
        asyncio.run(flow(vbase + "/mcp", remote, report, lambda: mem_peak(cmds["v"], envs["v"])))
        report["flow_s"] = round(time.monotonic() - t0, 1)
        saved = report["render_final"]["saved_to_files"]
        dl = Path(tempfile.mkdtemp(prefix="dl-", dir=os.environ.get("TMPDIR")))
        os.chmod(dl, 0o777)
        files_smoke.as_root(root, "sh", "-c", f"cp '/r/media/{saved['path']}' /r/final-copy.mp4 && chmod 644 /r/final-copy.mp4")
        shutil.copyfile(root / "final-copy.mp4", dl / "final.mp4")
        os.chmod(dl / "final.mp4", 0o644)
        probe = json.loads(e2e.ff("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                                  "-of", "json", "final.mp4", cwd=dl))
        shutil.rmtree(dl, ignore_errors=True)
        report["final_probe"] = probe
        report["memory_peak_sampled_bytes"] = peak_thread.peak
        peak_thread.stop.set()
        if a.motion_dir:  # keep the final MP4 for frame checks
            shutil.copyfile(root / "final-copy.mp4", a.motion_dir / "final.mp4")
        report["result"] = "pass" if (report["render_final"]["delivery_gate"]["pass"] and saved.get("saved")
                                      and report["apply_cuts_proposed"]["dialogue_gate"]["pass"]
                                      and not report["start_edit"]["cut_neighbour_overlaps"]
                                      and "failed" not in str(report["apply_cuts_proposed"]["preview"])) else "fail"
    finally:
        report["memory_peak_bytes_final"] = mem_peak(cmds["v"], envs["v"])
        try:
            report["video_logs_tail"] = run(*cmds["v"], "logs", "--no-color", "--tail", "30", env=envs["v"])[-4000:]
        except Exception:  # noqa: BLE001
            pass
        for key in [k for k in ("v", "t", "b") if k in cmds]:
            subprocess.run([*cmds[key], "down", "--remove-orphans"], env=envs[key], capture_output=True)
        if fcmd:
            subprocess.run([*fcmd, "down", "--remove-orphans"], env=fenv, capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        if not a.keep:
            files_smoke.as_root(root, "sh", "-c", "rm -rf /r/media /r/app-data /r/apps /r/state /r/final-copy.mp4")
            shutil.rmtree(root, ignore_errors=True)
        (e2e.OUT / "real-source-report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report.get(k) for k in ("result", "stage_seconds", "memory_peak_bytes_final", "flow_s")}, default=str))


if __name__ == "__main__":
    main()
