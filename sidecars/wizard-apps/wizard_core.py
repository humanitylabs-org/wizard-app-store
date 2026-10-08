"""Wizard apps discovery core: agent-agnostic and deterministic (contract: README.md, "Core").

Inputs: the Wizard App Store app list (fetched from GitHub about hourly, cached, with a built-in
fallback) and TCP/MCP probes on the Runtipi network. Output: <state_dir>/apps.json, the reachable
Wizard apps sorted by id, written only when its bytes change. No clocks, randomness or LLM in the
output: the same store list and probe results always give byte-identical apps.json.
"""
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CORE_VERSION = 1
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
PATH_RE = re.compile(r"/[A-Za-z0-9._~/-]{0,200}")
STORE_TYPES = ("service", "external")

# Used only when the store has never been reachable from this server.
BUILTIN_APPS = [
    {"id": "browser", "name": "Browser", "port": 9222, "short_desc": "Service: Shared headless Chromium."},
    {"id": "defleur-video", "name": "DeFleur Video (Testing)", "port": 8787, "mcp_path": "/mcp",
     "short_desc": "Service: Edit talking-head videos into vertical shorts."},
    {"id": "secret-drop", "name": "Secret Drop", "port": 8792, "short_desc": "Service: One-time encrypted secret handoff."},
    {"id": "transcriber", "name": "Transcriber", "port": 8000, "short_desc": "Service: Local speech-to-text."},
]

_said: dict = {}


def say(key, msg):
    """Log a line only when it changes, so logs stay tiny."""
    if _said.get(key) != msg:
        _said[key] = msg
        print("[wizard-apps] " + msg, flush=True)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_if_changed(path, text):
    """Atomically replace *path* with *text* unless it already holds exactly that. True if written."""
    path = Path(path)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return True


def parse_app(cfg, compose):
    """A store app's config.json + docker-compose.yml -> {id, name, short_desc, port[, mcp_path]} or None."""
    if not isinstance(cfg, dict) or not isinstance(compose, dict):
        return None
    aid, mcp_path = cfg.get("id"), cfg.get("wizard_mcp_path")
    if not isinstance(aid, str) or not ID_RE.fullmatch(aid) or cfg.get("wizard_type") not in STORE_TYPES:
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


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"wizard-apps-core/{CORE_VERSION}"})
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.read(1 << 20)


def fetch_store(repo, ref, get=http_get):
    """Every usable app in the public store at repo@ref (GitHub contents API + raw files)."""
    import yaml
    listing = json.loads(get(f"https://api.github.com/repos/{repo}/contents/apps?ref={urllib.parse.quote(ref)}"))
    apps = []
    for entry in listing:
        name = entry.get("name", "")
        if entry.get("type") != "dir" or not ID_RE.fullmatch(name):
            continue
        raw = f"https://raw.githubusercontent.com/{repo}/{ref}/apps/{name}/"
        try:
            app = parse_app(json.loads(get(raw + "config.json")), yaml.safe_load(get(raw + "docker-compose.yml")))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if app:
            apps.append(app)
    if not apps:
        raise ValueError("store listed no usable apps")
    return apps


def load_store(state_dir, repo, ref, now, refresh_s=3600, fetch=fetch_store):
    """Store app list: cached in <state_dir>/store.json, refetched after refresh_s, built-in when never fetched."""
    cache_path = Path(state_dir) / "store.json"
    cache = read_json(cache_path, {})
    if not isinstance(cache, dict):
        cache = {}
    stale = "fetched_at" not in cache or now - cache["fetched_at"] > refresh_s
    due = stale and now >= cache.get("retry_at", 0)
    if due:
        try:
            cache = {"fetched_at": now, "source": f"{repo}@{ref}", "apps": fetch(repo, ref)}
            say("store", f"store list from {repo}@{ref}: {len(cache['apps'])} apps")
        except Exception as exc:  # offline or GitHub unavailable: keep working, retry in 10 min
            cache["retry_at"] = now + 600
            say("store", f"store fetch failed ({type(exc).__name__}); using the {'cached' if cache.get('apps') else 'built-in'} list")
        write_if_changed(cache_path, json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return cache.get("apps") or BUILTIN_APPS


def tcp_probe(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close()
        return True
    except OSError:
        return False


def mcp_probe(url):
    """(ready, note): does *url* answer an MCP initialize? The probe session is closed again."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "wizard-apps-core", "version": str(CORE_VERSION)}}}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=15) as res:
            session = res.headers.get("Mcp-Session-Id")
            text = res.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, "needs a token" if exc.code in (401, 403) else f"HTTP {exc.code}"
    except OSError as exc:
        return False, type(exc).__name__
    if session:
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="DELETE", headers={"Mcp-Session-Id": session}),
                                   timeout=5).close()
        except OSError:
            pass
    ok = '"serverInfo"' in text or '"protocolVersion"' in text
    return ok, "" if ok else "not an MCP endpoint"


def discover(store_apps, tcp=tcp_probe, mcp=mcp_probe):
    """Reachable apps, sorted by id, one entry per id (first wins). Deterministic given the probe results."""
    seen, out = set(), []
    for app in sorted(store_apps, key=lambda a: str(a.get("id"))):
        aid = app.get("id")
        if aid in seen or not isinstance(aid, str) or not ID_RE.fullmatch(aid):
            continue
        seen.add(aid)
        if not tcp(aid, app["port"]):
            continue
        url = f"http://{aid}:{app['port']}"
        entry = {"id": aid, "name": app.get("name") or aid, "description": app.get("short_desc", ""),
                 "type": "http", "url": url, "mcp_url": None, "mcp_ready": False, "note": ""}
        if app.get("mcp_path"):
            entry["type"] = "mcp"
            entry["mcp_url"] = url + app["mcp_path"]
            entry["mcp_ready"], entry["note"] = mcp(entry["mcp_url"])
        out.append(entry)
    return out


def render(apps):
    return json.dumps({"version": CORE_VERSION, "apps": apps}, indent=2, sort_keys=True) + "\n"


def refresh(state_dir, repo, ref, now, refresh_s=3600, fetch=fetch_store, tcp=tcp_probe, mcp=mcp_probe):
    """One discovery cycle: load the store list, probe, write <state_dir>/apps.json if changed.
    Returns (apps, changed)."""
    apps = discover(load_store(state_dir, repo, ref, now, refresh_s, fetch), tcp, mcp)
    changed = write_if_changed(Path(state_dir) / "apps.json", render(apps))
    say("found", "Wizard apps found: " + ", ".join(a["id"] for a in apps) if apps else "no Wizard apps found")
    return apps, changed
