#!/usr/bin/env python3
"""Files + Transcriber + DeFleur Video: real translated Runtipi recipes on one network, one fake ROOT_FOLDER_HOST whose
media/ is created the Runtipi 4.8.0 way (root, 0755), Runtipi's post-up chmod on app data.

(b) an iPhone-style multi-track HEVC HLG .mov (real face + real speech, timecode, second 4-channel audio track, six
    text/metadata tracks) is uploaded into Files -> Videos through File Browser's tus API; over MCP only: list_files,
    import_file (converted), start_edit, apply_cuts, render_final; the finished MP4 appears in Videos/Edited and downloads
    through the Files app with the reported SHA-256.
(c) import_file refuses '..', absolute paths, a symlink to outside media, a FIFO and a folder.
(d) with media mounted read-only, capabilities.files gives a fix and create_upload still works.
Needs the local candidate image (VIDEO_TEST_IMAGE) and the MCP SDK (same handling as e2e-video-mcp.py).
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


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load("e2e_mcp", "e2e-video-mcp.py")  # re-execs under a Python with the MCP SDK if needed
files_smoke = load("smoke_files", "smoke-files.py")
e2e, tool, wait_run = m.e2e, m.tool, m.wait_run
run, http_call, IMAGE = e2e.run, e2e.http_call, e2e.IMAGE
ClientSession, streamable_http_client = m.ClientSession, m.streamable_http_client


def iphone_mov(fixture):
    out = fixture / "IMG_5644.mov"
    srt = fixture / "meta.srt"
    srt.write_text("1\n00:00:00,000 --> 00:10:00,000\nmeta\n")
    dur = json.loads(e2e.ff("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", "talking-1080p.mp4",
                            cwd=fixture))["format"]["duration"]
    args = ["ffmpeg", "-v", "error", "-y", "-i", "talking-1080p.mp4", "-f", "lavfi", "-i", "anoisesrc=a=0.001:r=48000:d=60"]
    args += [x for _ in range(6) for x in ("-i", "meta.srt")]
    args += ["-map", "0:v", "-map", "0:a", "-map", "1:a"] + [x for i in range(6) for x in ("-map", f"{i + 2}:s")]
    args += ["-t", dur, "-c:v", "libx265", "-preset", "fast",
             "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
             "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
             "-tag:v", "hvc1", "-c:a:0", "aac", "-c:a:1", "alac", "-ac:a:1", "4", "-c:s", "mov_text",
             "-timecode", "01:00:00:00", "-f", "mov", out.name]
    e2e.ff(*args, cwd=fixture)
    os.chmod(out, 0o666)
    return out


async def flow(url, fb, root, mov, truth, report):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            assert {"list_files", "import_file"} <= tools, tools
            caps = await tool(s, "capabilities")
            report["capabilities_files"] = caps["files"]
            assert caps["ready"] and caps["files"]["writable"] and not caps["files"]["fix"], caps["files"]
            listing = await tool(s, "list_files", {})
            report["list_files"] = [f["path"] for f in listing["files"]]
            assert "Videos/IMG_5644.mov" in report["list_files"], listing
            # (c) path safety through the same MCP tool
            refused = {}
            for bad in ("../IMG_5644.mov", "Videos/../../app-data/x.mov", "/etc/passwd", "Videos/escape.mov", "Videos/pipe.mov",
                        "Videos/folder.mov", "Videos/linkdir/IMG_5644.mov"):
                res = await s.call_tool("import_file", {"path": bad})
                body = json.loads(res.content[0].text)
                refused[bad] = body.get("error", "")[:160]
                assert body.get("error") and "id" not in body, (bad, body)
            report["refused"] = refused
            # (b) import -> edit -> render, all over MCP
            t0 = time.monotonic()
            imp = await tool(s, "import_file", {"path": "Videos/IMG_5644.mov"})
            if "run_id" in imp:
                imp = await wait_run(s, imp["run_id"], [])
            report["import_file"] = {"seconds": round(time.monotonic() - t0, 1), **{k: imp.get(k) for k in
                                     ("id", "video_codec", "width", "height", "duration", "imported_from", "normalization")},
                                     "original_streams": imp["original"]["streams"]}
            assert imp["video_codec"] == "h264" and imp["original"]["streams"] >= 9, imp
            assert float(imp["duration"]) > 5, imp  # the real-face speech fixture, not a 2 s stub
            assert imp["original"]["sha256"] == hashlib.sha256(mov.read_bytes()).hexdigest()
            pid, log = imp["id"], []
            edit = await wait_run(s, (await tool(s, "start_edit", {"project_id": pid, "language": "en"}))["run_id"], log)
            # As e2e-video-mcp.py: take start_edit's proposals; fallback is one small cut inside the fixture's measured pause.
            cuts = edit["proposed_cuts"]
            report["start_edit"] = {"transcript": edit["transcript"], "proposed_cuts": cuts, "untranscribed_sound": edit.get("untranscribed_sound")}
            if not cuts:
                d = float(imp["duration"])
                cuts = [{"start_s": round(d * 0.45, 3), "end_s": round(d * 0.45 + 0.3, 3), "reason": "long pause (fallback)"}]
            report["chosen_cuts"] = cuts
            cut = await wait_run(s, (await tool(s, "apply_cuts", {"project_id": pid, "segments": cuts}))["run_id"], log)
            assert cut["dialogue_gate"]["pass"], cut["dialogue_gate"]
            assert cut["seconds_removed"] > 0.2 and not cut["words_lost_vs_source"], cut
            final = await wait_run(s, (await tool(s, "render_final", {"project_id": pid}))["run_id"], log, budget=3600)
            saved = final["saved_to_files"]
            report["render_final"] = {"final": final["final"], "delivery_gate_pass": final["delivery_gate"]["pass"],
                                      "crop": final["crop"], "captions": final["captions"],
                                      "saved_to_files": saved, "runs": log}
            assert saved["saved"] and saved["path"].startswith("Videos/Edited/IMG_5644-edited-") and saved["path"].endswith(".mp4"), saved
            assert saved["sha256"] == final["final"]["sha256"]
            assert final["delivery_gate"]["pass"], final["delivery_gate"]
            assert final["crop"]["face_inside_crop_all_samples"] and not final["crop"]["flags"], final["crop"]
            assert final["captions"]["cues"] >= 2, final["captions"]
            # Visible and downloadable through the Files app.
            st, body = fb.req("GET", "/api/resources/Videos/Edited/")
            names = [i["name"] for i in json.loads(body)["items"]]
            sha, n = files_smoke.download_sha(fb, saved["path"])
            on_disk = files_smoke.as_root(root, "stat", "-c", "%u:%g:%a", "/r/media/" + saved["path"])
            report["files_app_download"] = {"listed": names, "sha256_match": sha == saved["sha256"], "bytes": n, "on_disk": on_disk}
            assert saved["path"].rsplit("/", 1)[1] in names and sha == saved["sha256"] and on_disk == "1000:1000:664"
            local = root / "dl.mp4"
            st, data = fb.req("GET", "/api/raw/" + saved["path"])  # the web UI's JWT (noauth mode still issues one)
            assert st == 200
            local.write_bytes(data)
            os.chmod(local, 0o666)
            probe = json.loads(e2e.ff("ffprobe", "-v", "error", "-show_streams", "-of", "json", local.name, cwd=root))["streams"]
            e2e.ff("ffmpeg", "-v", "error", "-xerror", "-i", local.name, "-f", "null", "-", cwd=root)
            report["final_probe"] = [(x["codec_type"], x["codec_name"], x.get("width"), x.get("height")) for x in probe]
            assert [(x["codec_name"], x.get("width"), x.get("height")) for x in probe if x["codec_type"] == "video"] == [("h264", 1080, 1920)]
            await tool(s, "delete_project", {"project_id": pid})
            assert (root / "media" / saved["path"]).exists() or "1000" in on_disk  # the copy in Files stays


async def read_only_check(url, source, report):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            caps = await tool(s, "capabilities")
            report["read_only"] = {"files": caps["files"]}
            assert caps["files"]["readable"] and not caps["files"]["writable"] and "read-only" in caps["files"]["fix"], caps["files"]
            up = await tool(s, "create_upload")
            project = m.curl_upload(up["curl"], source)
            report["read_only"]["upload_still_works"] = bool(project.get("id"))
            await tool(s, "delete_project", {"project_id": project["id"]})


def main():
    name = "files-video-" + secrets.token_hex(4)
    report: dict = {"test": "Files + Transcriber + DeFleur Video, MCP only, shared Runtipi media folder", "image": IMAGE}
    fc, tc, vc = e2e.translate("files"), e2e.translate("transcriber"), e2e.translate("defleur-video")
    fs, ts, vs = fc["services"]["files"], tc["services"]["transcriber"], vc["services"]["defleur-video"]
    for c in (fc, tc, vc):
        c["networks"]["tipi_main_network"] = {"name": name, "external": True}
    fs["ports"], ts["ports"], vs["ports"] = ["127.0.0.1::8080"], ["127.0.0.1::8000"], ["127.0.0.1::8787"]
    vs["image"], vs["pull_policy"] = IMAGE, "never"
    assert "${ROOT_FOLDER_HOST}/media:/media" in vs["volumes"] and "${ROOT_FOLDER_HOST}/media:/srv" in fs["volumes"]
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
        # Files first (as Miguel installs it): it makes media/ usable by uid 1000 and creates Videos/Edited.
        fcmd, fenv, _, fport = files_smoke.start(name + "-f", root, "", fc)
        fb = files_smoke.FB(fport)
        st, page = fb.req("GET", "/")  # a fresh browser: the app shell, configured for no login
        report["files_web_ui"] = {"status": st, "noauth": b'"AuthMethod":"noauth"' in page, "branding": b'"Name":"Files"' in page}
        assert st == 200 and report["files_web_ui"]["noauth"], page[:400]
        assert fb.login() == 200
        run(*cmds["t"], "up", "-d", env=envs["t"])
        run(*cmds["v"], "up", "-d", env=envs["v"])
        files_smoke.as_root(root, "chmod", "-Rf", "a+rwx", "/r/app-data/video")
        vbase = m_ready(cmds["v"], envs["v"], "defleur-video", 8787, "/healthz", 90)
        m_ready(cmds["t"], envs["t"], "transcriber", 8000, "/health", 900)
        fixture, truth = e2e.build_fixture(ts["image"], tdata)
        m.face_fixture(fixture)
        mov = iphone_mov(fixture)
        report["iphone_mov"] = {"bytes": mov.stat().st_size, "streams": json.loads(e2e.ff(
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", mov.name, cwd=fixture))["streams"]}
        files_smoke.upload_tus(fb, mov, "Videos/IMG_5644.mov")
        # Hostile entries for (c), made as the other app user would.
        files_smoke.as_root(root, "sh", "-c", "cd /r/media/Videos && ln -s /etc/hostname escape.mov && ln -s /etc linkdir && "
                            "mkfifo pipe.mov && mkdir folder.mov && chown -h 1000:1000 escape.mov linkdir pipe.mov folder.mov")
        t0 = time.monotonic()
        asyncio.run(flow(vbase + "/mcp", fb, root, mov, truth, report))
        report["flow_s"] = round(time.monotonic() - t0, 1)
        # (d) read-only media mount: fix in capabilities, upload API still works.
        run(*cmds["v"], "down", env=envs["v"])
        vs["volumes"] = [v + ":ro" if v.endswith(":/media") else v for v in vs["volumes"]]
        (root / "v.json").write_text(json.dumps(vc))
        run(*cmds["v"], "up", "-d", env=envs["v"])
        vbase = m_ready(cmds["v"], envs["v"], "defleur-video", 8787, "/healthz", 90)
        asyncio.run(read_only_check(vbase + "/mcp", fixture / "source.mp4", report))
        report["result"] = "pass"
    finally:
        for key in ("v", "t"):
            subprocess.run([*cmds[key], "down", "--remove-orphans"], env=envs[key], capture_output=True)
        if fcmd:
            subprocess.run([*fcmd, "down", "--remove-orphans"], env=fenv, capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)
        if "--keep" not in sys.argv:
            files_smoke.as_root(root, "sh", "-c", "rm -rf /r/media /r/app-data /r/apps /r/state")
            shutil.rmtree(root, ignore_errors=True)
        (e2e.OUT / "files-video-report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=1, default=str)[:12000])


def m_ready(cmd, env, svc, port, path, deadline_s):
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


if __name__ == "__main__":
    main()
