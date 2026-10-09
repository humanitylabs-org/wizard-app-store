#!/usr/bin/env python3
"""AI Accounts + Hermes Agent (Wizard build): logged-out end-to-end checks. Never logs in, never calls a model.

1. Existing /opt/data: the Wizard image leaves pre-existing files byte-identical and ends with the same file set
   as the official image it extends (same minimal fixture, same compose environment).
2. Hermes inside the Wizard image: the DirectSDK provider is discovered (bundled), offered by the provider list,
   and a request on the logged-out shared volume fails with the plugin's own "no usable login" message.
3. The plugin's own unit tests (pinned commit) pass against the Hermes core inside the image.
4. Runtipi-style install of both translated recipes as separate projects on one shared network: they share the
   fixed-name volume; files written by either app's uid are readable and writable by the other; Hermes reaches
   AI Accounts by service name; uninstalling one app (`down -v`, as Runtipi does) keeps the volume.
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
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
AIA = os.environ.get("AI_ACCOUNTS_IMAGE", "wizard-ai-accounts:test")
HERMES = os.environ.get("HERMES_IMAGE", "wizard-hermes-agent:test")
TAG = "zz-aia-smoke-" + secrets.token_hex(3)
PROVIDER = "claude-subscription-directsdk-experimental"
report: dict = {"ai_accounts_image": AIA, "hermes_image": HERMES}


def run(*args, timeout=180, check=True, **kw):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if check and p.returncode:
        raise RuntimeError(f"{args[:4]} exit {p.returncode}: {(p.stderr or p.stdout)[-800:]}")
    return p.stdout.strip()


def official_image() -> str:
    text = (ROOT / "images/hermes-agent/Dockerfile").read_text()
    return next(line.split()[1] for line in text.splitlines() if line.startswith("FROM nousresearch/hermes-agent"))


def tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_file() and not p.is_symlink():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


FIXTURE = {
    "config.yaml": "model:\n  provider: openai-codex\n  default: gpt-5.5\nplugins:\n  enabled: []\n",
    "memories/MEMORY.md": "Owner prefers short answers.\n",
    "skills/owner-skill/SKILL.md": "---\nname: owner-skill\ndescription: Use when testing.\n---\nKeep me.\n",
    "sessions/20261001_000000_abcdef.json": json.dumps({"id": "20261001_000000_abcdef", "messages": [{"role": "user", "content": "hi"}]}),
    # An existing install already has API_SERVER_KEY (the official image generates one on first boot when missing).
    ".env": "SOME_OWNER_SETTING=keep\nAPI_SERVER_KEY=fixture-not-a-secret-0123456789abcdef\n",
}


def boot_hermes(image: str, data: Path, extra=()):
    name = f"{TAG}-boot-{secrets.token_hex(2)}"
    env = ["-e", "HERMES_UID=1000", "-e", "HERMES_GID=1000", "-e", "HERMES_DASHBOARD=1", "-e", "HERMES_DASHBOARD_HOST=0.0.0.0",
           "-e", "HERMES_DASHBOARD_PORT=9119", "-e", "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=smoke",
           "-e", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=" + secrets.token_urlsafe(24),
           "-e", "HERMES_DASHBOARD_BASIC_AUTH_SECRET=" + secrets.token_hex(32)]
    run("docker", "run", "-d", "--name", name, "-p", "127.0.0.1::9119", "-v", f"{data}:/opt/data", *extra, *env, image,
        "gateway", "run")
    try:
        port = run("docker", "port", name, "9119/tcp").rsplit(":", 1)[1]
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                status = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5))
                if status.get("auth_required") is True:
                    break
            except (OSError, ValueError):
                time.sleep(2)
        else:
            raise RuntimeError(f"{image} dashboard not ready")
        time.sleep(5)
    finally:
        run("docker", "stop", "-t", "30", name, check=False, timeout=90)
        run("docker", "rm", "-f", name, check=False)


def data_parity(tmp: Path):
    trees = {}
    for label, image in (("official", official_image()), ("wizard", HERMES)):
        data = tmp / label
        for rel, text in FIXTURE.items():
            (data / rel).parent.mkdir(parents=True, exist_ok=True)
            (data / rel).write_text(text)
        os.chmod(data, 0o777)
        vol = f"{TAG}-{label}-claude"
        boot_hermes(image, data, ["-v", f"{vol}:/claude"] if label == "wizard" else [])
        run("docker", "volume", "rm", "-f", vol, check=False)
        # Read through a container: files are now owned by the remapped uid.
        listing = run("docker", "run", "--rm", "-v", f"{data}:/d:ro", "--entrypoint", "sh", official_image(), "-c",
                      "cd /d && find . -type f ! -path './logs/*' -exec sha256sum {} +")
        # The official image's own migration backups carry a boot timestamp; compare them by name pattern.
        trees[label] = {re.sub(r"\.\d{8}-\d{6}$", ".<ts>", line.split("  ", 1)[1][2:]): line.split("  ", 1)[0]
                        for line in listing.splitlines()}
    # The official image may migrate files itself (it rewrites config.yaml). The Wizard build must leave
    # every owner file exactly as the official image does, and add or drop nothing.
    unchanged = []
    for rel, text in FIXTURE.items():
        assert trees["wizard"][rel] == trees["official"][rel], f"wizard build differs from official on {rel}"
        if trees["wizard"][rel] == hashlib.sha256(text.encode()).hexdigest():
            unchanged.append(rel)
    volatile = ("state.db", ".lock", ".pid", "gateway_state", "auth.json", ".tmp", "logs/", "cache/", ".pyc",
                "spawn-ledger.json", "state/gateway.")
    only = {k: sorted(p for p in set(trees[k]) - set(trees[o]) if not any(v in p for v in volatile))
            for k, o in (("official", "wizard"), ("wizard", "official"))}
    assert only == {"official": [], "wizard": []}, only
    differ = sorted(p for p in set(trees["wizard"]) & set(trees["official"])
                    if trees["wizard"][p] != trees["official"][p] and not any(v in p for v in volatile))
    report["opt_data"] = {"owner_files_same_as_official_boot": sorted(FIXTURE), "byte_identical_to_fixture": unchanged,
                          "file_set_equal_to_official": True, "other_differing_files": differ,
                          "files_after_boot": len(trees["wizard"])}


def hermes_provider(vol: str):
    script = f"""
