import { expect, test } from "bun:test";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { parse } from "yaml";

const config = JSON.parse(readFileSync("apps/defleur-video/config.json", "utf8"));
const compose = parse(readFileSync("apps/defleur-video/docker-compose.yml", "utf8"));

test("publication allowlist excludes recovered vendor, history, evidence and local state", () => {
  const files: string[] = JSON.parse(readFileSync("images/defleur-video/release-files.json", "utf8"));
  expect(new Set(files).size).toBe(files.length);
  for (const file of files) {
    expect(existsSync(file)).toBe(true);
    expect(file).not.toMatch(/(^|\/)(vendor|docs|\.git|node_modules|\.local-data|__pycache__)(\/|$)/);
    expect(file).not.toContain("..");
  }
  for (const root of ["images/defleur-video", "apps/defleur-video"]) {
    for (const entry of readdirSync(root, { recursive: true, withFileTypes: true })) {
      if (!entry.isFile() || entry.parentPath.includes("__pycache__")) continue;
      const file = `${entry.parentPath}/${entry.name}`;
      expect(files).toContain(file);
    }
  }
  expect(files).toContain(".github/workflows/video.yml");
  expect(files).toContain("scripts/smoke-video.py");
  expect(files).toContain("scripts/translate-video-recipe.mjs");
  expect(files).toContain("scripts/e2e-video-mcp.py");
});

test("image bundles James' helpers byte-for-byte with NOTICE, no faster-whisper", () => {
  expect(readFileSync("images/defleur-video/.dockerignore", "utf8").trim().split("\n"))
    .toEqual(["*", "!Dockerfile", "!service.py", "!editing.py", "!client.py", "!workflow.py", "!transcriber.py",
              "!scan_windows.py", "!mcp_server.py", "!NOTICE", "!requirements.lock", "!defleur", "!defleur/**", "defleur/.gitignore"]);
  const dockerfile = readFileSync("images/defleur-video/Dockerfile", "utf8");
  expect(dockerfile).toContain("COPY defleur/ /opt/defleur/");
  expect(dockerfile).toContain("COPY NOTICE /opt/defleur/NOTICE");
  expect(dockerfile).toContain("--require-hashes");
  expect(dockerfile).toContain("test_audio_gate.py");
  expect(dockerfile).toContain("fonts-dejavu-core");
  const lock = readFileSync("images/defleur-video/requirements.lock", "utf8");
  expect(lock).toContain("torch==2.11.0+cpu");
  expect(lock).toContain("stable-ts==");
  expect(lock).not.toMatch(/^faster-whisper==/m);
  const notice = readFileSync("images/defleur-video/NOTICE", "utf8");
  expect(notice).toContain("30768288eb1308b18216a5df5eb4648fbce3e55b");
  expect(notice).toContain("MIT");
  expect(JSON.parse(readFileSync("images/defleur-video/defleur/plugin.json", "utf8")).license).toBe("MIT");
  // Every pinned helper hash in workflow.py must match the bundled bytes.
  const workflowPy = readFileSync("images/defleur-video/workflow.py", "utf8");
  const pins = [...workflowPy.matchAll(/"((?:skills|defaults)\/[^"]+)", "([a-f0-9]{64})"/g)];
  expect(pins.length).toBeGreaterThanOrEqual(12);
  for (const [, rel, hash] of pins) {
    const digest = new Bun.CryptoHasher("sha256").update(readFileSync(`images/defleur-video/defleur/${rel}`)).digest("hex");
    expect(digest).toBe(hash ?? "");
  }
});

test("release workflow tests, runs the two-app e2e, then publishes", () => {
  const workflow = parse(readFileSync(".github/workflows/video.yml", "utf8"));
  const steps = workflow.jobs["video-image"].steps;
  const firstPublish = steps.findIndex((step: {uses?: string; run?: string}) => step.uses === "docker/login-action@v3" || step.run?.includes("docker push"));
  const lastTest = Math.max(...["scripts/smoke-video.py", "scripts/e2e-video-audio.py", "scripts/e2e-video-mcp.py"].map(s => steps.findIndex((step: {run?: string}) => step.run?.includes(s))));
  expect(steps.findIndex((step: {run?: string}) => step.run?.includes("scripts/e2e-video-audio.py"))).toBeGreaterThan(-1);
  expect(firstPublish).toBeGreaterThan(lastTest);
  const commands = steps.map((step: {run?: string}) => step.run || "").join("\n");
  expect(commands).toContain("sh images/defleur-video/test-container.sh");
  expect(commands).toContain("python3 scripts/smoke-video.py");
  expect(commands).toContain(`docker push ghcr.io/humanitylabs-org/defleur-video:${config.version}`);
});

test("video testing release is private, no-GUI, no token form; optional Transcriber settings", () => {
  expect(config.available).toBe(true);
  expect(config.exposable).toBe(false);
  expect(config.no_gui).toBe(true);
  expect(config.form_fields.map((f: {env_variable: string}) => f.env_variable)).toEqual(["TRANSCRIBER_URL", "TRANSCRIBER_MODEL"]);
  for (const field of config.form_fields) expect(field.required).toBe(false);
  expect(config.form_fields[0].default).toBe("http://transcriber:8000");
  expect(config.form_fields[1].default).toBe("Systran/faster-whisper-small");
  const env = compose.services["defleur-video"].environment;
  expect(env.TRANSCRIBER_URL).toBe("${TRANSCRIBER_URL}");
  expect(env.TRANSCRIBER_MODEL).toBe("${TRANSCRIBER_MODEL}");
});

test("video has independent state, no agent volumes, bounded unprivileged service", () => {
  expect(Object.keys(compose.services)).toEqual(["defleur-video"]);
  const service = compose.services["defleur-video"];
  expect(service.volumes).toEqual(["${APP_DATA_DIR}/data:/data"]);
  expect(service.user).toBe("1000:1000");
  expect(service.read_only).toBe(true);
  expect(service.cap_drop).toEqual(["ALL"]);
  expect(service.security_opt).toEqual(["no-new-privileges:true"]);
  expect(service.mem_limit).toBe("1536m");
  expect(service.memswap_limit).toBe(service.mem_limit);
  expect(service.cpus).toBe(2);
  expect(service.pids_limit).toBe(64);
  expect(config.version).toBe("0.4.0-testing");
  expect(service.image).toBe(`ghcr.io/humanitylabs-org/defleur-video:${config.version}`);
  expect(service.environment.VIDEO_API_TOKEN).toBeUndefined();
  for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "depends_on"]) {
    expect(service[key]).toBeUndefined();
  }
});

test("MCP endpoint ships in the image and is exercised before publish", () => {
  expect(readFileSync("images/defleur-video/Dockerfile", "utf8")).toMatch(/COPY [^\n]*mcp_server\.py \/app\//);
  expect(readFileSync("images/defleur-video/requirements.in", "utf8")).toContain("mcp==2.0.0");
  expect(readFileSync("images/defleur-video/requirements.lock", "utf8")).toMatch(/^mcp==2\.0\.0 \\$/m);
  const mcp = readFileSync("images/defleur-video/mcp_server.py", "utf8");
  for (const tool of ["workflow_guide", "capabilities", "create_upload", "start_edit", "apply_cuts", "get_status", "list_projects", "delete_project"])
    expect(mcp).toContain(`def ${tool}(`);
  expect(mcp).not.toMatch(/openai|anthropic|api\.openai/i);
  expect(readFileSync("images/defleur-video/HERMES.md", "utf8")).toContain("hermes mcp add defleur-video --url http://defleur-video:8787/mcp");
});
