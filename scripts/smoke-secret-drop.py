"""Secret Drop release smoke: real Runtipi translation, fresh bind + permission step,
real browser over plain http:// on a NON-localhost address (insecure context), CLI client
keygen/create/pickup, one-time link, restart/recreate persistence, no plaintext at rest,
no capability or value in logs, cleanup.

Run: uv run --with playwright==1.63.0 --with cryptography==50.0.2 python scripts/smoke-secret-drop.py
Env: SECRET_DROP_IMAGE (default wizard-secret-drop:test), SMOKE_HOST_IP (default: primary
non-loopback IPv4), SMOKE_OUTPUT (evidence dir), CHROME_PATH (optional).
"""
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "images/secret-drop/client.py"
IMAGE = os.environ.get("SECRET_DROP_IMAGE", "wizard-secret-drop:test")
VERSION = json.loads((ROOT / "apps/secret-drop/config.json").read_text())["version"]


def run(*args, **kwargs):
    p = subprocess.run(args, check=True, capture_output=True, text=True, timeout=120, **kwargs)
    return p.stdout.strip()


def host_ip() -> str:
    if os.environ.get("SMOKE_HOST_IP"):
        return os.environ["SMOKE_HOST_IP"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # TEST-NET; UDP connect sends nothing
        return s.getsockname()[0]


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def cli(*args, env=None):
    return subprocess.run([sys.executable, str(CLIENT), *args], capture_output=True, text=True, timeout=60, env=env)


def main():
    ip = host_ip()
    assert not ip.startswith("127."), "use a non-loopback address to prove the insecure-context path"
    name = "secret-drop-smoke-" + secrets.token_hex(4)
    secret_value = "sk-smoke-" + secrets.token_urlsafe(24)
    report: dict = {"test": "translated recipe + fresh bind + insecure-context browser + CLI client", "image": IMAGE}
    out_dir = Path(os.environ.get("SMOKE_OUTPUT") or tempfile.gettempdir()) / name
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=name + "-", dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        translated = json.loads(run("node", "scripts/translate-video-recipe.mjs", "secret-drop", cwd=ROOT))
        report["runtipi"] = {k: v for k, v in translated.items() if k != "compose"}
        compose = translated["compose"]
        service = compose["services"]["secret-drop"]
        assert service["image"] == f"ghcr.io/humanitylabs-org/secret-drop:{VERSION}"
        assert service["user"] == "1000:1000" and service["read_only"] is True and service["cap_drop"] == ["ALL"]
        assert service["restart"] == "unless-stopped"
        assert service["ports"] == ["${APP_PORT}:8792"]
        assert service["volumes"] == ["${APP_DATA_DIR}/data:/data"]
        # Test-only substitutions: local candidate image, ephemeral port on a non-loopback IP, isolated network.
        service["image"] = IMAGE
        service["pull_policy"] = "never"
        # Fixed host port like Runtipi's APP_PORT, so links and client state survive recreate.
        with socket.socket() as probe:
            probe.bind((ip, 0))
            port = probe.getsockname()[1]
        service["ports"] = [f"{ip}:{port}:8792"]
        compose["networks"]["tipi_main_network"] = {"name": name, "external": True}
        app = tmp / "app-data"
        app.mkdir()
        env = {**os.environ, "APP_DATA_DIR": str(app), "SECRET_DROP_PUBLIC_URL": "", "SECRET_DROP_API_TOKEN": ""}
        recipe = tmp / "compose.json"
        recipe.write_text(json.dumps(compose))
        cmd = ["docker", "compose", "-p", name, "-f", str(recipe)]
        agent = tmp / "agent"
        cenv = {k: v for k, v in os.environ.items() if k != "SECRET_DROP_API_TOKEN"}

        def helper(code, host_root=False, user="0:0"):
            caps = [] if host_root else ["--cap-drop", "ALL"]
            return run("docker", "run", "--rm", "--network", "none", "--read-only", *caps, "--user", user,
                       "--mount", f"type=bind,source={app},target=/fixture", "--entrypoint", "python3", IMAGE, "-c", code)

        def base():
            return "http://" + run(*cmd, "port", "secret-drop", "8792", env=env)

        def ready(timeout=45):
            deadline = time.monotonic() + timeout
            while True:
                try:
                    url = base()
                    status, health = http_json(url + "/health")
                    if status == 200:
                        return url, health
                except (OSError, subprocess.CalledProcessError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    print(run(*cmd, "logs", "--no-color", env=env), file=sys.stderr)
                    raise RuntimeError("service not ready")
                time.sleep(0.25)

        run("docker", "network", "create", name)
        try:
            run(*cmd, "up", "-d", env=env)
            cid = run(*cmd, "ps", "-aq", env=env)
            assert cid
            before = json.loads(helper("import os,json; s=os.stat('/fixture/data'); print(json.dumps({'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode & 511)}))"))
            assert before["uid"] == 0 and before["mode"] == "0o755", before
            report["fresh_bind_before_runtipi_permission_step"] = before
            time.sleep(2)
            waiting_log = run(*cmd, "logs", "--no-color", env=env)
            report["waits_for_writable_data_dir"] = "waiting for /data to become writable" in waiting_log
            # Exactly Runtipi 4.8.0's verified post-up permission command, as host root, on disposable data.
            helper("import subprocess; subprocess.run(['chmod','-Rf','a+rwx','/fixture'],check=True)", host_root=True)
            url, health = ready()
            assert health == {"status": "ok", "version": VERSION}, health
            state = json.loads(run("docker", "inspect", "--format", "{{json .State}}", cid))
            report["after_permission_step"] = {"running": state["Running"], "restart_count": int(run("docker", "inspect", "--format", "{{.RestartCount}}", cid)),
                                               "health": health}
            assert url.startswith(f"http://{ip}:"), url
            report["page_origin_kind"] = "non-loopback IPv4 over plain http"

            # Static agent bootstrap served by the app.
            with urllib.request.urlopen(url + "/client.py", timeout=5) as r:
                assert r.read() == CLIENT.read_bytes()
            with urllib.request.urlopen(url + "/SKILL.md", timeout=5) as r:
                assert r.read() == (ROOT / "images/secret-drop/SKILL.md").read_bytes()

            # Agent: keygen + create via the shipped CLI.
            p = cli("keygen", "--key-file", str(agent / "agent.key"), env=cenv)
            assert p.returncode == 0, p.stderr
            fp = json.loads(p.stdout)["fingerprint"]
            p = cli("create", "--relay", url, "--key-file", str(agent / "agent.key"), "--key", "SMOKE_API_KEY",
                    "--label", "Smoke test API key", "--requester", "Smoke agent", "--state", str(agent / "req.json"), env=cenv)
            assert p.returncode == 0, p.stderr
            created = json.loads(p.stdout)
            capability = created["request_url"].split("#c=", 1)[1]
            assert created["request_url"].startswith(url + "/#c=")

            # Human: real Chromium, plain http on a non-loopback IP (insecure context).
            browser_report = {}
            with sync_playwright() as pw:
                chrome = os.environ.get("CHROME_PATH")
                browser = pw.chromium.launch(**({"executable_path": chrome} if chrome else {}), headless=True)
                ctx = browser.new_context(viewport={"width": 420, "height": 860})
                page = ctx.new_page()
                console = []
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
                page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
                requests_seen = []
                page.on("request", lambda r: requests_seen.append(r.url))
                page.goto(created["request_url"], wait_until="networkidle")
                page.wait_for_selector("#secret-form:not([hidden])", timeout=15000)
                browser_report["isSecureContext"] = page.evaluate("window.isSecureContext")
                browser_report["crypto_subtle_available"] = page.evaluate("!!(window.crypto && window.crypto.subtle)")
                browser_report["getRandomValues_available"] = page.evaluate("typeof crypto.getRandomValues === 'function'")
                assert browser_report["isSecureContext"] is False
                assert browser_report["crypto_subtle_available"] is False
                assert browser_report["getRandomValues_available"] is True
                browser_report["fragment_removed_from_address_bar"] = "#" not in page.url
                assert browser_report["fragment_removed_from_address_bar"]
                shown = {k: page.text_content("#" + k) for k in ("heading", "requester", "key", "fingerprint")}
                assert shown == {"heading": "Smoke test API key", "requester": "Smoke agent", "key": "SMOKE_API_KEY", "fingerprint": fp}, shown
                browser_report["shown"] = shown
                page.fill("#value", secret_value)
                assert page.get_attribute("#value", "type") == "password"
                page.click("#reveal")
                assert page.get_attribute("#value", "type") == "text" and page.input_value("#value") == secret_value
                page.click("#reveal")
                page.screenshot(path=str(out_dir / "1-request.png"))
                with page.expect_response(lambda r: r.url.endswith("/api/submit")) as resp_info:
                    page.click("#submit")
                submit_resp = resp_info.value
                sent_body = submit_resp.request.post_data or ""
                browser_report["submit_status"] = submit_resp.status
                browser_report["submitted_body_contains_plaintext"] = secret_value in sent_body
                browser_report["submitted_body_keys"] = sorted(json.loads(sent_body))
                assert submit_resp.status == 200 and not browser_report["submitted_body_contains_plaintext"]
                assert browser_report["submitted_body_keys"] == ["ct", "enc", "suite", "version"]
                page.wait_for_function("document.getElementById('heading').textContent === 'Sent'", timeout=10000)
                browser_report["after_submit_heading"] = page.text_content("#heading")
                browser_report["input_cleared"] = page.input_value("#value") == ""
                page.screenshot(path=str(out_dir / "2-sent.png"))
                assert all(u.startswith(url) for u in requests_seen), requests_seen
                browser_report["external_requests"] = 0
                page2 = ctx.new_page()
                page2.goto(created["request_url"], wait_until="networkidle")
                page2.wait_for_function("document.getElementById('heading').textContent === 'Already used'", timeout=10000)
                browser_report["reopen_heading"] = page2.text_content("#heading")
                page2.screenshot(path=str(out_dir / "3-reopen.png"))
                browser_report["console"] = console
                assert not [c for c in console if "Content Security Policy" in c or c.startswith("pageerror")], console
                browser_report["chromium"] = browser.version
                browser.close()
            report["browser"] = browser_report

            # Agent: pickup once into a test .env, then compare.
            env_file = agent / "test.env"
            env_file.write_text("EXISTING=keep\n")
            p = cli("pickup", "--state", str(agent / "req.json"), "--write-env", str(env_file), env=cenv)
            assert p.returncode == 0, p.stderr
            picked = json.loads(p.stdout)
            assert secret_value not in p.stdout + p.stderr
            content = env_file.read_text()
            assert content == f"EXISTING=keep\nSMOKE_API_KEY='{secret_value}'\n", "env content mismatch"
            report["pickup"] = {"value_matches": True, "env_mode": oct(env_file.stat().st_mode & 0o777),
                                "other_entries_preserved": True, "value_bytes": picked["value_bytes"]}
            assert report["pickup"]["env_mode"] == "0o600"
            status, body = http_json(url + "/api/request", {"X-Secret-Drop-Capability": capability})
            assert (status, body["error"]) == (409, "used"), (status, body)

            # Persistence: a pending request survives restart and recreate.
            p = cli("create", "--relay", url, "--key-file", str(agent / "agent.key"), "--key", "SECOND_TOKEN",
                    "--label", "Second", "--requester", "Smoke agent", "--state", str(agent / "second.json"), env=cenv)
            assert p.returncode == 0, p.stderr
            cap2 = json.loads(p.stdout)["request_url"].split("#c=", 1)[1]
            persistence = {}
            for action in (("restart",), ("up", "-d", "--force-recreate")):
                run(*cmd, *action, env=env)
                url, _ = ready()
                status, body = http_json(url + "/api/request", {"X-Secret-Drop-Capability": cap2})
                persistence[" ".join(action)] = status
                assert status == 200, (action, status, body)
            report["pending_request_persists"] = persistence
            # Runtipi re-runs its permission step after start; service must keep working.
            helper("import subprocess; subprocess.run(['chmod','-Rf','a+rwx','/fixture'],check=True)", host_root=True)
            url, _ = ready()
            p = cli("cancel", "--state", str(agent / "second.json"), env=cenv)
            assert p.returncode == 0 and json.loads(p.stdout)["status"] == "cancelled", p.stderr

            # No plaintext / capability / pickup secret at rest, none in logs.
            data_hits = json.loads(helper(
                "import json,pathlib,sys; needles=" + json.dumps([secret_value, capability, cap2]) +
                "; blob=b''.join(p.read_bytes() for p in pathlib.Path('/fixture/data').rglob('*') if p.is_file());"
                "print(json.dumps({'files':sorted(p.name for p in pathlib.Path('/fixture/data').iterdir()),'hits':[n for n in needles if n.encode() in blob]}))",
                user="1000:1000"))
            assert data_hits["hits"] == [], data_hits
            report["data_dir"] = {"files": data_hits["files"], "plaintext_or_capability_found": False}
            logs = run(*cmd, "logs", "--no-color", env=env)
            (out_dir / "service.log").write_text(logs)
            assert secret_value not in logs and capability not in logs and cap2 not in logs and "SMOKE_API_KEY" not in logs
            assert not re.search(r"[0-9a-f]{64}", logs)
            report["logs"] = {"lines": len(logs.splitlines()), "contain_secret_or_capability_or_request_id": False}
            report["result"] = "pass"
        finally:
            subprocess.run([*cmd, "down", "-v", "--remove-orphans"], env=env, capture_output=True, timeout=120)
            subprocess.run(["docker", "network", "rm", name], capture_output=True, timeout=60)
            # Let the unprivileged host user remove Runtipi-owned test data.
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                            f"type=bind,source={app},target=/fixture", "--entrypoint", "/bin/chmod", IMAGE, "-Rf", "a+rwx", "/fixture"],
                           capture_output=True, timeout=60)
            shutil.rmtree(app, ignore_errors=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
