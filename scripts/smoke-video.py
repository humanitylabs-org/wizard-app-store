#!/usr/bin/env python3
"""Disposable actual-recipe container/API lifecycle test; no agent or paid calls.

Requires npm ci, Docker/Compose and the already-built local candidate image.
Uses the real pinned Runtipi builder. It is NOT a complete Runtipi UI install.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("VIDEO_TEST_IMAGE", "wizard-defleur-video:0.3.0-testing")
sys.path.insert(0, str(ROOT / "images/defleur-video"))
from client import Client  # pyright: ignore[reportMissingImports]


def run(*args, **kwargs):
    p = subprocess.run(args, check=True, capture_output=True, text=True, timeout=120, **kwargs)
    return p.stdout.strip()


def main():
    token = secrets.token_hex(24)
    name = "video-review-smoke-" + secrets.token_hex(5)
    report: dict = {"test": "translated recipe + real container HTTP lifecycle", "image": IMAGE}
    with tempfile.TemporaryDirectory(prefix=name + "-", dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        translated = json.loads(run("node", "scripts/translate-video-recipe.mjs", cwd=ROOT))
        report["runtipi"] = {k: v for k, v in translated.items() if k != "compose"}
        compose = translated["compose"]
        service = compose["services"]["defleur-video"]
        assert service["restart"] == "unless-stopped"
        assert service["image"] == "ghcr.io/humanitylabs-org/defleur-video:0.3.0-testing"
        assert service["user"] == "1000:1000" and service["read_only"] is True
        assert service["ports"] == ["${APP_PORT}:8787"]
        # Test-only substitutions: cached image, loopback ephemeral port, isolated network.
        service["image"] = IMAGE
        service["pull_policy"] = "never"
        service["ports"] = ["127.0.0.1::8787"]
        compose["networks"]["tipi_main_network"] = {"name": name, "external": True}
        app = tmp / "app-data"
        app.mkdir()
        # Runtipi writes form-field defaults into the app env file.
        fields = {f["env_variable"]: f["default"] for f in json.loads((ROOT / "apps/defleur-video/config.json").read_text())["form_fields"]}
        env = {**os.environ, "APP_DATA_DIR": str(app), **fields}
        recipe = tmp / "compose.json"
        recipe.write_text(json.dumps(compose))
        cmd = ["docker", "compose", "-p", name, "-f", str(recipe)]
        run("docker", "network", "create", name)
        try:
            run(*cmd, "up", "-d", env=env)
            cid = run(*cmd, "ps", "-aq", env=env)
            assert cid
            # Docker creates a fresh absent bind directory as container root.
            def helper(code, host_root=False):
                # Runtipi's permission step runs as real host root; inspection helpers stay unprivileged.
                caps = [] if host_root else ["--cap-drop", "ALL"]
                return run("docker", "run", "--rm", "--network", "none", "--read-only", *caps,
                           "--user", "0:0", "--mount", f"type=bind,source={app},target=/fixture",
                           "--entrypoint", "/usr/bin/python3", IMAGE, "-c", code)
            before = json.loads(helper("import os,json; s=os.stat('/fixture/data'); print(json.dumps({'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode & 511)}))"))
            assert before["uid"] == 0 and before["mode"] == "0o755", before
            report["fresh_bind_before_runtipi_permission_step"] = before
            # Exactly Runtipi 4.8.0's verified post-up permission command, on disposable data only.
            helper("import subprocess; subprocess.run(['chmod','-Rf','a+rwx','/fixture'],check=True)", host_root=True)
            def ready():
                deadline = time.monotonic() + 45
                while True:
                    try:
                        port = run(*cmd, "port", "defleur-video", "8787", env=env).rsplit(":", 1)[1]
                        client = Client("http://127.0.0.1:" + port, "")  # open mode, as installed
                        return client, client.request("GET", "/healthz")
                    except (OSError, http.client.HTTPException, subprocess.CalledProcessError, IndexError):
                        if time.monotonic() >= deadline:
                            print(run(*cmd, 'logs', '--no-color', env=env), file=sys.stderr)
                            print(run('docker', 'inspect', '--format', '{{json .State}} {{json .NetworkSettings.Ports}}', cid), file=sys.stderr)
                            print(run('docker', 'exec', cid, '/usr/bin/python3', '-c', "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/healthz').read())"), file=sys.stderr)
                            raise RuntimeError("container did not recover after Runtipi permission step")
                        time.sleep(.25)
            client, health = ready()
            assert Client("http://127.0.0.1:" + run(*cmd, "port", "defleur-video", "8787", env=env).rsplit(":", 1)[1], "").request("GET", "/v1/capabilities")["operations"]
            assert health["version"] == "0.3.0-testing"
            report["health"] = health
            inspect = json.loads(run("docker", "inspect", cid))[0]
            assert inspect["Config"]["User"] == "1000:1000"
            assert inspect["HostConfig"]["ReadonlyRootfs"]
            assert inspect["HostConfig"]["Memory"] == 1610612736
            report["startup_restart_count"] = inspect["RestartCount"]
            report["uid"] = int(run("docker", "exec", cid, "id", "-u"))
            assert report["uid"] == 1000
            report["bind_after_permission_step"] = json.loads(helper("import os,json; s=os.stat('/fixture/data'); print(json.dumps({'uid':s.st_uid,'mode':oct(s.st_mode & 511)}))"))
            # A real captionable synthetic source, generated inside the candidate.
            run("docker", "exec", cid, "/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "libx264",
                "-threads", "1", "-c:a", "aac", "/data/smoke-source.mp4")
            run("docker", "cp", cid + ":/data/smoke-source.mp4", str(tmp / "source.mp4"))
            original = (tmp / "source.mp4").read_bytes()
            project = client.request("POST", "/v1/projects", original, "video/mp4")
            pid = project["id"]
            assert client.request("GET", f"/v1/projects/{pid}") == project
            decision_value = {"transcript": {"language": "en", "provenance": "Synthetic tone fixture; not actual speech",
                "words": [{"start_s": .1, "end_s": .7, "word": "Synthetic"}]}, "plan": {
                "segments": [{"start_s": 0, "end_s": 1.8, "reason": "Synthetic lifecycle fixture"}],
                "captions": [{"start_s": .1, "end_s": .8, "text": "Synthetic review"}], "framing": {"mode": "contain"}}}
            decision = client.request("POST", f"/v1/projects/{pid}/decisions", json.dumps(decision_value))
            assert client.request("GET", f"/v1/projects/{pid}/decisions")["decisions"] == [decision]
            job = client.request("POST", f"/v1/projects/{pid}/previews", json.dumps({"decision_id": decision["id"]}))
            job = client.wait(job["id"], True)
            assert job["state"] == "needs_review", job
            assert job["result"]["captions_burned"] and not job["delivery_approved"]
            before_movie = client.request("GET", f"/v1/jobs/{job['id']}/preview")
            assert hashlib.sha256(before_movie).hexdigest() == job["result"]["sha256"]
            client.review(job["id"], tmp / "before-review")
            # Piece-1 workflow stages (no Transcriber here; e2e-video-audio.py covers ASR/alignment).
            caps = client.request("GET", "/v1/capabilities")["workflow"]
            assert all(h["available"] for h in caps["helpers"].values()), caps["helpers"]
            assert caps["transcriber"]["url_host"] == "transcriber:8000" and caps["transcriber"]["reachable"] is False
            report["transcriber_absent_reported"] = caps["transcriber"]
            assert client.request("GET", "/v1/workflow/docs/defleur-audio", raw=True).startswith(b"---")
            stages = {}
            def stage(op, body):
                j = client.wait(client.request("POST", f"/v1/projects/{pid}/stages/{op}", json.dumps(body))["id"], True)
                stages[op] = j
                return j
            src = stage("source-audio", {})
            assert src["state"] == "needs_review", src
            asr = stage("asr", {"audio_job": src["id"], "language": "en"})
            assert asr["state"] == "failed" and "Install the Transcriber app" in asr["error"], asr
            report["asr_without_transcriber"] = asr["error"]
            asm = stage("pcm-assemble", {"audio_job": src["id"], "segments": [{"start_s": 0, "end_s": .6, "reason": "smoke"}, {"start_s": 1.0, "end_s": 1.9, "reason": "smoke"}]})
            assert asm["state"] == "needs_review", asm
            audit = stage("speech-cut-audit", {"assemble_job": asm["id"], "regions": [{"mode": "keep", "start_s": .1, "end_s": .5}, {"mode": "drop", "start_s": .7, "end_s": .9}]})
            assert audit["state"] == "needs_review" and audit["result"]["summary"]["pass"], audit
            edited = client.request("GET", f"/v1/jobs/{asm['id']}/stage-artifacts/edited.wav")
            edge_png = client.request("GET", f"/v1/jobs/{audit['id']}/stage-artifacts/1-start-spectrogram.png")
            # Read back exact project, decision, job, source and output after each lifecycle.
            for label, command in [("restart", ["restart", "-t", "5"]), ("stop-start", ["stop", "-t", "5"]), ("recreate", ["up", "-d", "--force-recreate"])]:
                run(*cmd, *command, env=env)
                if label == "stop-start":
                    run(*cmd, "start", env=env)
                client, _ = ready()
                assert client.request("GET", f"/v1/projects/{pid}") == project
                assert client.request("GET", f"/v1/projects/{pid}/decisions")["decisions"] == [decision]
                assert client.request("GET", f"/v1/jobs/{job['id']}") == job
                assert client.request("GET", f"/v1/projects/{pid}/source") == original
                assert client.request("GET", f"/v1/jobs/{job['id']}/preview") == before_movie
                for op, j in stages.items():
                    assert client.request("GET", f"/v1/jobs/{j['id']}") == j, op
                assert client.request("GET", f"/v1/jobs/{asm['id']}/stage-artifacts/edited.wav") == edited
                assert client.request("GET", f"/v1/jobs/{audit['id']}/stage-artifacts/1-start-spectrogram.png") == edge_png
                report[label] = "exact project/decision/job/source/preview and workflow stage jobs/artifacts preserved"
            client.review(job["id"], tmp / "after-review")
            report["render"] = {"sha256": job["result"]["sha256"], "bytes": len(before_movie),
                "state": job["state"], "artifacts_verified": len(job["result"]["review"]["artifacts"]), "captions_burned": True}
            client.request("DELETE", f"/v1/projects/{pid}")
            assert client.request("GET", f"/v1/projects/{pid}", missing_ok=True) is None
            assert client.request("GET", f"/v1/jobs/{job['id']}", missing_ok=True) is None
            report["delete_read_back"] = True
            report["workflow_stages"] = {op: {"state": j["state"], "artifacts": len((j.get("result") or {}).get("artifacts", []))} for op, j in stages.items()}
        finally:
            run(*cmd, "down", "--remove-orphans", env=env)
            run("docker", "network", "rm", name)
            # UID 1000 files cannot be removed by the rootless host UID without a scoped cleanup.
            run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                f"type=bind,source={app},target=/fixture", "--entrypoint", "/bin/chmod", IMAGE, "-Rf", "a+rwx", "/fixture")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
