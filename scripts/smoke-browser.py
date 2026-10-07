#!/usr/bin/env python3
"""Disposable Runtipi-translated lifecycle test for the Browser app.

Uses the real pinned Runtipi 4.8.0 compose builder, a fresh app-data dir, the
same post-up permission step Runtipi runs, then connects puppeteer-core (the
exact version DeFleur Video pins) from a separate container on the app network
by the service name `browser`, renders a page, screenshots it, checks the
pixels, restarts (force-recreate) and does it again. Also checks the host port
is loopback-only. Needs Docker/Compose, npm, and internet to pull images.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
APP = "browser"
NODE = "node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392"
PUPPETEER = "puppeteer-core@25.12.0"  # same exact version DeFleur Video pins

CLIENT = r"""
const puppeteer = require('puppeteer-core');
const dns = require('dns').promises;
(async () => {
  // Chrome rejects DevTools HTTP requests whose Host is not an IP or localhost: resolve first.
  const {address} = await dns.lookup(process.argv[2], {family: 4});
  const browser = await puppeteer.connect({browserURL: `http://${address}:${process.argv[3]}`});
  const page = await browser.newPage();
  await page.setViewport({width: 1080, height: 1920, deviceScaleFactor: 1});
  await page.setContent('<html><body style="margin:0;background:#102030"><div id="b" style="position:absolute;left:100px;top:200px;width:400px;height:300px;background:rgb(250,10,10)"></div><svg style="position:absolute;left:600px;top:900px" width="200" height="200"><circle cx="100" cy="100" r="90" fill="rgb(10,240,10)"/></svg></body></html>');
  const a = await page.screenshot({type: 'png'});
  const b = await page.screenshot({type: 'png'});
  const px = await page.evaluate(async (data) => {
    const img = new Image(); img.src = 'data:image/png;base64,' + data; await img.decode();
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0);
    const at = (x, y) => Array.from(g.getImageData(x, y, 1, 1).data.slice(0, 3));
    return {size: [img.width, img.height], red: at(300, 350), green: at(700, 1000), bg: at(50, 50)};
  }, Buffer.from(a).toString('base64'));
  const version = await browser.version();
  await page.close(); await browser.disconnect();
  console.log(JSON.stringify({version, png_bytes: a.length, deterministic: Buffer.compare(Buffer.from(a), Buffer.from(b)) === 0, ...px}));
})().catch(e => { console.error(e.stack || e); process.exit(1); });
"""


def run(*args, timeout=600, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs).stdout.strip()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    name = "browser-smoke-" + secrets.token_hex(4)
    translated = json.loads(run("node", "scripts/translate-video-recipe.mjs", APP, cwd=ROOT))
    compose = translated["compose"]
    service = compose["services"][APP]
    assert service["restart"] == "unless-stopped" and service["read_only"] is True and service["init"] is True
    assert service["ports"] == ["127.0.0.1:${APP_PORT}:9222"], service["ports"]
    assert service["networks"] == {"tipi_main_network": {"gw_priority": 1}}
    report = {"test": "translated recipe + real headless Chromium lifecycle over the app network", "image": service["image"],
              "runtipi_revision": translated["revision"]}
    compose["networks"]["tipi_main_network"] = {"name": name, "external": True}
    port = free_port()
    with tempfile.TemporaryDirectory(prefix=name + "-", dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        app = tmp / "app-data"
        app.mkdir()
        client = tmp / "client"
        client.mkdir()
        (client / "package.json").write_text('{"private": true}')
        run("npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", "--save-exact", PUPPETEER, cwd=client, timeout=300)
        (client / "client.cjs").write_text(CLIENT)
        env = {**os.environ, "APP_DATA_DIR": str(app), "APP_PORT": str(port)}
        recipe = tmp / "compose.json"
        recipe.write_text(json.dumps(compose))
        cmd = ["docker", "compose", "-p", name, "-f", str(recipe)]
        run("docker", "network", "create", name)

        def drive():
            out = run("docker", "run", "--rm", "--network", name, "--user", "1000:1000", "--read-only",
                      "--mount", f"type=bind,source={client},target=/client,readonly", "-w", "/client",
                      NODE, "node", "client.cjs", APP, "9222", timeout=180)
            r = json.loads(out.splitlines()[-1])
            assert r["size"] == [1080, 1920], r
            assert r["red"][0] > 230 and r["red"][1] < 30, r
            assert r["green"][1] > 220 and r["green"][0] < 30, r
            assert r["bg"] == [16, 32, 48], r
            assert r["deterministic"], r
            return r

        def ready(deadline_s=120):
            deadline = time.monotonic() + deadline_s
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as res:
                        return json.loads(res.read())
                except OSError:
                    time.sleep(1)
            print(run(*cmd, "logs", "--no-color", "--tail", "60", env=env), file=sys.stderr)
            raise RuntimeError("Browser did not answer /json/version")

        try:
            started = time.monotonic()
            run(*cmd, "up", "-d", env=env)
            cid = run(*cmd, "ps", "-aq", env=env)
            # Runtipi 4.8.0 runs this as host root right after compose up.
            run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                f"type=bind,source={app},target=/fixture", "--entrypoint", "/bin/chmod",
                service["image"], "-Rf", "a+rwx", "/fixture")
            version = ready()
            report["first_ready_seconds"] = round(time.monotonic() - started, 1)
            report["browser"] = version["Browser"]
            inspect = json.loads(run("docker", "inspect", cid))[0]
            hc = inspect["HostConfig"]
            assert hc["ReadonlyRootfs"] and hc["Init"] and inspect["Config"]["User"] == "1000:1000"
            assert hc["CapDrop"] == ["ALL"] and hc["ShmSize"] == 2 * 1024**3
            binding = hc["PortBindings"]["9222/tcp"]
            assert all(b["HostIp"] == "127.0.0.1" for b in binding), binding
            report["host_binding"] = binding
            report["limits"] = {"memory": hc["Memory"], "pids": hc["PidsLimit"], "shm": hc["ShmSize"]}
            report["first"] = drive()
            run(*cmd, "up", "-d", "--force-recreate", env=env)
            t0 = time.monotonic()
            ready()
            report["recreate_ready_seconds"] = round(time.monotonic() - t0, 1)
            report["after_recreate"] = drive()
            run(*cmd, "restart", env=env)
            ready()
            report["after_restart"] = drive()
            cid = run(*cmd, "ps", "-q", env=env)  # recreate gives a new container id
            stats = run("docker", "stats", "--no-stream", "--format", "{{.MemUsage}} pids={{.PIDs}}", cid)
            report["idle_after_use"] = stats
        finally:
            subprocess.run([*cmd, "down", "--remove-orphans"], env=env, capture_output=True)
            subprocess.run(["docker", "network", "rm", name], capture_output=True)
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", "0:0", "--mount",
                            f"type=bind,source={tmp},target=/fixture", "--entrypoint", "/bin/chmod",
                            service["image"], "-Rf", "a+rwx", "/fixture"], capture_output=True)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
