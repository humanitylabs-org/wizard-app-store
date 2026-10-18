#!/usr/bin/env python3
"""Summaries for conformance receipts.
  summarize.py phase <dir> <phase>    print one phase's result
  summarize.py final <dir> <canary>   write summary.json, print RESULT PASS|FAIL (exit 1 on FAIL)"""
import glob
import json
import sys

mode, out = sys.argv[1], sys.argv[2]


def load(name):
    with open(f"{out}/{name}.json") as fh:
        return json.load(fh)


if mode == "phase":
    name = sys.argv[3]
    a, b = load(name), load(f"{name}-inspect")
    print(f"  in-agent {a['summary']['passed']}/{a['summary']['total']} failed={a['summary']['failed']}")
    print(f"  inspect  {b['summary']['passed']}/{b['summary']['total']} failed={b['summary']['failed']}")
    sys.exit(0)

canary = sys.argv[3]
phases = {}
for name in ("initial", "restart", "recreate"):
    a, b = load(name), load(f"{name}-inspect")
    phases[name] = {"in_agent": a["summary"], "inspect": b["summary"]}
leak = any(canary in open(p, errors="replace").read() for p in glob.glob(f"{out}/*.json"))
ok = not leak and all(not p["in_agent"]["failed"] and not p["inspect"]["failed"] for p in phases.values())
with open(f"{out}/summary.json", "w") as fh:
    json.dump({"result": "PASS" if ok else "FAIL", "canary_in_receipts": leak, "phases": phases}, fh, indent=1)
print("RESULT", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
