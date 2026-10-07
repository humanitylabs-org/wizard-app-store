#!/usr/bin/env python3
"""Real two-app end-to-end test of DeFleur Video piece 1 (audio/edit) over HTTP.

Both apps run from their real Runtipi 4.8.0-translated recipes on ONE shared
external network (as Runtipi's runtipi_tipi_main_network), so the video app
reaches the Transcriber by its compose service name: http://transcriber:8000.
A speech fixture with a deliberate filler "um" and a pause is synthesized by the
Transcriber's own Kokoro TTS, muxed with a test picture, uploaded, and every
piece-1 stage is run through the dialogue audio gate. Needs internet (Speaches
startup, model downloads). No paid APIs, no LLM: this script plays the operator.

Env: VIDEO_TEST_IMAGE (local candidate), E2E_OUT (report + bundles dir),
E2E_CACHE (optional persistent dir for Transcriber/alignment model caches).
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("VIDEO_TEST_IMAGE", "wizard-defleur-video:0.3.0-testing")
OUT = Path(os.environ.get("E2E_OUT") or tempfile.mkdtemp(prefix="defleur-e2e-"))
CACHE = os.environ.get("E2E_CACHE")
TTS_MODEL = "speaches-ai/Kokoro-82M-v1.0-ONNX"
sys.path.insert(0, str(ROOT / "images/defleur-video"))
from client import Client  # noqa: E402  # pyright: ignore[reportMissingImports]

# Spoken pieces; the filler is its own clip so its true source position is known.
PARTS = [("speech", "Hello, this is a short test of the video editor."), ("gap", 0.35),
         ("speech", "Um,"), ("gap", 0.9),
         ("speech", "the filler word should be removed cleanly, and the pause shortened."), ("gap", 0.4)]


def run(*args, timeout=600, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs).stdout.strip()


def http_call(method, url, body=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, res.read()


def norm(word):
    return "".join(c for c in word.lower() if c.isalnum())


def translate(app):
    return json.loads(run("node", "scripts/translate-video-recipe.mjs", app, cwd=ROOT))["compose"]


class Peak(threading.Thread):
    """Samples the video container's cgroup memory.peak (and current) during the run."""
    def __init__(self, cid):
        super().__init__(daemon=True)
        self.cid, self.stop, self.max_current, self.peak = cid, threading.Event(), 0, 0

    def run(self):
        while not self.stop.wait(1):
            try:
                cur, peak = run("docker", "exec", self.cid, "cat", "/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.peak", timeout=10).split()
                self.max_current, self.peak = max(self.max_current, int(cur)), max(self.peak, int(peak))
            except (subprocess.SubprocessError, ValueError):
                pass


def ff(tool, *args, cwd):
    """Host ffmpeg/ffprobe if present, else the copy inside the candidate image (CI runners lack it)."""
    if shutil.which(tool) and not os.environ.get("E2E_FFMPEG_DOCKER"):
        return run(tool, *args, cwd=cwd)
    return run("docker", "run", "--rm", "--network", "none", "--mount", f"type=bind,source={cwd},target=/w", "-w", "/w",
               "--entrypoint", f"/usr/bin/{tool}", IMAGE, *args)


