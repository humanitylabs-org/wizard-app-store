"""Wizard apps sync: the one store-specific addition to the Hermes Agent app.

Runs as a second service next to the unmodified official Hermes image (same image, same uid,
same /opt/data). Every cycle it looks for running Wizard apps on the Runtipi network, connects
apps that serve MCP through the Hermes CLI (`hermes config set|unset mcp_servers.<app-id>`), and
refreshes one lean skill at skills/wizard-apps/SKILL.md. It only ever changes MCP entries it
created itself (recorded in wizard-apps/state.json) and that one skill folder. The app list comes
from the public Wizard App Store (apps with "wizard_mcp_path" in config.json serve MCP), cached in
/opt/data, with a small built-in list for offline use. Design: sidecars/wizard-apps/README.md.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1"
HOME = Path(os.environ.get("HERMES_HOME") or "/opt/data")
CONFIG = HOME / "config.yaml"
STATE_DIR = HOME / "wizard-apps"
STATE = STATE_DIR / "state.json"
STORE_CACHE = STATE_DIR / "store.json"
SKILL = HOME / "skills" / "wizard-apps" / "SKILL.md"
MARKER = "managed-by: wizard-apps-sync"
HERMES = os.environ.get("WIZARD_APPS_HERMES_CLI") or "/opt/hermes/.venv/bin/hermes"
REPO = os.environ.get("WIZARD_APPS_STORE_REPO") or "humanitylabs-org/wizard-app-store"
REF = os.environ.get("WIZARD_APPS_STORE_REF") or "main"
INTERVAL = int(os.environ.get("WIZARD_APPS_INTERVAL_S") or 30)
GRACE = int(os.environ.get("WIZARD_APPS_GRACE_S") or 600)
STORE_EVERY = int(os.environ.get("WIZARD_APPS_STORE_REFRESH_S") or 3600)
ENABLED = (os.environ.get("WIZARD_APPS_SYNC") or "true").strip().lower() not in {"false", "0", "no", "off"}
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
PATH_RE = re.compile(r"/[A-Za-z0-9._~/-]{0,200}")

# Used only when the store has never been reachable from this server.
BUILTIN = [
    {"id": "defleur-video", "name": "DeFleur Video (Testing)", "port": 8787, "mcp_path": "/mcp",
     "short_desc": "Service: Edit talking-head videos into vertical shorts."},
    {"id": "transcriber", "name": "Transcriber", "port": 8000, "short_desc": "Service: Local speech-to-text."},
    {"id": "secret-drop", "name": "Secret Drop", "port": 8792, "short_desc": "Service: One-time encrypted secret handoff."},
    {"id": "browser", "name": "Browser", "port": 9222, "short_desc": "Service: Shared headless Chromium."},
]

# Detailed notes only for apps without MCP tools; MCP apps describe themselves.
NOTES = {
    "transcriber": (
        "OpenAI-compatible speech-to-text with word timings. Base URL `http://transcriber:8000/v1`, any API key "
        "works. List models with `GET /v1/models`, then e.g. `curl -fsS http://transcriber:8000/v1/audio/transcriptions "
        "-F file=@<audio-or-video> -F model=<model-id> -F response_format=verbose_json "
        "-F 'timestamp_granularities[]=word'`."),
    "secret-drop": (
        "Use it whenever you need an API key, token or password from the owner: never ask for secrets in chat. "
        "Fetch `http://secret-drop:8792/SKILL.md` and follow it (it uses `http://secret-drop:8792/client.py`)."),
    "browser": (
        "Shared headless Chromium (Chrome DevTools Protocol). DevTools rejects host names, so resolve the IP first "
        "(`getent hosts browser`) and connect to `http://<ip>:9222` (Puppeteer `browserURL`, Playwright "
        "`connect_over_cdp`). Open your own browser context and disconnect when done; don't close the browser."),
}

_last: dict = {}


def say(key: str, msg: str) -> None:
    """Print only when a message changes, so the log stays tiny."""
    if _last.get(key) != msg:
        _last[key] = msg
        print("[wizard-apps] " + msg, flush=True)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wizard-apps-sync/" + VERSION})
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.read(1 << 20)


def parse_app(cfg, compose):
    """One store app -> {id, name, short_desc, port, mcp_path?}, or None if agents don't use it."""
    if not isinstance(cfg, dict) or not isinstance(compose, dict):
        return None
    aid, mcp_path = cfg.get("id"), cfg.get("wizard_mcp_path")
    if not isinstance(aid, str) or not ID_RE.fullmatch(aid) or cfg.get("wizard_type") not in ("service", "external"):
        return None
    services = compose.get("services") or {}
    svc = services.get(aid) or next((s for s in services.values() if (s.get("x-runtipi") or {}).get("is_main")), None)
    if not isinstance(svc, dict):
        return None
    port = (svc.get("x-runtipi") or {}).get("internal_port")
    if not port and svc.get("ports"):
        port = str(svc["ports"][0]).rsplit(":", 1)[-1].split("/")[0]
    try:
        port = int(str(port))
    except ValueError:
        return None
    app = {"id": aid, "name": str(cfg.get("name") or aid)[:80], "short_desc": str(cfg.get("short_desc") or "")[:160],
           "port": port}
    if isinstance(mcp_path, str) and PATH_RE.fullmatch(mcp_path):
        app["mcp_path"] = mcp_path
    return app


