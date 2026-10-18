#!/usr/bin/env python3
"""Outside-in checks of what Docker actually applied to the restricted agent's containers.
Usage: inspect_check.py <compose-project> <ingress host:port> <agent api key>"""
import json
import subprocess
import sys
import urllib.error
import urllib.request

project, ingress, api_key = sys.argv[1:4]
CHECKS = []


def inspect(service):
    ids = subprocess.check_output(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
                                   "--filter", f"label=com.docker.compose.service={service}"], text=True).split()
    return json.loads(subprocess.check_output(["docker", "inspect", *ids], text=True)) if ids else []


def check(cid, desc, ok, evidence):
    CHECKS.append({"id": cid, "check": desc, "pass": bool(ok), "evidence": evidence})


agent = inspect("agent")
check("I0", "exactly one agent container running", len(agent) == 1, len(agent))
a = agent[0] if agent else {"Config": {}, "HostConfig": {}, "Mounts": [], "NetworkSettings": {"Networks": {}}}
hc, cfg = a["HostConfig"], a["Config"]
check("I1", "runs as uid 10000 (not root)", cfg.get("User") == "10000:10000", cfg.get("User"))
check("I2", "not privileged", hc.get("Privileged") is False, hc.get("Privileged"))
check("I3", "all capabilities dropped, none added",
      [c.upper() for c in (hc.get("CapDrop") or [])] in (["ALL"], ["CAP_ALL"]) and not hc.get("CapAdd"),
      {"drop": hc.get("CapDrop"), "add": hc.get("CapAdd")})
check("I4", "no-new-privileges", any("no-new-privileges" in s for s in hc.get("SecurityOpt") or []), hc.get("SecurityOpt"))
check("I5", "read-only root filesystem", hc.get("ReadonlyRootfs") is True, hc.get("ReadonlyRootfs"))
mounts = [{"type": m["Type"], "dest": m["Destination"], "rw": m["RW"], "src": m.get("Name") or m.get("Source")}
          for m in a.get("Mounts", [])]
# The home may be a named volume or (driver choice on the VPS) one dedicated host directory.
allowed = {("volume", "/opt/data", True), ("bind", "/opt/data", True), ("volume", "/opt/wizard-skills", False)}
check("I6", "only the home (rw) and system-skills volume (ro) are mounted",
      all((m["type"], m["dest"], m["rw"]) in allowed for m in mounts), mounts)
check("I7", "no socket mounted and no host path other than the agent's own home",
      not any("sock" in str(m["src"]) or (m["type"] == "bind" and m["dest"] != "/opt/data") for m in mounts), mounts)
check("I8", "no published ports on the agent", not (hc.get("PortBindings") or {}), hc.get("PortBindings"))
nets = list((a.get("NetworkSettings") or {}).get("Networks", {}))
check("I9", "attached only to the sandbox network", len(nets) == 1 and nets[0].endswith("_sandbox"), nets)
if nets:
    n = json.loads(subprocess.check_output(["docker", "network", "inspect", nets[0]], text=True))[0]
    check("I10", "sandbox network is internal (no route out)", n.get("Internal") is True, n.get("Internal"))
check("I11", "host namespaces not shared",
      all((hc.get(k) or "") in ("", "private", "default") for k in ("PidMode", "IpcMode", "UTSMode", "UsernsMode"))
      and hc.get("NetworkMode", "").endswith("_sandbox"),
      {k: hc.get(k) for k in ("PidMode", "IpcMode", "UTSMode", "UsernsMode", "NetworkMode")})
check("I12", "memory, CPU and process limits set",
      hc.get("Memory", 0) > 0 and hc.get("NanoCpus", 0) > 0 and (hc.get("PidsLimit") or 0) > 0,
      {"memory": hc.get("Memory"), "nano_cpus": hc.get("NanoCpus"), "pids": hc.get("PidsLimit")})
check("I13", "no devices passed through", not hc.get("Devices"), hc.get("Devices"))
env_names = sorted(e.split("=", 1)[0] for e in cfg.get("Env") or [])
check("I14", "no provider/control-plane secrets in the agent's environment",
      not any(k for k in env_names if any(s in k for s in ("ANTHROPIC", "OPENAI", "SECRET", "PASSWORD", "OWNER", "DOCKER_HOST"))
              or (k.endswith(("_KEY", "_TOKEN")) and k != "API_SERVER_KEY")),
      env_names)

for svc in ("egress", "edge"):
    s = inspect(svc)
    shc = s[0]["HostConfig"] if s else {}
    check(f"I15-{svc}", f"{svc} sidecar: non-root, caps dropped, read-only, no-new-privileges",
          bool(s) and s[0]["Config"].get("User") == "65534:65534" and shc.get("ReadonlyRootfs") is True
          and (shc.get("CapDrop") or []) and not shc.get("CapAdd")
          and any("no-new-privileges" in x for x in shc.get("SecurityOpt") or []),
          {"user": s[0]["Config"].get("User") if s else None, "ro": shc.get("ReadonlyRootfs"), "drop": shc.get("CapDrop")})

# The service side can still reach the agent's API (through the edge relay) and the key is enforced.
def get(key):
    req = urllib.request.Request(f"http://{ingress}/v1/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return repr(e)

with_key, without_key = get(api_key), get(None)
check("I16", "service reaches agent API with key (200) and is refused without it (401)",
      with_key == 200 and without_key == 401, {"with_key": with_key, "without_key": without_key})

print(json.dumps({"summary": {"total": len(CHECKS), "passed": sum(c["pass"] for c in CHECKS),
                              "failed": [c["id"] for c in CHECKS if not c["pass"]]}, "checks": CHECKS}, indent=1))
