#!/usr/bin/env python3
"""Copy sidecars/wizard-apps/{wizard_core,hermes_adapter}.py into the Hermes Agent recipe.

The sidecar runs the unmodified official Hermes image as `python3 -c BOOTSTRAP CORE ADAPTER`:
Runtipi installs only recipe files, so the two modules travel as command arguments (YAML block
scalars). The .py files are the reviewable source; run this after editing them. `--check` fails
when the recipe is stale (the store tests run it).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sidecars/wizard-apps"
RECIPE = ROOT / "apps/hermes-agent/docker-compose.yml"
BOOTSTRAP = (SRC / "bootstrap.py").read_text(encoding="utf-8")
MODULES = [SRC / "wizard_core.py", SRC / "hermes_adapter.py"]
BEGIN = "    command:\n"
END = "    user: \"1000:1000\"\n"


def block(text):
    if "$" in text or "\t" in text:
        sys.exit("embedded sources must not contain '$' (Compose interpolation) or tabs")
    if not text.endswith("\n"):
        text += "\n"
    return "      - |\n" + "".join("        " + line if line.strip() else "\n" for line in text.splitlines(keepends=True))


def expected_command():
    return [BOOTSTRAP] + [m.read_text(encoding="utf-8") for m in MODULES]


recipe = RECIPE.read_text(encoding="utf-8")
head, sep, rest = recipe.partition("  wizard-apps:\n")
start = rest.index(BEGIN) + len(BEGIN)
end = rest.index(END, start)
updated = head + sep + rest[:start] + "".join(block(t) for t in expected_command()) + rest[end:]
if "--check" in sys.argv:
    sys.exit(0 if updated == recipe else "apps/hermes-agent/docker-compose.yml is stale: run scripts/embed-wizard-apps-sync.py")
RECIPE.write_text(updated, encoding="utf-8")
print("embedded", ", ".join(f"{m.name} ({len(m.read_text().splitlines())} lines)" for m in MODULES))
