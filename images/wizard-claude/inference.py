"""Isolated subscription inference and router ingress (stdlib only)."""
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import threading
import time

MAX_BODY = 256 * 1024
CODES = {"signed_out", "expired", "limit", "unreachable", "provider_error"}
SLOTS = threading.BoundedSemaphore(2)
TIMEOUT_S = 120


class Fault(Exception):
    def __init__(self, code="provider_error", message="Provider inference failed.", status=502):
        self.code, self.status = code, status
        super().__init__(message)

    def payload(self):
        return {"type": "error", "code": self.code, "message": str(self)}


def admit(headers):
    """Same grants file shape as the router; no owner/browser credentials accepted."""
    refused = {"origin", "tailscale-user-login", "x-forwarded-for", "forwarded", "x-real-ip"}
    if any(k.lower() in refused or k.lower().startswith("cf-") for k in headers):
        raise Fault(message="Inference is box-only.", status=403)
    path = os.environ.get("WIZARD_GRANTS_FILE")
    grants = {"enforce": False, "incoming": []}
    if path:
        try:
            grants = json.loads(Path(path).read_text())
            if type(grants.get("enforce")) is not bool or not isinstance(grants.get("incoming"), list):
                raise ValueError()
            for row in grants["incoming"]:
                if not isinstance(row, dict) or not isinstance(row.get("from"), str) or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"]):
                    raise ValueError()
        except (OSError, ValueError, TypeError, AttributeError):
            raise Fault(message="Grants configuration is unavailable or invalid.", status=503) from None
    token = headers.get("X-Wizard-Grant", "")
    digest = hashlib.sha256(token.encode()).hexdigest()
    for row in grants["incoming"]:
        if token and hmac.compare_digest(digest, row["sha256"]):
            if row["from"] != "wizard-connection-router":
                raise Fault(message="Only the connection router may infer.", status=403)
            return True
    if grants["enforce"]:
        raise Fault(message="Unknown router grant.", status=403)
    logging.getLogger("inference").warning("Unknown router grant (report-only); caller identity is unverified")
    return False


def body(handler):
    if handler.headers.get("Transfer-Encoding") or handler.headers.get("Content-Encoding"):
        raise Fault(message="Encoded request bodies are unsupported.", status=415)
    if handler.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
        raise Fault(message="JSON only.", status=415)
    try:
        n = int(handler.headers.get("Content-Length", "0"))
        if not 0 < n <= MAX_BODY:
            raise ValueError()
    except ValueError:
        raise Fault("limit", "Invalid request size.", 413) from None
    def pairs(rows):
        out = {}
        for k, v in rows:
            if k in out:
                raise ValueError()
            out[k] = v
        return out
    try:
        data = json.loads(handler.rfile.read(n), object_pairs_hook=pairs)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError):
        raise Fault(message="Invalid JSON object.", status=400) from None


def validate(data, models):
    allowed = {"model", "system", "messages", "max_tokens", "stream", "abilities"}
    m = next((m for m in models if m["id"] == data.get("model")), None)
    messages = data.get("messages")
    abilities = data.get("abilities", [])
    if (set(data) - allowed or m is None or not isinstance(data.get("system", ""), str)
            or data.get("stream", True) is not True
            or not isinstance(messages, list) or not 1 <= len(messages) <= 128
            or any(not isinstance(v, dict) or set(v) != {"role", "content"}
                   or v["role"] not in ("user", "assistant") or not isinstance(v["content"], str) for v in messages)
            or not isinstance(abilities, list) or any(not isinstance(a, str) or a not in m["abilities"] for a in abilities)
            or type(data.get("max_tokens", 8192)) is not int or not 1 <= data.get("max_tokens", 8192) <= 32768):
        raise Fault(message="Invalid inference contract or unsupported model/ability.", status=400)
    return data


def start(handler):
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()


def emit(handler, event):
    handler.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
    handler.wfile.flush()


def models():
    try:
        rows = json.loads(Path(os.environ.get("WIZARD_CLAUDE_MODELS_FILE", Path(__file__).with_name("models.json"))).read_text())["models"]
        if not isinstance(rows, list) or not rows:
            raise ValueError()
        seen = set()
        for m in rows:
            if (not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"] or m["id"].startswith("-")
                    or m["id"] in seen or not isinstance(m.get("label"), str) or m.get("tier") not in ("fast", "standard", "frontier")
                    or not isinstance(m.get("abilities"), list) or any(a not in ("text", "streaming", "web_search") for a in m["abilities"])):
                raise ValueError()
            seen.add(m["id"])
        return rows
    except (OSError, ValueError, TypeError, KeyError):
        raise Fault(message="Model configuration is unavailable or invalid.", status=503) from None


def credential(directory):
    # Explicit service env token is useful for isolated deployments; never persisted.
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        return token
    try:
        auth = json.loads((Path(directory) / ".credentials.json").read_text()).get("claudeAiOauth", {})
        if not auth.get("accessToken"):
            raise Fault("signed_out", "Connect Claude first.", 401)
        if auth.get("expiresAt", 0) <= time.time() * 1000:
            raise Fault("expired", "Claude sign-in expired; renew in the connection app.", 401)
        return auth["accessToken"]
    except FileNotFoundError:
        raise Fault("signed_out", "Connect Claude first.", 401) from None
    except (OSError, ValueError, TypeError, AttributeError):
        raise Fault(message="Claude sign-in is unavailable.") from None


