#!/usr/bin/env python3
"""Copy sidecars/wizard-apps/sync.py into the Hermes Agent recipe's wizard-apps service.

The sidecar runs the unmodified official Hermes image with `python3 -c <script>`, so the script
must live inside docker-compose.yml. sync.py is the reviewable source; run this after editing it
(`--check` fails when the recipe is stale; the store tests enforce the same).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sidecars/wizard-apps/sync.py"
RECIPE = ROOT / "apps/hermes-agent/docker-compose.yml"
BEGIN = "    command:\n      - |\n"
END = "    user: \"1000:1000\"\n"

script = SOURCE.read_text(encoding="utf-8")
if "$" in script or "\t" in script:
    sys.exit("sync.py must not contain '$' (Compose interpolation) or tabs")
block = "".join(("        " + line if line.strip() else "\n") if line.endswith("\n") else "        " + line + "\n"
                for line in script.splitlines(keepends=True))
recipe = RECIPE.read_text(encoding="utf-8")
head, sep, rest = recipe.partition("  wizard-apps:\n")
start = rest.index(BEGIN) + len(BEGIN)
end = rest.index(END, start)
updated = head + sep + rest[:start] + block + rest[end:]
if "--check" in sys.argv:
    sys.exit(0 if updated == recipe else "apps/hermes-agent/docker-compose.yml is stale: run scripts/embed-wizard-apps-sync.py")
RECIPE.write_text(updated, encoding="utf-8")
print("embedded", len(script.splitlines()), "lines")