def build_fixture(speaches_image, hf_cache):
    """Synthesize speech with a filler and a pause using a throwaway Speaches container (Kokoro TTS)."""
    fixture = OUT / "fixture"
    if (fixture / "source.mp4").is_file() and (fixture / "truth.json").is_file():
        return fixture, json.loads((fixture / "truth.json").read_text())
    shutil.rmtree(fixture, ignore_errors=True)
    fixture.mkdir(parents=True)
    os.chmod(fixture, 0o777)  # the image's ffmpeg runs as uid 1000
    name = "defleur-e2e-tts-" + secrets.token_hex(4)
    run("docker", "run", "-d", "--name", name, "-p", "127.0.0.1::8000", "--mount", f"type=bind,source={hf_cache},target=/home/ubuntu/.cache/huggingface",
        speaches_image)
    try:
        base = None
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                base = "http://127.0.0.1:" + run("docker", "port", name, "8000").splitlines()[0].rsplit(":", 1)[1]
                if http_call("GET", base + "/health", timeout=5)[0] == 200:
                    break
            except (OSError, urllib.error.URLError, http.client.HTTPException, subprocess.CalledProcessError, IndexError):
                pass
            time.sleep(2)
        http_call("POST", base + "/v1/models/" + TTS_MODEL, timeout=900)
        clips, truth, cursor = [], {}, 0.0
        for i, (kind, value) in enumerate(PARTS):
            path = f"part-{i}.wav"
            if kind == "speech":
                body = json.dumps({"model": TTS_MODEL, "voice": "af_heart", "input": value, "response_format": "wav"}).encode()
                raw = f"part-{i}.tts.wav"
                (fixture / raw).write_bytes(http_call("POST", base + "/v1/audio/speech", body, {"Content-Type": "application/json"}, timeout=300)[1])
                # Trim TTS leading/trailing silence so clip boundaries are speech boundaries.
                ff("ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
                   "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                   "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", path, cwd=fixture)
            else:
                ff("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(value), "-c:a", "pcm_s16le", path, cwd=fixture)
            dur = float(ff("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path, cwd=fixture))
            if kind == "speech" and value == "Um,":
                truth["um"] = {"start_s": round(cursor, 3), "end_s": round(cursor + dur, 3)}
            if kind == "gap" and value == 0.9:
                truth["pause"] = {"start_s": round(cursor, 3), "end_s": round(cursor + dur, 3)}
            clips.append(path)
            cursor += dur
        truth["duration_s"] = round(cursor, 3)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    (fixture / "list.txt").write_text("".join(f"file '{p}'\n" for p in clips))
    ff("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "speech.wav", cwd=fixture)
    ff("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-i", "speech.wav",
       "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
       "-movflags", "+faststart", "source.mp4", cwd=fixture)
    (fixture / "truth.json").write_text(json.dumps(truth, indent=2))
    return fixture, truth


def main():
    name = "defleur-e2e-" + secrets.token_hex(4)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"test": "two translated Runtipi recipes on one shared network; real speech; every piece-1 stage over HTTP",
              "image": IMAGE, "started_unix": time.time(), "stages": {}}
    t_all = time.monotonic()
    tc, vc = translate("transcriber"), translate("defleur-video")
    ts, vs = tc["services"]["transcriber"], vc["services"]["defleur-video"]
    assert vs["environment"]["TRANSCRIBER_URL"] == "${TRANSCRIBER_URL}"
    for c in (tc, vc):
        c["networks"]["tipi_main_network"] = {"name": name, "external": True}
    ts["ports"], vs["ports"] = ["127.0.0.1::8000"], ["127.0.0.1::8787"]
    vs["image"], vs["pull_policy"] = IMAGE, "never"
    work = Path(tempfile.mkdtemp(prefix=name + "-", dir=os.environ.get("TMPDIR")))
    tdata = Path(CACHE) / "transcriber" if CACHE else work / "transcriber"
    vdata = work / "video"
    tdata.mkdir(parents=True, exist_ok=True)
    vdata.mkdir()
    if CACHE:  # keep alignment checkpoints across local runs; Runtipi itself uses /data/models
        (Path(CACHE) / "models").mkdir(exist_ok=True)
        os.chmod(Path(CACHE) / "models", 0o777)  # rootless Docker: container uid 1000 is not the host uid
        vs["volumes"].append(f"{Path(CACHE) / 'models'}:/data/models")
    model = json.loads((ROOT / "apps/transcriber/config.json").read_text())["form_fields"][0]["default"]
    venv = {**os.environ, "APP_DATA_DIR": str(vdata), "TRANSCRIBER_URL": "http://transcriber:8000", "TRANSCRIBER_MODEL": model}
    tenv = {**os.environ, "APP_DATA_DIR": str(tdata), "TRANSCRIBER_MODEL": model}
    (work / "t.json").write_text(json.dumps(tc))
    (work / "v.json").write_text(json.dumps(vc))
    tcmd = ["docker", "compose", "-p", name + "-t", "-f", str(work / "t.json")]
    vcmd = ["docker", "compose", "-p", name + "-v", "-f", str(work / "v.json")]

    def chmod(app_dir, image):  # Runtipi 4.8.0's post-up permission step, as host root
        run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount", f"type=bind,source={app_dir},target=/fixture",
            "--entrypoint", "/bin/chmod", image, "-Rf", "a+rwx", "/fixture")

    run("docker", "network", "create", name)
    peak = None
    try:
        run(*tcmd, "up", "-d", env=tenv)
        chmod(tdata, ts["image"])
        run(*vcmd, "up", "-d", env=venv)
        chmod(vdata, IMAGE)
        vcid = run(*vcmd, "ps", "-aq", env=venv)

        def ready(cmd, env, svc, port, path, deadline_s):
            deadline = time.monotonic() + deadline_s
            while time.monotonic() < deadline:
                try:
                    base = "http://127.0.0.1:" + run(*cmd, "port", svc, str(port), env=env).rsplit(":", 1)[1]
                    if http_call("GET", base + path, timeout=5)[0] == 200:
                        return base
                except (OSError, urllib.error.URLError, http.client.HTTPException, subprocess.CalledProcessError, IndexError):
                    pass
                time.sleep(2)
            print(run(*cmd, "logs", "--no-color", "--tail", "60", env=env), file=sys.stderr)
            raise RuntimeError(svc + " did not become healthy")

        t0 = time.monotonic()
        tbase = ready(tcmd, tenv, "transcriber", 8000, "/health", 900)
        report["transcriber_ready_s"] = round(time.monotonic() - t0, 1)
        vbase = ready(vcmd, venv, "defleur-video", 8787, "/healthz", 60)
        client = Client(vbase, "")
        peak = Peak(vcid)
        peak.start()

        # The DNS alias claim, checked from inside the video container.
        caps = client.request("GET", "/v1/capabilities")
        report["video_sees_transcriber"] = caps["workflow"]["transcriber"]
        assert caps["workflow"]["transcriber"].get("reachable") and caps["workflow"]["transcriber"]["url_host"] == "transcriber:8000", caps["workflow"]["transcriber"]
        assert caps["workflow"]["transcriber"]["model_installed"], "Transcriber model not installed"
        assert all(h["available"] for h in caps["workflow"]["helpers"].values())

        t0 = time.monotonic()
        fixture, truth = build_fixture(ts["image"], tdata)
        report["fixture"] = {"text": [v for k, v in PARTS if k == "speech"], "tts": TTS_MODEL + " af_heart (separate fixture container; "
                             "the store recipe's noexec /tmp blocks Kokoro's espeak library)", "duration_s": truth["duration_s"],
                             "ground_truth": truth, "sha256": hashlib.sha256((fixture / "source.mp4").read_bytes()).hexdigest(),
                             "build_s": round(time.monotonic() - t0, 1)}

        def stage(label, op, body, expect_ok=True):
            t = time.monotonic()
            job = client.request("POST", f"/v1/projects/{pid}/stages/{op}", json.dumps(body))
            job = client.wait(job["id"], True)
            info = {"job": job["id"], "state": job["state"], "wall_s": round(time.monotonic() - t, 2)}
            if job["state"] == "needs_review":
                info["summary"] = job["result"]["summary"]
                info["helpers"] = job["result"]["helpers"]
                info["artifacts"] = {a["name"]: a["sha256"] for a in job["result"]["artifacts"]}
                dest = OUT / "bundles" / label
                shutil.rmtree(dest, ignore_errors=True)
                dest.parent.mkdir(exist_ok=True)
                client.stage_bundle(job["id"], dest)  # verifies every artifact hash on download
            else:
                info["error"] = job.get("error")
            report["stages"][label] = info
            if expect_ok:
                assert job["state"] == "needs_review", (label, job.get("error"))
            return job, OUT / "bundles" / label

        project = client.upload(fixture / "source.mp4")
        pid = project["id"]
        report["project"] = {k: project.get(k) for k in ("id", "duration", "width", "height", "source_sha256")}
        src, _ = stage("01-source-audio", "source-audio", {})
        stage("02-preset", "resolve-preset", {"project": {"caption": {"max_words": 4}}})
        pre, _ = stage("03-preflight", "preflight", {"language": "en"})
        assert pre["result"]["summary"]["piece_1_blockers"] == [], pre["result"]["summary"]
        asr, asr_dir = stage("04-asr-source", "asr", {"audio_job": src["id"], "language": "en"})
        receipt = json.loads((asr_dir / "asr.json").read_text())
        words = receipt["words"]
        report["asr"] = {"text": " ".join(w["word"] for w in words), "words": len(words), "language_detected": receipt["language_detected"],
                         "model": receipt["model_resolved"], "provenance": receipt["provenance"], "seconds": receipt["seconds"]}
        expected = {norm(w) for _, v in PARTS if isinstance(v, str) for w in v.split()} - {"um"}
        got = {norm(w["word"]) for w in words}
        report["asr"]["expected_words_missing"] = sorted(expected - got)
        assert len(expected - got) <= 2, report["asr"]
        al, al_dir = stage("05-align", "align", {"asr_job": asr["id"], "language": "en"})
        aligned = [w for s in json.loads((al_dir / "aligned.json").read_text())["segments"] for w in s["words"]]
        report["alignment"] = {"model": al["result"]["summary"]["model"], "aligned_words": len(aligned),
                               "receipt": json.loads((al_dir / "align-receipt.json").read_text()),
                               "words": [{"word": w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in aligned]}
        assert len(aligned) == len(words)
        report["acoustic_ctc"] = caps["workflow"]["acoustic_ctc"]

        # Operator decision (this script stands in for Hermes): cut the filler using evidence, not guesses.
        um = next((w for w in aligned if norm(w["word"]) == "um"), None)
        basis = "aligned ASR word 'um'" if um else "ASR omitted the filler (known asr.py limitation); synthesized clip boundaries used"
        um_start, um_end = (um["start"], um["end"]) if um else (truth["um"]["start_s"], truth["um"]["end_s"])
        before = [w for w in aligned if w["end"] <= um_start + 0.05 and norm(w["word"]) != "um"]
        after = [w for w in aligned if w["start"] >= um_end - 0.05 and norm(w["word"]) != "um"]
        # Cut from just after the last kept word before the filler to just before the first word after the pause.
        cut_start = round(min(before[-1]["end"] + 0.12, um_start - 0.02), 3)
        cut_end = round(max(after[0]["start"] - 0.12, truth["pause"]["end_s"] - 0.3, um_end + 0.05), 3)
        duration = src["result"]["summary"]["duration_s"]
        segments = [{"start_s": 0.0, "end_s": cut_start, "reason": "opening sentence kept whole"},
                    {"start_s": cut_end, "end_s": round(duration, 6), "reason": "continue after removed filler 'um' and shortened pause"}]
        report["edit_decision"] = {"basis": basis, "um": [round(um_start, 3), round(um_end, 3)], "cut": [cut_start, cut_end], "segments": segments}
        asm, asm_dir = stage("06-pcm-assemble", "pcm-assemble", {"audio_job": src["id"], "segments": segments})
        edit_map = json.loads((asm_dir / "edit-map.json").read_text())
        report["edit_map"] = {"duration": edit_map["duration"], "frames": edit_map["frames"], "fps": edit_map["fps"], "samples": edit_map["samples"],
                              "removed_s": round(duration - edit_map["duration"], 4),
                              "segments": [{k: s[k] for k in ("start_s", "end_s", "output_start", "output_end")} for s in edit_map["segments"]]}
        regions = [{"mode": "keep", "start_s": round(w["start"], 3), "end_s": round(w["end"], 3), "word": w["word"].strip()} for w in before + after]
        regions.append({"mode": "drop", "start_s": round(um_start, 3), "end_s": round(um_end, 3), "word": "um", "reason": "filler"})
        regions.sort(key=lambda r: r["start_s"])
        audit, audit_dir = stage("07-speech-cut-audit", "speech-cut-audit", {"assemble_job": asm["id"], "regions": regions})
        cut = json.loads((audit_dir / "cut-regression.json").read_text())
        report["cut_audit"] = {"pass": cut["pass"], "edges": cut["edges"], "failed": [r for r in cut["candidate"] if not r["pass"]],
                               "drop_regions": [r for r in cut["candidate"] if r["mode"] == "drop"],
                               "evidence_sha256": {n: h for n, h in report["stages"]["07-speech-cut-audit"]["artifacts"].items() if n.endswith(".png")}}
        assert cut["pass"], report["cut_audit"]
        scan, _ = stage("08-acoustic-scan", "acoustic-scan", {"assemble_job": asm["id"]})
        easr, easr_dir = stage("09-asr-edited", "asr", {"audio_job": asm["id"], "language": "en"})
        edited_words = [norm(w["word"]) for w in json.loads((easr_dir / "asr.json").read_text())["words"]]
        report["edited_asr"] = {"text": " ".join(edited_words), "um_present": "um" in edited_words,
                                "missing_after_edit": sorted(expected - set(edited_words))}
        assert "um" not in edited_words and len(expected - set(edited_words)) <= 2, report["edited_asr"]
        n = scan["result"]["summary"]["windows"]
        edges = [{"segment": e["segment_index"] if "segment_index" in e else int(e["waveform"].split("-")[0]), "edge": e["edge"], "decision": "keep",
                  "findings": f"Inspected waveform+spectrogram at source {e['source_s']:.3f}s: cut lands in low-energy space, no word onset clipped."}
                 for e in cut["edges"]]
        gate_body = {"assemble_job": asm["id"], "audit_job": audit["id"], "scan_job": scan["id"], "edited_asr_job": easr["id"],
                     "filler_review": {"full_pass_reviewed": True, "candidates": [{"word": "um", "source_start_s": round(um_start, 3), "source_end_s": round(um_end, 3),
                                       "action": "removed", "reason": "hesitation filler; " + basis}]},
                     "acoustic_review": [{"window": i, "findings": "Edited window inspected: continuous speech/silence, no click or doubled syllable."} for i in range(n)],
                     "reviewed_edges": edges}
        # Fail-closed check first: one edge missing must not pass.
        bad, _ = stage("10a-dialogue-gate-incomplete", "dialogue-gate", {**gate_body, "reviewed_edges": edges[:-1]})
        assert not bad["result"]["summary"]["dialogue_gate_pass"]
        gate, gate_dir = stage("10-dialogue-gate", "dialogue-gate", gate_body)
        report["dialogue_gate"] = json.loads((gate_dir / "dialogue-gate-result.json").read_text())
        report["dialogue_gate_incomplete_rejected"] = bad["result"]["summary"]["error"]
        assert report["dialogue_gate"]["pass"], report["dialogue_gate"]
        frames = edit_map["frames"]
        plan = {"locked_timeline": {"fps": edit_map["fps"], "frames": frames, "duration": edit_map["duration"]},
                "visual_plan": {"beats": [{"start": 0, "end": edit_map["duration"], **{k: "speaker on camera (e2e placeholder)" for k in
                    ("spoken_anchor", "viewer_inference", "visual_family", "state_before", "state_after", "causal_action", "caption_treatment", "speaker_return")}}]},
                "crop_ledger": {"source_mode": "cfr", "ranges": [{"start": 0, "end": edit_map["duration"]}]}}
        vp, _ = stage("11-validate-project", "validate-project", plan)
        assert vp["result"]["summary"]["pass"], vp["result"]["summary"]

        # Persistence of stage outputs across restart and recreate.
        jobs = {label: client.request("GET", f"/v1/jobs/{info['job']}") for label, info in report["stages"].items()}
        for label, command in [("restart", ["restart", "-t", "5"]), ("recreate", ["up", "-d", "--force-recreate"])]:
            run(*vcmd, *command, env=venv)
            vbase = ready(vcmd, venv, "defleur-video", 8787, "/healthz", 60)
            client = Client(vbase, "")
            for lbl, job in jobs.items():
                assert client.request("GET", f"/v1/jobs/{job['id']}") == job, lbl
            artifact = client.request("GET", f"/v1/jobs/{asm['id']}/stage-artifacts/edited.wav")
            assert hashlib.sha256(artifact).hexdigest() == report["stages"]["06-pcm-assemble"]["artifacts"]["edited.wav"]
            report[label] = "all stage jobs and edited.wav hash preserved"
        vcid = run(*vcmd, "ps", "-aq", env=venv)
        peak.cid = vcid
        report["wall_time_s"] = round(time.monotonic() - t_all, 1)
        report["video_memory"] = {"cgroup_peak_bytes_before_recreate": peak.peak, "max_sampled_current_bytes": peak.max_current,
                                  "limit_bytes": json.loads(run("docker", "inspect", vcid))[0]["HostConfig"]["Memory"]}
        report["transcriber_stats"] = run("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", run(*tcmd, "ps", "-q", env=tenv))
        client.request("DELETE", f"/v1/projects/{pid}")
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
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("wall_time_s", "asr", "alignment", "edit_decision", "edit_map", "dialogue_gate", "video_memory") if k in report},
                     indent=2, default=str)[:20000])


if __name__ == "__main__":
    main()
