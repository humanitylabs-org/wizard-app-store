#!/usr/bin/env python3
"""End-to-end: Hermes Agent recipe + wizard-apps sync + DeFleur Video, as Runtipi 4.8.0 runs them.

Both recipes go through the real pinned Runtipi compose builder (scripts/translate-video-recipe.mjs),
share one external network (Runtipi's tipi_main_network), get fresh bind dirs and Runtipi's post-up
`chmod -Rf a+rwx`. No model is called. Test-only knobs: loopback ephemeral ports, a short sync
interval and grace period, and WIZARD_APPS_STORE_REF (default: this checkout's HEAD, which must be
pushed) so the store list comes from the commit under test.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
VIDEO_IMAGE = os.environ.get("VIDEO_TEST_IMAGE", "wizard-defleur-video:0.6.0-testing")
GRACE = 40


def run(*args, check=True, timeout=240, **kwargs):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(args[:6])} -> {p.returncode}: {(p.stderr or p.stdout)[-800:]}")
    return p.stdout.strip()


def wait(what, fn, timeout):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.monotonic() > deadline:
            raise RuntimeError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(2)


def recipe(app_id, net, tmp, env_extra):
    compose = json.loads(run("node", "scripts/translate-video-recipe.mjs", app_id, cwd=ROOT))["compose"]
    compose["networks"]["tipi_main_network"] = {"name": net, "external": True}
    for svc in compose["services"].values():
        svc["ports"] = [re.sub(r"^\$\{APP_PORT\}:", "127.0.0.1::", p) for p in svc.get("ports", [])]
    data = tmp / app_id
    data.mkdir()
    fields = json.loads((ROOT / f"apps/{app_id}/config.json").read_text())["form_fields"]
    env = {**os.environ, "APP_DATA_DIR": str(data),
           **{f["env_variable"]: str(f["default"]).lower() if isinstance(f.get("default"), bool) else str(f["default"])
              for f in fields if "default" in f}, **env_extra}
    path = tmp / f"{app_id}.json"
    path.write_text(json.dumps(compose))
    return compose, data, env, ["docker", "compose", "-p", f"{net}-{app_id}", "-f", str(path)]


def runtipi_chmod(data, image):
    # Exactly Runtipi 4.8.0's post-up permission step (host root), on disposable data only.
    run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount", f"type=bind,source={data},target=/fixture",
        "--entrypoint", "/bin/chmod", image, "-Rf", "a+rwx", "/fixture")


def main():
    if subprocess.run(["docker", "image", "inspect", VIDEO_IMAGE], capture_output=True).returncode:
        run("docker", "pull", VIDEO_IMAGE, timeout=900)
    net = "wzapps-e2e-" + secrets.token_hex(4)
    ref = os.environ.get("WIZARD_APPS_STORE_REF") or run("git", "rev-parse", "HEAD", cwd=ROOT)
    report: dict = {"network": "external, named like runtipi_tipi_main_network", "store_ref": ref}
    with tempfile.TemporaryDirectory(prefix=net + "-", dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        h_compose, h_data, h_env, h = recipe("hermes-agent", net, tmp, {
            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": secrets.token_urlsafe(24),
            "HERMES_DASHBOARD_BASIC_AUTH_SECRET": secrets.token_hex(32)})
        image = h_compose["services"]["hermes-agent"]["image"]
        side = h_compose["services"]["wizard-apps"]
        side["environment"].update(WIZARD_APPS_INTERVAL_S="5", WIZARD_APPS_GRACE_S=str(GRACE), WIZARD_APPS_STORE_REF=ref)
        (tmp / "hermes-agent.json").write_text(json.dumps(h_compose))
        v_compose, v_data, v_env, v = recipe("defleur-video", net, tmp, {})
        v_compose["services"]["defleur-video"].update(image=VIDEO_IMAGE, pull_policy="never")
        (tmp / "defleur-video.json").write_text(json.dumps(v_compose))

        def hx(*args, check=True):
            return run(*h, "exec", "-T", "-u", "1000:1000", "-e", "HOME=/opt/data", "hermes-agent", *args, env=h_env, check=check)

        def side_logs():
            return run(*h, "logs", "--no-color", "--no-log-prefix", "wizard-apps", env=h_env)

        def gateway_log():
            return hx("sh", "-c", "cat /opt/data/logs/*.log 2>/dev/null; true")

        def servers():
            return json.loads(hx("/opt/hermes/.venv/bin/python3", "-c",
                "import yaml,json;print(json.dumps((yaml.safe_load(open('/opt/data/config.yaml')) or {}).get('mcp_servers') or {}))"))

        def apps_json():
            return hx("sh", "-c", "cat /opt/data/wizard-apps/apps.json 2>/dev/null; true")

        def skill():
            return hx("sh", "-c", "cat /opt/data/skills/wizard-apps/SKILL.md 2>/dev/null; true")

        def mcp_list():
            return hx("hermes", "mcp", "list")

        def user_state():
            text = hx("sh", "-c", "cat /opt/data/config.yaml /opt/data/skills/my-notes/SKILL.md")
            return {"comment": "# owner comment: keep me" in text, "entry": servers().get("my-tools"),
                    "skill": hashlib.sha256(hx("cat", "/opt/data/skills/my-notes/SKILL.md").encode()).hexdigest()}

        run("docker", "network", "create", net)
        try:
            # 1. Hermes Agent alone.
            run(*h, "up", "-d", env=h_env)
            runtipi_chmod(h_data, image)
            wait("dashboard", lambda: "200" in hx("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                                  "http://127.0.0.1:9119/api/status", check=False), 180)
            wait("'no Wizard apps found'", lambda: "no Wizard apps found" in side_logs(), 120)
            assert "defleur-video" not in servers(), servers()
            assert "No Wizard apps are running" in skill()
            assert json.loads(apps_json())["apps"] == []
            info = json.loads(run("docker", "inspect", run(*h, "ps", "-q", "hermes-agent", env=h_env)))[0]
            img = json.loads(run("docker", "image", "inspect", image))[0]["Config"]
            assert info["Config"]["Image"] == image and info["Config"]["Entrypoint"] == img["Entrypoint"]
            assert info["Config"]["Cmd"] == ["gateway", "run"] and info["RestartCount"] == 0
            report["1_alone"] = {"sidecar_log": side_logs().splitlines(), "wizard_entries": [], "hermes_image": image}

            # Owner's own MCP entry, skill and config comment, added the way an owner would.
            hx("hermes", "config", "set", "mcp_servers.my-tools", '{"url": "http://my-tools.invalid:9/mcp", "enabled": false}')
            hx("sh", "-c", "sed -i '1i # owner comment: keep me' /opt/data/config.yaml && mkdir -p /opt/data/skills/my-notes && "
               "printf -- '---\\nname: my-notes\\ndescription: Owner notes.\\n---\\n\\nMine.\\n' > /opt/data/skills/my-notes/SKILL.md")
            mine = user_state()
            assert mine["comment"] and mine["entry"] == {"url": "http://my-tools.invalid:9/mcp", "enabled": False}

            # 2. DeFleur Video appears; Hermes is not restarted.
            started = time.monotonic()
            run(*v, "up", "-d", env=v_env)
            runtipi_chmod(v_data, VIDEO_IMAGE)
            wait("defleur-video in hermes mcp list", lambda: re.search(r"defleur-video.*enabled", mcp_list()), 150)
            listed = time.monotonic() - started
            wait("gateway reconcile", lambda: re.search(r"MCP servers reconciled.*added=\['defleur-video'\]", gateway_log()), 150)
            reconciled = time.monotonic() - started
            test = hx("hermes", "mcp", "test", "defleur-video")
            tools = len(re.findall(r"^\s+\S+\s{2,}", test.split("Tools discovered")[-1], re.M)) if "Tools discovered" in test else None
            assert servers()["defleur-video"] == {"url": "http://defleur-video:8787/mcp", "enabled": True}
            text = skill()
            assert "DeFleur Video" in text and "mcp__defleur_video__" in text and "workflow_guide" in text
            discovered = json.loads(apps_json())["apps"]
            assert [(a["id"], a["type"], a["mcp_url"], a["mcp_ready"]) for a in discovered] == \
                [("defleur-video", "mcp", "http://defleur-video:8787/mcp", True)], discovered
            report["2_connect"] = {"apps_json": discovered,"mcp_list_after_s": round(listed), "gateway_reconciled_after_s": round(reconciled),
                "gateway_log": re.findall(r".*MCP servers reconciled.*", gateway_log())[-1][-160:],
                "mcp_test_tail": [l.strip() for l in test.splitlines() if l.strip()][-4:], "tools_counted": tools,
                "hermes_restarts": json.loads(run("docker", "inspect", info["Id"]))[0]["RestartCount"]}

            # 3. Owner's things survive several cycles; steady state writes nothing.
            stamp = "stat -c '%Y %s' /opt/data/config.yaml /opt/data/wizard-apps/apps.json /opt/data/skills/wizard-apps/SKILL.md"
            before = (hx("sh", "-c", stamp), apps_json(), skill())
            time.sleep(20)
            assert user_state() == mine
            assert (hx("sh", "-c", stamp), apps_json(), skill()) == before, "steady state must not rewrite files"
            report["3_user_untouched"] = mine

            # 4. App stops -> entry removed after the grace period; comes back on restart.
            run(*v, "stop", "-t", "5", env=v_env)
            stopped = time.monotonic()
            wait("entry removed", lambda: "defleur-video" not in servers(), GRACE + 60)
            removed = time.monotonic() - stopped
            assert removed >= GRACE - 1, removed
            wait("gateway teardown", lambda: re.search(r"MCP servers reconciled.*removed=\['defleur-video'\]", gateway_log()), 150)
            run(*v, "start", env=v_env)
            wait("entry back", lambda: servers().get("defleur-video") == {"url": "http://defleur-video:8787/mcp", "enabled": True}, 120)
            assert user_state() == mine
            report["4_stop_start"] = {"removed_after_s": round(removed), "grace_s": GRACE, "restored": True}

            # 5. Runtipi update: restart, then recreate.
            for label, cmd in [("restart", ["restart"]), ("recreate", ["up", "-d", "--force-recreate"])]:
                run(*h, *cmd, env=h_env)
                runtipi_chmod(h_data, image)
                wait("dashboard", lambda: "200" in hx("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                                      "http://127.0.0.1:9119/api/status", check=False), 180)
                wait("entry after " + label, lambda: re.search(r"defleur-video.*enabled", mcp_list()), 120)
                assert "DeFleur Video" in skill() and user_state() == mine
            info = json.loads(run("docker", "inspect", run(*h, "ps", "-q", "hermes-agent", env=h_env)))[0]
            assert info["Config"]["Image"] == image and info["Config"]["Cmd"] == ["gateway", "run"]
            report["5_update"] = "restart + recreate: entry, skill and owner's settings intact; official image, gateway run"

            # Off switch: removes only the sync's own entry and skill.
            off = {**h_env, "WIZARD_APPS_SYNC": "false"}
            run(*h, "up", "-d", "wizard-apps", env=off)
            wait("off cleanup", lambda: "defleur-video" not in servers() and not skill(), 60)
            assert user_state() == mine
            run(*h, "up", "-d", "wizard-apps", env=h_env)
            wait("back on", lambda: "defleur-video" in servers(), 60)
            report["off_switch"] = "WIZARD_APPS_SYNC=false removed only its own entry and skill; true restored them"
            logs = side_logs().splitlines()
            assert len(logs) < 40, logs
            report["sidecar_log_lines_total"] = len(logs)
        except Exception:
            print(run(*h, "logs", "--no-color", "--tail", "40", env=h_env, check=False)[-4000:], file=sys.stderr)
            raise
        finally:
            run(*v, "down", "--remove-orphans", env=v_env, check=False)
            run(*h, "down", "--remove-orphans", env=h_env, check=False)
            run("docker", "network", "rm", net, check=False)
            for data in (h_data, v_data):
                runtipi_chmod(data, image)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