def failure(event):
    # Classify privately, never return provider output (it can contain prompt/token data).
    text = json.dumps(event).lower()
    if any(s in text for s in ("rate_limit", "rate limit", "usage limit", "hit your limit", "429")):
        return "limit"
    if any(s in text for s in ("expired", "authentication_error", "invalid oauth", "401")):
        return "expired"
    if any(s in text for s in ("not logged in", "login required", "signed out")):
        return "signed_out"
    if any(s in text for s in ("connection error", "unreachable", "timed out", "econn")):
        return "unreachable"
    return "provider_error"


def kill(child):
    if child and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(data, cli, directory, work):
    """Yield provisional text; done requires the CLI's successful effective-model result."""
    token = credential(directory)
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="infer-", dir=work) as root:
        root = Path(root)
        for folder in (root / "home", root / "config", root / "cwd"):
            folder.mkdir(mode=0o700)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root / "home"),
               "CLAUDE_CONFIG_DIR": str(root / "config"), "TMPDIR": str(root), "LANG": "C.UTF-8",
               "CLAUDE_CODE_OAUTH_TOKEN": token, "DISABLE_AUTOUPDATER": "1",
               "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        web = "web_search" in data.get("abilities", [])
        tools = "WebSearch" if web else ""
        argv = [cli, "-p", "--safe-mode", "--system-prompt", data.get("system", ""), "--no-session-persistence",
                "--tools", tools, "--allowedTools", tools, "--disable-slash-commands", "--setting-sources", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--model", data["model"],
                "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--max-turns", "8" if web else "1"]
        prompt = (data["messages"][0]["content"] if len(data["messages"]) == 1 and data["messages"][0]["role"] == "user"
                  else "Reply to the final user message in this supplied conversation:\n" + json.dumps(data["messages"]))
        child = None
        deadline = time.monotonic() + TIMEOUT_S
        try:
            child = subprocess.Popen(argv, env=env, cwd=root / "cwd", stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            def write():
                try:
                    child.stdin.write(prompt.encode())
                    child.stdin.close()
                except OSError:
                    pass
            writer = threading.Thread(target=write, daemon=True)
            writer.start()
            pending = b""
            total = visible = 0
            texts = []
            result = None
            assistant_models = set()
            while True:
                if time.monotonic() >= deadline:
                    raise Fault("unreachable", "Claude inference timed out.")
                if not select.select([child.stdout], [], [], 2)[0]:
                    yield None  # heartbeat also detects disconnected clients
                    continue
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                total += len(chunk)
                if total > 4 * 1024 * 1024 or len(pending) > 1024 * 1024:
                    raise Fault("limit", "Claude output exceeded its limit.")
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("type") == "assistant":
                        message = event.get("message", {})
                        if message.get("model"):
                            assistant_models.add(message["model"])
                        for block in message.get("content", []):
                            if block.get("type") == "tool_use" and (not web or block.get("name") != "WebSearch"):
                                raise Fault(message="Unexpected tool use.")
                    if event.get("type") == "stream_event":
                        if event.get("event", {}).get("type") == "message_start":
                            texts = []
                        delta = event.get("event", {}).get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta["text"]
                            texts.append(text)
                            visible += len(text.encode())
                            if visible > data.get("max_tokens", 8192):
                                raise Fault("limit", "Visible output exceeded its conservative byte limit.")
                            yield {"type": "delta", "text": text}
                    if event.get("type") == "result":
                        if result is not None:
                            raise Fault(message="Duplicate completion.")
                        result = event
            code = child.wait(timeout=5)
            if pending.strip() or code or not result or result.get("is_error") or result.get("subtype") != "success":
                raise Fault(failure(result), "Claude did not complete inference.")
            used = result.get("modelUsage", {})
            if (set(used) != {data["model"]} or assistant_models - set(used) or result.get("permission_denials")):
                raise Fault(message="Effective model or tool permission differs from the approved request.")
            if "".join(texts) != result.get("result"):
                raise Fault(message="Final text differs from streamed text.")
            effective = next(iter(used))
            usage = result.get("usage")
            if not isinstance(usage, dict) or type(usage.get("output_tokens")) is not int:
                raise Fault(message="Missing provider usage.")
            if usage["output_tokens"] > data.get("max_tokens", 8192):
                raise Fault("limit", "Output token limit exceeded.")
            yield {"type": "done", "model": effective, "usage": usage}
        except (OSError, subprocess.TimeoutExpired):
            raise Fault("unreachable", "Claude process is unavailable.") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise Fault(message="Malformed Claude stream.") from None
        finally:
            kill(child)
            if child:
                child.wait(timeout=5)
                writer.join(timeout=5)
                child.stdin.close()
                child.stdout.close()


def handle(handler, cli, directory, work):
    started = acquired = False
    try:
        admit(handler.headers)
        handler.connection.settimeout(10)
        data = validate(body(handler), models())
        if not SLOTS.acquire(blocking=False):
            raise Fault("limit", "Inference capacity busy.", 429)
        acquired = True
        events = run(data, cli, directory, work)
        try:
            first = next(events)  # credentials/process errors remain HTTP errors
            start(handler)
            started = True
            def send(event):
                if event is None:
                    handler.wfile.write(b": heartbeat\n\n")
                    handler.wfile.flush()
                else:
                    emit(handler, event)
            send(first)
            for event in events:
                send(event)
        finally:
            events.close()
    except Fault as e:
        if started:
            emit(handler, e.payload())
        else:
            handler.json(e.status, e.payload())
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        pass
    finally:
        if acquired:
            SLOTS.release()
