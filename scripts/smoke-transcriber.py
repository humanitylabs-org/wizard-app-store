#!/usr/bin/env python3
"""Disposable Runtipi-translated lifecycle test for the Transcriber app.

Uses the real pinned Runtipi 4.8.0 compose builder, a fresh app-data bind, the
same post-up permission step Runtipi runs, then performs a real word-timestamp
transcription and checks the model survives restart without re-download.
Needs Docker/Compose, npm ci, and internet access to pull the image and model.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
APP = "transcriber"
FIXTURE = ROOT / "scripts/fixtures/transcriber-hello.ogg"
EXPECTED = {"hello", "miguel", "um", "short", "test", "shared", "transcriber", "word", "start", "end", "time"}


def run(*args, timeout=600, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs).stdout.strip()


def http(method, url, body=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, res.read()


def transcribe(base, model):
    boundary = uuid.uuid4().hex
    fields = [("model", model), ("response_format", "verbose_json"),
              ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
    body = b""
    for k, v in fields:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{FIXTURE.name}\"\r\n"
             "Content-Type: audio/ogg\r\n\r\n").encode() + FIXTURE.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    _, raw = http("POST", base + "/v1/audio/transcriptions", body,
                  {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=300)
    return json.loads(raw)


def main():
    name = "transcriber-smoke-" + secrets.token_hex(4)
    translated = json.loads(run("node", "scripts/translate-video-recipe.mjs", APP, cwd=ROOT))
    compose = translated["compose"]
    service = compose["services"][APP]
    model = json.loads((ROOT / f"apps/{APP}/config.json").read_text())["form_fields"][0]["default"]
    assert service["restart"] == "unless-stopped" and service["read_only"] is True
    assert service["ports"] == ["${APP_PORT}:8000"]
    report = {"test": "translated recipe + real container transcription lifecycle", "image": service["image"], "model": model}
    service["ports"] = ["127.0.0.1::8000"]
    compose["networks"]["tipi_main_network"] = {"name": name, "external": True}
    with tempfile.TemporaryDirectory(prefix=name + "-", dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        app = tmp / "app-data"
        app.mkdir()
        env = {**os.environ, "APP_DATA_DIR": str(app), "TRANSCRIBER_MODEL": model}
        recipe = tmp / "compose.json"
        recipe.write_text(json.dumps(compose))
        cmd = ["docker", "compose", "-p", name, "-f", str(recipe)]
        run("docker", "network", "create", name)
        try:
            started = time.monotonic()
            run(*cmd, "up", "-d", env=env)
            cid = run(*cmd, "ps", "-aq", env=env)
            # Runtipi 4.8.0 runs this as host root right after compose up.
            run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                f"type=bind,source={app},target=/fixture", "--entrypoint", "/bin/chmod",
                service["image"], "-Rf", "a+rwx", "/fixture")

            def ready(deadline_s=600):
                deadline = time.monotonic() + deadline_s
                while time.monotonic() < deadline:
                    try:
                        port = run(*cmd, "port", APP, "8000", env=env).rsplit(":", 1)[1]
                        base = "http://127.0.0.1:" + port
                        if http("GET", base + "/health", timeout=5)[0] == 200:
                            return base
                    except (OSError, urllib.error.URLError, subprocess.CalledProcessError, IndexError):
                        pass
                    time.sleep(3)
                print(run(*cmd, "logs", "--no-color", "--tail", "80", env=env), file=sys.stderr)
                raise RuntimeError("Transcriber did not become healthy")

            base = ready()
            report["first_ready_seconds"] = round(time.monotonic() - started, 1)
            report["first_start_restarts"] = json.loads(run("docker", "inspect", cid))[0]["RestartCount"]
            inspect = json.loads(run("docker", "inspect", cid))[0]
            assert inspect["HostConfig"]["ReadonlyRootfs"] and inspect["Config"]["User"] == "ubuntu"
            assert run("docker", "exec", cid, "id", "-u") == "1000"
            models = json.loads(http("GET", base + "/v1/models")[1])
            assert any(m["id"] == model for m in models["data"]), models

            t0 = time.monotonic()
            result = transcribe(base, model)
            report["transcribe_seconds"] = round(time.monotonic() - t0, 2)
            words = result.get("words") or []
            assert result.get("language") == "en", result.get("language")
            got = {"".join(c for c in w["word"].lower() if c.isalnum()) for w in words}
            missing = EXPECTED - got
            assert not missing, f"missing words {missing}: {result.get('text')}"
            assert all(0 <= w["start"] <= w["end"] <= result["duration"] + 0.5 for w in words)
            assert [w["start"] for w in words] == sorted(w["start"] for w in words)
            report["text"] = result["text"].strip()
            report["words"] = len(words)

            def blobs():
                # Speaches logs "Fetching" on every start (remote check), so compare the cached files instead.
                found = {}
                for p in (app / "data/huggingface/hub").rglob("blobs/*"):
                    if p.is_file():
                        s = p.stat()
                        found[str(p.relative_to(app))] = (s.st_size, s.st_mtime_ns, s.st_ino)
                return found

            before = blobs()
            assert before, "no cached model blobs found in app data"
            run(*cmd, "up", "-d", "--force-recreate", env=env)
            t0 = time.monotonic()
            base = ready(120)
            report["recreate_ready_seconds"] = round(time.monotonic() - t0, 1)
            assert blobs() == before, "cached model files changed after recreate (re-downloaded?)"
            assert transcribe(base, model).get("words"), "no words after recreate"
            report["recreate"] = "same cached model files; transcription works without re-download"
            report["cached_blobs"] = len(before)
            # Known upstream behavior (verified manually): PRELOAD_MODELS queries huggingface.co at
            # startup, so a restart with no internet exits and Docker retries until it is back.
            report["data_bytes"] = int(run("du", "-sb", str(app)).split()[0])
        finally:
            subprocess.run([*cmd, "down", "--remove-orphans"], env=env, capture_output=True)
            subprocess.run(["docker", "network", "rm", name], capture_output=True)
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                            f"type=bind,source={app},target=/fixture", "--entrypoint", "/bin/chmod",
                            service["image"], "-Rf", "a+rwx", "/fixture"], capture_output=True)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
