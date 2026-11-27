#!/usr/bin/env python3
"""Holographic memory works in the Hermes Agent Wizard image with no network (wizard-app-manager#856).

Usage: python3 scripts/check-holographic-memory.py <image>
Runs Hermes' own memory initializer (the one the gateway uses) in a throwaway container with
`--network none`, as an unprivileged user, on a fresh home whose config selects `memory.provider:
holographic` (what every Agent Service agent uses). It must find the provider bundled with the image,
never download it, and store and recall a fact. Hermes v0.22+ moved the provider out of core; without the
built-in copy this fails with "moved out of core and could not be installed automatically".
"""
import json
import subprocess
import sys

PROBE = r'''
import json, os
from pathlib import Path
from types import SimpleNamespace
home = Path(os.environ["HERMES_HOME"]); home.mkdir(parents=True, exist_ok=True)
(home / "config.yaml").write_text("memory:\n  provider: holographic\n")
from hermes_cli.config import load_config
from agent.agent_init import _init_memory
from plugins.memory import find_provider_dir
class Probe(SimpleNamespace):
    def __getattr__(self, name): return None
cfg = load_config()
a = Probe(enabled_toolsets=["memory"], disabled_toolsets=[], tools=[], valid_tool_names=set(), session_id="holo-check",
          session_cwd=str(home))
_init_memory(a, cfg, False, "api_server")
m = a._memory_manager
assert m is not None and m.get_provider("holographic"), "holographic memory did not start"
fact = "The throwaway check prefers teal notebooks."
assert json.loads(m.handle_tool_call("fact_store", {"action": "add", "content": fact})).get("status") == "added"
found = json.loads(m.handle_tool_call("fact_store", {"action": "search", "query": "teal notebooks", "limit": 5}))
assert any(r["content"] == fact for r in found["results"]), found
m.shutdown_all()
where = find_provider_dir("holographic")
assert str(where).startswith("/opt/hermes/plugins/memory/"), where
assert not (home / "plugins" / "holographic").exists(), "the provider was installed into the home"
pinned = where / "PINNED_COMMIT"
print(json.dumps({"provider": "holographic", "dir": str(where), "fact_recalled": True,
                  "pinned": pinned.read_text().strip() if pinned.exists() else "in Hermes core"}))
'''


def main(image: str) -> None:
    out = subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", "1000:1000", "--read-only",
                          "--tmpfs", "/tmp:rw,mode=1777", "-e", "HOME=/tmp/h", "-e", "HERMES_HOME=/tmp/h",
                          "--entrypoint", "/opt/hermes/.venv/bin/python", image, "-c", PROBE],
                         capture_output=True, text=True, timeout=300)
    if out.returncode:
        sys.exit(f"holographic memory check failed on {image}:\n{out.stdout[-2000:]}\n{out.stderr[-4000:]}")
    if "moved out of core" in out.stdout + out.stderr:
        sys.exit(f"Hermes tried to fetch the provider on {image}:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
    print(out.stdout.strip().splitlines()[-1])


if __name__ == "__main__":
    main(sys.argv[1])