set -e
mkdir -p /tmp/h && cd /tmp
claude --version
/opt/hermes/.venv/bin/python - <<'EOF'
import providers, json
from hermes_cli.models import list_available_providers
p = providers.get_provider_profile("{PROVIDER}")
rows = [r for r in list_available_providers() if r["id"] == "{PROVIDER}"]
print(json.dumps({{"profile": type(p).__name__, "source": providers._SOURCES.get("{PROVIDER}"), "listed": rows}}))
EOF
printf 'model:\\n  provider: {PROVIDER}\\n  default: opus\\n' > /tmp/h/config.yaml
timeout 150 hermes chat -q "Reply OK" --oneshot > /tmp/out.txt 2>&1 || true
grep -c "has no usable login" /tmp/out.txt || true
grep -c "Traceback" /tmp/out.txt || true
"""
    out = run("docker", "run", "--rm", "--user", "1000:1000", "-e", "HOME=/tmp", "-e", "HERMES_HOME=/tmp/h",
              "-v", f"{vol}:/claude", "--entrypoint", "sh", HERMES, "-c", script, timeout=300).splitlines()
    info = json.loads(out[1])
    assert out[0].startswith("2.1.263 "), out[0]
    assert info["profile"] == "ClaudeOAuthDirectSDKProfile" and info["source"] == "bundled", info
    assert info["listed"] and info["listed"][0]["label"] == "Claude Subscription DirectSDK (Experimental)", info
    assert int(out[2]) > 0, "plugin's logged-out message missing"
    assert int(out[3]) == 0, "traceback in logged-out request"
    report["hermes_provider"] = {"claude": out[0], **info, "logged_out_request": "plugin 'no usable login' message, no traceback"}


def plugin_tests(tmp: Path):
    text = (ROOT / "images/hermes-agent/fetch-directsdk-plugin.py").read_text()
    commit = text.split('COMMIT = "', 1)[1].split('"', 1)[0]
    tgz = tmp / "plugin.tgz"
    url = f"https://codeload.github.com/NousResearch/hermes-plugin-claude-subscription-directsdk/tar.gz/{commit}"
    tgz.write_bytes(urllib.request.urlopen(url, timeout=120).read())
    os.chmod(tmp, 0o755)
    script = ("set -e; mkdir -p /tmp/p /tmp/home && tar xzf /w/plugin.tgz -C /tmp/p --strip-components=1 && cd /tmp/p && "
              "HOME=/tmp/home UV_CACHE_DIR=/tmp/uv HERMES_AGENT_REPO=/opt/hermes uv run -q --no-project "
              "--python /opt/hermes/.venv/bin/python --with pytest==8.4.2 python -m pytest -q -p no:cacheprovider 2>&1 | tail -1")
    out = run("docker", "run", "--rm", "--user", "1000:1000", "-v", f"{tmp}:/w:ro", "--entrypoint", "sh", HERMES, "-c",
              script, timeout=600)
    assert " passed" in out and "failed" not in out and "error" not in out, out
    report["plugin_unit_tests"] = {"commit": commit, "result": out}


def translated(app: str) -> dict:
    compose = json.loads(run("node", "scripts/translate-video-recipe.mjs", app, cwd=ROOT))["compose"]
    return compose


def two_apps(tmp: Path):
    net, vol = f"{TAG}-net", f"{TAG}-claude"
    run("docker", "network", "create", net)
    projects = []
    try:
        for app, image in (("wizard-ai-accounts", AIA), ("hermes-agent", HERMES)):
            c = translated(app)
            assert c["volumes"] == {"claude-login": {"name": "wizard-ai-accounts-claude"}}, c["volumes"]
            c["volumes"]["claude-login"]["name"] = vol  # test-only name, never the real one
            c["networks"]["tipi_main_network"] = {"name": net, "external": True}
            s = c["services"][app]
            s["image"] = image
            s["ports"] = ["127.0.0.1::" + s["ports"][0].split(":")[-1]]
            s.pop("labels", None)
            env = {**os.environ, "APP_DATA_DIR": str(tmp / app), "AI_ACCOUNTS_PASSWORD": "",
                   "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "smoke",
                   "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": secrets.token_urlsafe(24),
                   "HERMES_DASHBOARD_BASIC_AUTH_SECRET": secrets.token_hex(32)}
            (tmp / app / "data").mkdir(parents=True)
            os.chmod(tmp / app / "data", 0o777)
            f = tmp / f"{app}.json"
            f.write_text(json.dumps(c))
            cmd = ["docker", "compose", "-p", f"{TAG}-{app}", "-f", str(f)]
            projects.append((cmd, env))
            run(*cmd, "up", "-d", env=env, timeout=300)
        aia_cmd, aia_env = projects[0]
        h_cmd, h_env = projects[1]
        aia = run(*aia_cmd, "ps", "-q", env=aia_env)
        hermes = run(*h_cmd, "ps", "-q", env=h_env)
        deadline = time.monotonic() + 240
        while True:  # Hermes finishes its uid remap, then the gateway runs as uid 1000
            ps = run("docker", "exec", hermes, "sh", "-c", "ps -o user=,args= -u 1000 | grep -c 'gateway run' || true", check=False)
            if ps.strip() not in ("", "0") or time.monotonic() > deadline:
                break
            time.sleep(3)
        mode = run("docker", "exec", aia, "stat", "-c", "%u:%g %a", "/claude")
        assert mode == "1000:1000 700", mode
        hid = run("docker", "exec", hermes, "id", "-u", "hermes")
        assert hid == "1000", hid
        run("docker", "exec", "-u", "1000:1000", aia, "sh", "-c", "printf from-accounts > /claude/zz-a")
        run("docker", "exec", "-u", "hermes", hermes, "sh", "-c",
            "cat /claude/zz-a && printf ' +hermes' >> /claude/zz-a && printf from-hermes > /claude/zz-h")
        both = run("docker", "exec", "-u", "1000:1000", aia, "sh", "-c",
                   "printf ' +accounts' >> /claude/zz-h && cat /claude/zz-a && echo && cat /claude/zz-h")
        assert both.splitlines() == ["from-accounts +hermes", "from-hermes +accounts"], both
        run("docker", "exec", "-u", "1000:1000", aia, "rm", "/claude/zz-a", "/claude/zz-h")
        # Hermes reaches AI Accounts by service name; the plugin and AI Accounts see the same login state.
        health = run("docker", "exec", hermes, "curl", "-sf", "http://wizard-ai-accounts:8795/health")
        accounts = json.loads(run("docker", "exec", hermes, "curl", "-sf", "http://wizard-ai-accounts:8795/api/accounts"))
        assert accounts["accounts"][0]["status"] == "not_connected"
        status = run("docker", "exec", "-u", "hermes", "-e", "HOME=/tmp", hermes, "/opt/hermes/.venv/bin/python", "-c",
                     "import sys, json; sys.path.insert(0, '/opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental');"
                     "from directsdk_setup import setup_status; s = setup_status();"
                     "print(json.dumps({k: s[k] for k in ('available', 'logged_in')}))")
        assert json.loads(status) == {"available": True, "logged_in": False}, status
        # Runtipi uninstall of AI Accounts runs `down --remove-orphans -v --rmi all`: the shared volume survives.
        run(*aia_cmd, "down", "--remove-orphans", "-v", env=aia_env, timeout=120)
        assert vol in run("docker", "volume", "ls", "-q"), "shared volume removed while Hermes still uses it"
        report["two_apps"] = {"volume_mode": mode, "hermes_uid": hid, "cross_uid_read_write": True,
                              "service_name_health": json.loads(health)["status"], "plugin_setup_status": json.loads(status),
                              "volume_survives_other_app_uninstall": True}
    finally:
        for cmd, env in reversed(projects):
            run(*cmd, "down", "--remove-orphans", "-v", env=env, check=False, timeout=120)
        run("docker", "volume", "rm", "-f", vol, check=False)
        run("docker", "network", "rm", net, check=False)


def main():
    with tempfile.TemporaryDirectory(prefix=TAG + "-", dir=os.environ.get("TMPDIR"), ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        vol = f"{TAG}-provider"
        try:
            hermes_provider(vol)
            (tmp / "plugin").mkdir()
            plugin_tests(tmp / "plugin")
            two_apps(tmp / "apps")
            data_parity(tmp / "data")
        finally:
            run("docker", "volume", "rm", "-f", vol, check=False)
            # Bind dirs were written by the containers' uids: clean them through a container.
            run("docker", "run", "--rm", "-v", f"{tmp}:/t", "--entrypoint", "sh", official_image(), "-c",
                "rm -rf /t/data /t/apps", check=False)
    print(json.dumps(report, indent=1))
    print("PASS: AI Accounts + Hermes Agent Wizard build (logged-out paths; no login, no model call).")


if __name__ == "__main__":
    sys.exit(main())