def fetch_store():
    import yaml
    listing = json.loads(http_get(f"https://api.github.com/repos/{REPO}/contents/apps?ref={urllib.parse.quote(REF)}"))
    apps = []
    for entry in listing:
        name = entry.get("name", "")
        if entry.get("type") != "dir" or not ID_RE.fullmatch(name):
            continue
        raw = f"https://raw.githubusercontent.com/{REPO}/{REF}/apps/{name}/"
        try:
            app = parse_app(json.loads(http_get(raw + "config.json")), yaml.safe_load(http_get(raw + "docker-compose.yml")))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if app:
            apps.append(app)
    if not apps:
        raise ValueError("store listed no usable apps")
    return apps


_next_store_try = 0.0


def load_apps():
    global _next_store_try
    cache = read_json(STORE_CACHE, {})
    now = time.time()
    if now >= _next_store_try and now - cache.get("fetched_at", 0) > STORE_EVERY:
        try:
            cache = {"fetched_at": now, "source": f"{REPO}@{REF}", "apps": fetch_store()}
            write_atomic(STORE_CACHE, json.dumps(cache, indent=1))
            say("store", f"store list refreshed from {REPO}@{REF}: {len(cache['apps'])} apps")
        except Exception as exc:  # offline or GitHub unavailable: keep working
            _next_store_try = now + 600
            say("store", f"store fetch failed ({type(exc).__name__}); using the {'cached' if cache.get('apps') else 'built-in'} list")
    return cache.get("apps") or BUILTIN


def reachable(app) -> bool:
    try:
        socket.create_connection((app["id"], app["port"]), timeout=3).close()
        return True
    except OSError:
        return False


def mcp_url(app) -> str:
    return f"http://{app['id']}:{app['port']}{app['mcp_path']}"


def mcp_check(url: str):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "wizard-apps-sync", "version": VERSION}}}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                             "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            text = res.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, "needs a token (set one up with hermes mcp add)" if exc.code in (401, 403) else f"HTTP {exc.code}"
    except OSError as exc:
        return False, type(exc).__name__
    return ('"serverInfo"' in text or '"protocolVersion"' in text), "not an MCP endpoint"


