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
            caps = await tool(s, "capabilities")
            assert caps["ready"], caps
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
            cut = await timed("apply_cuts_proposed", "apply_cuts", {"project_id": pid, "segments": cuts})
            keys = ("seconds_removed", "kept_segments", "words_lost_vs_source", "words_added_vs_source", "words_lost_near_cuts",
                    "asr_variance_far_from_cuts", "fillers_source_only", "fillers_edit_only", "dialogue_gate", "preview", "cut_sound_check")
            report["apply_cuts_proposed"] = {k: cut.get(k) for k in keys}
            save()
            empty = await timed("apply_cuts_empty", "apply_cuts", {"project_id": pid, "segments": []})
            report["apply_cuts_empty"] = {k: empty.get(k) for k in keys + ("no_cuts",)}
            save()
            final = await timed("render_final", "render_final", {"project_id": pid, "options": {}}, budget=5400)
            report["render_final"] = {k: final.get(k) for k in ("final", "delivery_gate", "saved_to_files", "captions", "crop",
                                                                 "stage_seconds", "final_render_phase_seconds")}
            save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-source", required=True, type=Path)
    ap.add_argument("--name", default="Videos/hormozi advice 7.MP4")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    src = a.real_source.resolve()
    name = "real-video-" + secrets.token_hex(4)
    report: dict = {"test": "real source over MCP (Files + Transcriber + DeFleur Video)", "image": fv.IMAGE,
                    "source": str(src), "source_bytes": src.stat().st_size}
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
    for key, c in (("t", tc), ("v", vc)):
        (root / f"{key}.json").write_text(json.dumps(c))
        cmds[key] = ["docker", "compose", "-p", f"{name}-{key}", "-f", str(root / f"{key}.json")]
    run("docker", "network", "create", name)
    fcmd = fenv = None
    try:
        fcmd, fenv, _, _ = files_smoke.start(name + "-f", root, "", fc)
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
        for key in ("v", "t"):
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
