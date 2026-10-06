#!/usr/bin/env python3
"""Standalone stdlib client and offline review bundle. No Hermes dependencies."""
import argparse
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from typing import Any


class Client:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("URL must be an http(s) origin without credentials/path/query")
        if not token:
            raise ValueError("set VIDEO_API_TOKEN in environment")
        self.origin, self.host, self.token = parsed, parsed.hostname, token

    def request(self, method, path, data=None, kind="application/json", missing_ok=False, raw=False) -> Any:
        connection_type = http.client.HTTPSConnection if self.origin.scheme == "https" else http.client.HTTPConnection
        c = connection_type(self.host, self.origin.port, timeout=70)
        try:
            c.request(method, path, body=data, headers={"Authorization": "Bearer " + self.token, "Content-Type": kind})
            response = c.getresponse()
            content = response.read(134217729)
            if len(content) > 134217728:
                raise ValueError("response exceeds client budget")
            if missing_ok and response.status == 404:
                return None
            if response.status >= 300:
                raise ValueError(f"HTTP {response.status}: {content[:300].decode(errors='replace')}")
            return json.loads(content) if not raw and response.getheader("Content-Type") == "application/json" else content
        finally:
            c.close()

    def upload(self, path):
        """Stream a large source; avoid buffering the full fixture in RAM."""
        path = Path(path)
        if not 0 < path.stat().st_size <= 512 * 1024 * 1024:
            raise RuntimeError("source must be at most 512 MiB")
        with path.open("rb") as source:
            expected = hashlib.file_digest(source, "sha256").hexdigest()
            source.seek(0)
            cls = http.client.HTTPSConnection if self.origin.scheme == "https" else http.client.HTTPConnection
            c = cls(self.origin.hostname, self.origin.port, timeout=120)
            try:
                c.request("POST", "/v1/projects", body=source, headers={"Authorization": "Bearer " + self.token,
                    "Content-Type": "video/mp4", "Content-Length": str(path.stat().st_size)})
                response = c.getresponse()
                data = response.read(65537)
                if response.status != 201:
                    raise RuntimeError(f"upload: HTTP {response.status}: {data[:300]!r}")
                project = json.loads(data)
            finally:
                c.close()
        if project["source_sha256"] != expected or self.request("GET", f"/v1/projects/{project['id']}") != project:
            raise RuntimeError("upload hash/read-back mismatch")
        return project

    def stage_bundle(self, jid, destination):
        job = self.wait(jid, True)
        if job["state"] != "needs_review" or not job.get("result", {}).get("stage"):
            raise RuntimeError("stage did not complete: " + str(job.get("error")))
        out = Path(destination)
        out.mkdir(parents=True, exist_ok=False, mode=0o700)
        (out / "job.json").write_text(json.dumps(job, indent=2))
        for artifact in job["result"]["artifacts"]:
            name = artifact["name"]
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name) or name in (".", "..", "job.json"):
                raise RuntimeError("unsafe artifact name")
            data = self.request("GET", f"/v1/jobs/{jid}/stage-artifacts/{name}", raw=True)
            if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise RuntimeError("stage artifact checksum mismatch")
            (out / name).write_bytes(data)
        return {"job": jid, "directory": str(out), "stage": job["result"]["stage"], "delivery_approved": False}

    def wait(self, jid, wait):
        deadline = time.monotonic() + 400
        while True:
            job = self.request("GET", f"/v1/jobs/{jid}")
            if not wait or job["state"] not in ("queued", "running"):
                return job
            if time.monotonic() > deadline:
                raise ValueError("poll deadline reached; job may still be running")
            time.sleep(.3)

    def review(self, jid, directory):
        job = self.wait(jid, True)
        if job["state"] != "needs_review" or job["result"].get("stage"):
            raise ValueError("job did not produce preview review output; use stage-bundle for workflow stages: " + str(job.get("error")))
        result = job["result"]
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        # Refuse to overwrite an existing bundle; hashes verified before each write.
        def save(name, route, checksum):
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name) or name in (".", ".."):
                raise ValueError("unsafe artifact filename")
            content = self.request("GET", route)
            if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError("artifact checksum mismatch")
            (directory / name).write_bytes(content)
        base = f"/v1/jobs/{jid}"
        save("preview.mp4", base + "/preview", result["sha256"])
        review = result.get("review", {})
        for name, artifact in review.get("artifacts", {}).items():
            save(name, base + "/artifacts/" + name, artifact["sha256"])
        (directory / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        if job.get("decision_id"):
            decisions = self.request("GET", f"/v1/projects/{job['project']}/decisions")["decisions"]
            decision = next(d for d in decisions if d["id"] == job["decision_id"])
            (directory / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
        esc = html.escape
        body = ["<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>DeFleur review — not delivery</title>",
                "<style>body{background:#111;color:#eee;font:16px system-ui;max-width:900px;margin:24px auto;padding:16px;overflow-wrap:anywhere}img,audio,video{max-width:100%}video{max-height:480px}section{border-top:1px solid #666;margin-top:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#8ce}</style>",
                "<h1>Review required — not delivery approved</h1>",
                "<p>Listen to the complete preview, then each source edge. Inspect waveform and spectrogram, speech, framing and caption timing. Generated evidence is not an acoustic or creative pass.</p>",
                '<video controls src="preview.mp4"></video><p><a href="preview.mp4">Download exact MP4</a> · <a href="job.json">Hash-bound receipt</a></p>',
                "<p>Preview SHA-256: <code>" + esc(result["sha256"]) + "</code></p>"]
        if review.get("preview_audio"):
            body.append('<h2>Exact preview decoded audio (not locked PCM)</h2><audio controls src="' + esc(review["preview_audio"], quote=True) + '"></audio>')
        for edge in review.get("edges", []):
            body.append(f"<section><h2>Segment {edge['segment']} {esc(edge['edge'])}: source {edge['source_s']}s — unreviewed</h2><p>Window {edge['window_start_s']}–{edge['window_end_s']}s left to right. Cut at vertical marker. Spectrogram 0–8000Hz bottom to top; log magnitude, linear frequency. Waveform normalized per window (not calibrated loudness).</p>")
            for key in ("waveform", "spectrogram"):
                body.append(f'<h3>{key.title()}</h3><img alt="{key}" src="{esc(edge[key], quote=True)}">')
            body.append('<audio controls src="' + esc(edge["audio"], quote=True) + '"></audio></section>')
        body.append("<h2>Unmet delivery gates</h2><pre>" + esc(json.dumps(job["missing_delivery_gates"], indent=2)) + "</pre>")
        body.append("<h2>Submitted plan</h2><pre>" + esc(json.dumps(job["plan"], indent=2)) + "</pre>")
        (directory / "index.html").write_text("\n".join(body), encoding="utf-8")
        return {"directory": str(directory.resolve()), "review": "index.html", "sha256": result["sha256"], "delivery_approved": False}


def identifier(value):
    if not re.fullmatch("[0-9a-f]{32}", value):
        raise argparse.ArgumentTypeError("expected 32 lowercase hex ID")
    return value


def read_bounded(path, maximum):
    with Path(path).open("rb") as f:
        data = f.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("input file exceeds request budget")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("VIDEO_API_URL", "http://127.0.0.1:8787"))
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser("upload"); upload.add_argument("file")
    decision = commands.add_parser("decision"); decision.add_argument("project", type=identifier); decision.add_argument("file")
    decisions = commands.add_parser("decisions"); decisions.add_argument("project", type=identifier)
    render = commands.add_parser("render"); render.add_argument("project", type=identifier)
    choice = render.add_mutually_exclusive_group(required=True)
    choice.add_argument("--decision", type=identifier); choice.add_argument("--plan")
    status = commands.add_parser("status"); status.add_argument("job", type=identifier); status.add_argument("--wait", action="store_true")
    review = commands.add_parser("review"); review.add_argument("job", type=identifier); review.add_argument("directory", type=Path)
    stage = commands.add_parser("stage"); stage.add_argument("project", type=identifier); stage.add_argument("operation", choices=["source-audio", "pcm-assemble", "resolve-preset"]); stage.add_argument("file")
    bundle = commands.add_parser("stage-bundle"); bundle.add_argument("job", type=identifier); bundle.add_argument("directory", type=Path)
    delete = commands.add_parser("delete"); delete.add_argument("project", type=identifier)
    args = parser.parse_args()
    client = Client(args.url, os.environ.get("VIDEO_API_TOKEN", ""))
    if args.command == "upload":
        value = client.upload(args.file)
    elif args.command == "stage":
        value = client.request("POST", f"/v1/projects/{args.project}/stages/{args.operation}", read_bounded(args.file, 65536))
        value = client.wait(value["id"], False)
    elif args.command == "stage-bundle":
        value = client.stage_bundle(args.job, args.directory)
    elif args.command == "decision":
        route = f"/v1/projects/{args.project}/decisions"
        value = client.request("POST", route, read_bounded(args.file, 65536))
        persisted = client.request("GET", route)["decisions"]
        if value not in persisted:
            raise ValueError("decision read-back mismatch")
    elif args.command == "decisions":
        value = client.request("GET", f"/v1/projects/{args.project}/decisions")
    elif args.command == "render":
        data = json.dumps({"decision_id": args.decision}).encode() if args.decision else read_bounded(args.plan, 65536)
        value = client.request("POST", f"/v1/projects/{args.project}/previews", data)
        value = client.wait(value["id"], False)
    elif args.command == "status":
        value = client.wait(args.job, args.wait)
        if args.wait and value["state"] == "failed":
            raise ValueError("job failed: " + str(value.get("error")))
    elif args.command == "review":
        value = client.review(args.job, args.directory)
    else:
        route = f"/v1/projects/{args.project}"
        value = client.request("DELETE", route)
        if client.request("GET", route, missing_ok=True) is not None:
            raise ValueError("delete read-back failed")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (ValueError, RuntimeError, OSError, http.client.HTTPException) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
