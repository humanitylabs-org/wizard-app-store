"""Hermes adapter: applies the core's apps.json to Hermes Agent (design: README.md).

It writes MCP entries only through the Hermes CLI (`hermes config set|unset mcp_servers.<app-id>`)
and only for apps the core marks as MCP-ready. It touches only entries it created (recorded in
hermes-state.json) and only while they still match what it wrote. It renders the wizard-apps skill
from a fixed template. Idempotent: with an unchanged apps.json and config.yaml it makes no CLI
call and writes no file.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import wizard_core as core

ADAPTER_VERSION = 1
MARKER = "managed-by: wizard-apps-sync"

# Detailed notes only for apps without MCP tools; MCP apps describe themselves through their tools.
NOTES = {
    "browser": (
        "Shared headless Chromium (Chrome DevTools Protocol). DevTools rejects host names, so resolve the IP first "
        "(`getent hosts browser`) and connect to `http://<ip>:9222` (Puppeteer `browserURL`, Playwright "
        "`connect_over_cdp`). Use your own browser context and disconnect when done; don't close the browser."),
    "secret-drop": (
        "Use it whenever you need an API key, token or password from the owner; never ask for secrets in chat. "
        "Fetch `http://secret-drop:8792/SKILL.md` and follow it (it uses `http://secret-drop:8792/client.py`)."),
    "transcriber": (
        "OpenAI-compatible speech-to-text with word timings. Base URL `http://transcriber:8000/v1`, any API key "
        "works. List models with `GET /v1/models`, then e.g. `curl -fsS http://transcriber:8000/v1/audio/transcriptions "
        "-F file=@<audio-or-video> -F model=<model-id> -F response_format=verbose_json "
        "-F 'timestamp_granularities[]=word'`."),
}


class Hermes:
    """The Hermes side: config.yaml (read), the Hermes CLI (write), the skills folder."""

    def __init__(self, home, cli):
        self.home = Path(home)
        self.config = self.home / "config.yaml"
        self.skill = self.home / "skills" / "wizard-apps" / "SKILL.md"
        self.cli = cli
        self.calls = []

    def ready(self):
        return self.config.exists() and (self.home / "skills").is_dir()

    def servers(self):
        import yaml
        data = yaml.safe_load(self.config.read_text(encoding="utf-8")) or {}
        servers = data.get("mcp_servers") if isinstance(data, dict) else None
        return servers if isinstance(servers, dict) else {}

    def run(self, *args):
        # Hermes' own config lock is per process: let a write in progress settle first, then use its CLI,
        # which writes atomically and keeps comments, key order and every other setting.
        for _ in range(20):
            if time.time() - self.config.stat().st_mtime >= 3:
                break
            time.sleep(1)
        self.calls.append(args)
        env = dict(os.environ, HOME=os.environ.get("HOME") or str(self.home))
        p = subprocess.run([self.cli, *args], capture_output=True, text=True, timeout=180, env=env)
        if p.returncode:
            core.say("cli", f"hermes {' '.join(args[:2])} failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-200:]}")
        return p.returncode == 0


def ours(entry, url):
    """The on-disk entry is still exactly what this adapter wrote."""
    return isinstance(entry, dict) and set(entry) <= {"url", "enabled"} and entry.get("url") == url \
        and entry.get("enabled", True) is True


def covered(servers, app):
    """Name of another entry that already points at this app (same host), sorted for stability."""
    host = urllib.parse.urlsplit(app["mcp_url"]).hostname
    for name in sorted(servers):
        entry = servers[name]
        if name != app["id"] and isinstance(entry, dict) and urllib.parse.urlsplit(str(entry.get("url") or "")).hostname == host:
            return name
    return ""


def tool_prefix(name):
    return "mcp__" + "".join(c if c.isalnum() or c == "_" else "_" for c in name) + "__"


def render_skill(apps, servers):
    """Fixed template; the same apps.json and mcp_servers always give the same text."""
    lines = [
        "---", "name: wizard-apps",
        "description: Use for Wizard apps on this server (video, speech, secrets).",
        f"version: {ADAPTER_VERSION}.0.0", "author: Wizard App Store", "license: MIT",
        "metadata:", "  hermes:", "    tags: [wizard-apps, runtipi, mcp]", "---", "",
        "# Wizard apps on this server", "",
        f"<!-- {MARKER}. Rewritten automatically; edits here are overwritten. -->", "",
    ]
    if not apps:
        return "\n".join(lines + [
            "No Wizard apps are running right now. The owner can add one with one click in Runtipi "
            "(Wizard App Store); it is connected here within about a minute.", ""])
    lines += ["## Installed now", ""]
    with_tools = False
    for app in apps:
        if app["type"] == "mcp":
            name = app["id"] if app["id"] in servers else covered(servers, app)
            entry = servers.get(name) if name else None
            if isinstance(entry, dict) and entry.get("enabled", True) is not False:
                with_tools = True
                lines.append(f"- **{app['name']}**: its tools `{tool_prefix(name)}*` are connected.")
            else:
                lines.append(f"- **{app['name']}**: running at `{app['url']}`, but its tools are not connected yet "
                             "(starting, turned off by the owner, or it needs a token).")
        else:
            note = NOTES.get(app["id"]) or f"{app['description'].split(': ', 1)[-1]} Internal URL: `{app['url']}`."
            lines.append(f"- **{app['name']}**: {note}")
    lines.append("")
    if with_tools:
        lines += ["## Apps with tools", "",
                  "Their tools are already connected. Call the app's `workflow_guide` (or `capabilities`) tool first "
                  "and follow it. If the tools are missing in this chat, they were connected after it started: ask "
                  "the owner to start a new chat (/new).", ""]
    lines += [
        "## Files", "",
        "- Files the owner sends in chat are saved under `/opt/data/cache/` (for example `cache/videos/` or "
        "`cache/documents/`); the message gives the path. When an app returns an upload URL or curl command, run "
        "it yourself with that local path. Don't ask the owner to upload.",
        "- Links that apps return use internal addresses like `http://<app-id>:<port>/...`, which the owner's "
        "phone or laptop cannot open. Download the file yourself (`curl -fsSo /opt/data/cache/<name> '<url>'`) "
        "and send it as an attachment (`MEDIA:/opt/data/cache/<name>`). If that isn't possible, tell the owner to "
        "replace the host with the server's address (its Tailscale IP) and the app's port shown in Runtipi.",
        "",
        "## More apps", "",
        "The owner adds the next Wizard app with one click in Runtipi (Wizard App Store); it is connected here "
        "within about a minute.", "",
    ]
    return "\n".join(lines)


def write_skill(hermes, text):
    if hermes.skill.exists() and MARKER not in hermes.skill.read_text(encoding="utf-8", errors="replace"):
        core.say("skill", "skills/wizard-apps was not written by this sync; leaving it alone")
        return
    if core.write_if_changed(hermes.skill, text):
        core.say("skill", "wizard-apps skill updated")


def apply(apps, hermes, state, now, grace_s=600):
    """Bring Hermes in line with *apps*. Mutates *state*; calls the CLI only when something must change."""
    owned = state.setdefault("owned", {})
    missing = state.setdefault("missing_since", {})
    servers = hermes.servers()
    ready = {a["id"]: a for a in apps if a["type"] == "mcp" and a["mcp_ready"]}
    for aid in sorted(owned):
        own = owned[aid]
        if own.get("state") != "active":
            continue
        if not ours(servers.get(aid), own.get("url")):
            owned[aid] = {"state": "released"}
            missing.pop(aid, None)
            core.say("own:" + aid, f"{aid}: the owner changed or removed this MCP entry; leaving it alone from now on")
        elif aid in ready and ready[aid]["mcp_url"] == own["url"]:
            missing.pop(aid, None)
        else:
            since = missing.setdefault(aid, now)
            if now - since >= grace_s and hermes.run("config", "unset", f"mcp_servers.{aid}"):
                owned[aid] = {"state": "removed"}
                missing.pop(aid, None)
                core.say("own:" + aid, f"{aid}: unreachable for {grace_s}s, removed its MCP entry")
    servers = hermes.servers() if hermes.calls else servers
    for aid, app in sorted(ready.items()):
        if owned.get(aid, {}).get("state") in ("active", "released") or aid in servers:
            continue
        other = covered(servers, app)
        if other:
            core.say("own:" + aid, f"{aid}: already connected by the owner as '{other}'")
            continue
        if hermes.run("config", "set", f"mcp_servers.{aid}", json.dumps({"url": app["mcp_url"], "enabled": True})) \
                and ours(hermes.servers().get(aid), app["mcp_url"]):
            owned[aid] = {"state": "active", "url": app["mcp_url"]}
            core.say("own:" + aid, f"{aid}: connected {app['mcp_url']} (tools {tool_prefix(aid)}*)")
    servers = hermes.servers() if hermes.calls else servers
    write_skill(hermes, render_skill(apps, servers))
    return state


def disable(hermes, state):
    """The owner turned the sync off: undo only what it made."""
    servers = hermes.servers()
    for aid, own in sorted(state.get("owned", {}).items()):
        if own.get("state") == "active" and ours(servers.get(aid), own.get("url")) \
                and hermes.run("config", "unset", f"mcp_servers.{aid}"):
            own["state"] = "removed"
    if hermes.skill.exists() and MARKER in hermes.skill.read_text(encoding="utf-8", errors="replace"):
        hermes.skill.unlink()
        if not any(hermes.skill.parent.iterdir()):
            hermes.skill.parent.rmdir()
    core.say("main", "WIZARD_APPS_SYNC is off: removed this sync's own MCP entries and skill; idle")


def save_state(path, state):
    core.write_if_changed(path, json.dumps(state, indent=1, sort_keys=True) + "\n")


def main():
    env = os.environ.get
    home = Path(env("HERMES_HOME") or "/opt/data")
    state_dir = home / "wizard-apps"
    state_path = state_dir / "hermes-state.json"
    repo = env("WIZARD_APPS_STORE_REPO") or "humanitylabs-org/wizard-app-store"
    ref = env("WIZARD_APPS_STORE_REF") or "main"
    interval = int(env("WIZARD_APPS_INTERVAL_S") or 30)
    grace = int(env("WIZARD_APPS_GRACE_S") or 600)
    enabled = (env("WIZARD_APPS_SYNC") or "true").strip().lower() not in {"false", "0", "no", "off"}
    hermes = Hermes(home, env("WIZARD_APPS_HERMES_CLI") or "/opt/hermes/.venv/bin/hermes")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    core.say("main", f"wizard-apps sync (core {core.CORE_VERSION}, hermes adapter {ADAPTER_VERSION}) started: "
                     f"store {repo}@{ref}, every {interval}s, enabled={enabled}")
    state = core.read_json(state_path, {})
    state = state if isinstance(state, dict) else {}
    while True:
        try:
            if not hermes.ready():
                core.say("main", "waiting for Hermes to initialise /opt/data")
            elif not enabled:
                disable(hermes, state)
                save_state(state_path, state)
                while True:  # cleanup done; idle until the setting changes (container recreate)
                    time.sleep(3600)
            else:
                now = int(time.time())
                apps, _ = core.refresh(state_dir, repo, ref, now)
                hermes.calls = []
                apply(apps, hermes, state, now, grace)
                save_state(state_path, state)
        except Exception as exc:  # never crash-loop; report once and retry next cycle
            core.say("error", f"cycle failed: {type(exc).__name__}: {str(exc)[:200]}")
        time.sleep(interval)