def mcp_servers():
    import yaml
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    servers = data.get("mcp_servers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


def hermes(*args) -> bool:
    # Hermes' own config lock is per process, so stay clear of a write it may be in the middle of:
    # wait until config.yaml has been quiet for a few seconds, then let the CLI do the atomic write.
    for _ in range(20):
        if time.time() - CONFIG.stat().st_mtime >= 3:
            break
        time.sleep(1)
    env = dict(os.environ, HOME=os.environ.get("HOME") or "/tmp")
    p = subprocess.run([HERMES, *args], capture_output=True, text=True, timeout=180, env=env)
    if p.returncode:
        say("cli", f"hermes {' '.join(args[:2])} failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-200:]}")
    return p.returncode == 0


def ours(entry, url) -> bool:
    """The on-disk entry is still exactly what this sync wrote."""
    return isinstance(entry, dict) and set(entry) <= {"url", "enabled"} and entry.get("url") == url \
        and entry.get("enabled", True) is True


def covered(servers, app) -> str:
    """Name of an owner's entry that already points at this app (same host, or same port and path)."""
    for name, entry in servers.items():
        url = urllib.parse.urlsplit(str((entry or {}).get("url") or "")) if isinstance(entry, dict) else None
        if url and (url.hostname == app["id"] or (url.port == app["port"] and url.path.rstrip("/") == app["mcp_path"].rstrip("/"))):
            return name
    return ""


def sync_mcp(apps, present, state):
    servers = mcp_servers()
    owned = state.setdefault("owned", {})
    now = time.time()
    for app in (a for a in apps if a.get("mcp_path")):
        aid, url = app["id"], mcp_url(app)
        own = owned.get(aid) or {}
        entry = servers.get(aid)
        if own.get("state") == "active":
            if not ours(entry, own.get("url")):
                owned[aid] = {"state": "released"}
                say("own:" + aid, f"{aid}: owner changed or removed this MCP entry; leaving it alone from now on")
            elif aid not in present and now - state["seen"].get(aid, 0) > GRACE:
                if hermes("config", "unset", f"mcp_servers.{aid}"):
                    owned[aid] = {"state": "removed"}
                    say("own:" + aid, f"{aid}: unreachable for {GRACE}s, removed its MCP entry")
            continue
        if own.get("state") == "released" or aid not in present or aid in servers:
            continue
        other = covered(servers, app)
        if other:
            say("own:" + aid, f"{aid}: already connected by the owner as '{other}'")
            continue
        ok, why = mcp_check(url)
        if not ok:
            say("own:" + aid, f"{aid}: MCP check failed at {url}: {why}")
            continue
        if hermes("config", "set", f"mcp_servers.{aid}", json.dumps({"url": url, "enabled": True})) \
                and ours(mcp_servers().get(aid), url):
            owned[aid] = {"state": "active", "url": url}
            say("own:" + aid, f"{aid}: connected MCP server {url} (tools mcp__{aid.replace('-', '_')}__*)")
    return mcp_servers()


def render_skill(apps, present, servers) -> str:
    installed = [a for a in apps if a["id"] in present]
    lines = [
        "---", "name: wizard-apps",
        "description: Use for Wizard apps on this server (video, speech, secrets).",
        f"version: {VERSION}.0.0", "author: Wizard App Store", "license: MIT",
        "metadata:", "  hermes:", "    tags: [wizard-apps, runtipi, mcp]", "---", "",
        "# Wizard apps on this server", "",
        f"<!-- {MARKER}. Rewritten automatically every minute; edits here are overwritten. -->", "",
    ]
    if not installed:
        lines += ["No Wizard apps are running right now. The owner can add one with one click in Runtipi "
                  "(Wizard App Store); it is connected here within about a minute.", ""]
        return "\n".join(lines)
    lines += ["## Installed now", ""]
    tools = []
    for a in installed:
        url = f"http://{a['id']}:{a['port']}"
        if a.get("mcp_path"):
            name = a["id"] if a["id"] in servers else covered(servers, a)
            entry = servers.get(name) if name else None
            if isinstance(entry, dict) and entry.get("enabled", True) is not False:
                tools.append(a)
                lines.append(f"- **{a['name']}**: tools `mcp__{name.replace('-', '_')}__*` are connected.")
            else:
                lines.append(f"- **{a['name']}**: running at `{url}`, but its tools are not connected "
                             f"(the owner turned them off, or it needs a token).")
        else:
            note = NOTES.get(a["id"]) or (a.get("short_desc", "").split(": ", 1)[-1] + f" Internal URL: `{url}`.")
            lines.append(f"- **{a['name']}**: {note}")
    lines.append("")
    if tools:
        lines += ["## Apps with tools", "",
                  "Their MCP tools are already connected. Call the app's `workflow_guide` (or `capabilities`) tool "
                  "first and follow it. If the tools are missing from this chat, they were connected after it "
                  "started: ask the owner to start a new chat (/new).", ""]
    lines += [
        "## Files", "",
        "- Files the owner sends in chat are saved under `/opt/data/cache/` (for example `cache/videos/` or "
        "`cache/documents/`); the message gives the path. When an app's tool returns an upload URL or curl "
        "command, run it yourself with that local path. Don't ask the owner to upload.",
        "- Links that apps return use internal addresses like `http://<app-id>:<port>/...`, which the owner's "
        "phone or laptop cannot open. Download the file yourself (`curl -fsSo /opt/data/cache/<name> '<url>'`) "
        "and send it as an attachment (`MEDIA:/opt/data/cache/<name>`). If that isn't possible, tell the owner "
        "to replace the host with the server's address (its Tailscale IP) and the app's port shown in Runtipi.",
        "",
        "## More apps", "",
        "The owner adds the next Wizard app with one click in Runtipi (Wizard App Store); it is connected here "
        "within about a minute.", "",
    ]
    return "\n".join(lines)


def write_skill(text: str) -> None:
    if SKILL.exists():
        current = SKILL.read_text(encoding="utf-8", errors="replace")
        if MARKER not in current:
            say("skill", "skills/wizard-apps exists and was not written by this sync; leaving it alone")
            return
        if current == text:
            return
    write_atomic(SKILL, text)
    say("skill", "wizard-apps skill updated")


def disable(state) -> None:
    """WIZARD_APPS_SYNC=false: undo only what this sync made, then idle."""
    servers = mcp_servers() if CONFIG.exists() else {}
    for aid, own in state.get("owned", {}).items():
        if own.get("state") == "active" and ours(servers.get(aid), own.get("url")):
            if hermes("config", "unset", f"mcp_servers.{aid}"):
                own["state"] = "removed"
    if SKILL.exists() and MARKER in SKILL.read_text(encoding="utf-8", errors="replace"):
        SKILL.unlink()
        SKILL.parent.rmdir() if not any(SKILL.parent.iterdir()) else None
    write_atomic(STATE, json.dumps(state, indent=1))
    say("main", "WIZARD_APPS_SYNC is off: removed this sync's own MCP entries and skill; idle")


def cycle(state) -> None:
    if not CONFIG.exists() or not (HOME / "skills").is_dir():
        say("main", "waiting for Hermes to initialise /opt/data")
        return
    if not ENABLED:
        disable(state)
        return
    apps = load_apps()
    present = {a["id"] for a in apps if reachable(a)}
    now = time.time()
    for aid in present:
        state["seen"][aid] = now
    say("found", "Wizard apps found: " + ", ".join(sorted(present)) if present else "no Wizard apps found")
    servers = sync_mcp(apps, present, state)
    write_skill(render_skill(apps, present, servers))
    write_atomic(STATE, json.dumps(state, indent=1))


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    say("main", f"wizard-apps sync {VERSION} started (store {REPO}@{REF}, every {INTERVAL}s, enabled={ENABLED})")
    state = read_json(STATE, {})
    state.setdefault("seen", {})
    state.setdefault("owned", {})
    while True:
        try:
            cycle(state)
            if not ENABLED and CONFIG.exists():
                while True:  # turned off: cleanup is done, stay idle until the setting changes
                    time.sleep(3600)
        except Exception as exc:  # never crash-loop; report once and retry next cycle
            say("error", f"cycle failed: {type(exc).__name__}: {str(exc)[:200]}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
