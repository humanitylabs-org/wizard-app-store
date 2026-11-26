"""One-year Claude sign-in (humanitylabs-org/claude-connection#27; switch `one-year-signin`, off by default).

Claude Code's `setup-token` signs a Claude subscription in for one year instead of the about four weeks of
`claude auth login`. It uses the same browser sign-in and paste-the-code step, but it only prints the new credential
on its own screen. This module is the one place that sees it: it reads it from that screen and writes it into the
shared login folder's `.credentials.json` in the shape Claude Code itself uses, so every reader that already uses that
folder (this app's Claude Code, the agent's Claude Code, Hermes' Claude Code source) picks it up and no second login
or env file appears. The value is never returned, logged or kept anywhere else; server.py only gets ok/until.

Checked with the pinned Claude Code (2.1.296): its sign-in link asks only for `user:inference`; a file holding that
credential with a one-year `expiresAt` reads as a claude.ai login (`claude auth status`), is not rewritten, and
`claude auth logout` removes it. Usage and profile reads need `user:profile`, so usage.py does not ask for them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

ARGV = ["setup-token"]
YEAR_S = 365 * 86400  # what setup-token asks Anthropic for (31536000 s)
SCOPES = ["user:inference"]
CREDENTIAL = re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_-]{20,400}")
_FORWARD = re.compile(r"\x1b\[(\d*)C")  # cursor-forward: the full-screen UI writes spaces this way
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")
FAILED = re.compile(r"OAuth error|Press Enter to retry|Failed to exchange|[Ee]rror:", re.I)


def screen(raw: str) -> str:
    text = _FORWARD.sub(lambda m: " " * min(int(m.group(1) or 1), 200), raw)
    return _ANSI.sub("", text).replace("\r", "\n")


def ready(raw: str) -> bool:
    """The paste-the-code prompt is on screen (the full-screen UI may print it without spaces)."""
    return "pastecode" in re.sub(r"\s", "", screen(raw)).lower()


def scratch_env(env: dict, work: Path) -> dict:
    """The CLI runs on an empty scratch folder: the shared login is only replaced once the new one exists."""
    folder = Path(work) / "one-year-login"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, mode=0o700)
    return {**env, "CLAUDE_CONFIG_DIR": str(folder)}


def cleanup(work: Path) -> None:
    shutil.rmtree(Path(work) / "one-year-login", ignore_errors=True)


def save(claude_dir: str, credential: str, now: float | None = None) -> float:
    """Write the one-year sign-in into `<claude_dir>/.credentials.json` (0600, atomic). The plan label of the sign-in
    it replaces is kept, since this credential can't read the plan. Returns the end date (epoch seconds)."""
    now = time.time() if now is None else now
    path = Path(claude_dir) / ".credentials.json"
    try:
        old = json.loads(path.read_bytes()[: 1 << 20])
    except (OSError, ValueError):
        old = {}
    old = old if isinstance(old, dict) else {}
    prev = old.get("claudeAiOauth")
    prev = prev if isinstance(prev, dict) else {}
    ends = now + YEAR_S
    oauth = {"accessToken": credential, "refreshToken": None, "expiresAt": int(ends * 1000), "scopes": list(SCOPES),
             "wizardSignin": "one-year"}  # usage.ONE_YEAR_MARK: how the app tells it from a four-week sign-in
    for key in ("subscriptionType", "rateLimitTier"):
        if prev.get(key):
            oauth[key] = prev[key]
    data = json.dumps({**old, "claudeAiOauth": oauth}).encode()
    tmp = path.with_name(".credentials.json.%d.tmp" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return ends


def until_text(ends: float) -> str:
    return datetime.fromtimestamp(ends, timezone.utc).strftime("%-d %b %Y")


def outcome(raw: str, claude_dir: str, now: float | None = None) -> dict | None:
    """After the code was sent: None while Claude Code is still working, else {ok, message[, until]}. On success the
    new sign-in is already saved. The credential itself never leaves this function."""
    text = screen(raw)
    found = CREDENTIAL.search(text)
    if found:
        try:
            ends = save(claude_dir, found.group(0), now)
        except OSError:
            return {"ok": False, "message": "Claude signed in, but the app could not save the sign-in. Press Connect again."}
        return {"ok": True, "message": "Signed in for one year, until %s." % until_text(ends),
                "until": datetime.fromtimestamp(ends, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if FAILED.search(text):
        return {"ok": False, "message": "Claude did not accept that code. Start again and paste the newest code."}
    return None
