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
    expect(file).not.toMatch(/(^|\/)(vendor|docs|\.git|node_modules|\.local-data)(\/|$)/);
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
});

test("image context and release workflow contain only the original service", () => {
  expect(readFileSync("images/defleur-video/.dockerignore", "utf8").trim().split("\n"))
    .toEqual(["*", "!Dockerfile", "!service.py", "!editing.py", "!client.py", "!workflow.py"]);
  const dockerfile = readFileSync("images/defleur-video/Dockerfile", "utf8");
  expect(dockerfile).toContain("COPY service.py editing.py client.py workflow.py /app/");
  expect(dockerfile).toContain("fonts-dejavu-core");
  const workflow = parse(readFileSync(".github/workflows/video.yml", "utf8"));
  const steps = workflow.jobs["video-image"].steps;
  const firstPublish = steps.findIndex((step: {uses?: string; run?: string}) => step.uses === "docker/login-action@v3" || step.run?.includes("docker push"));
  const lastTest = steps.findIndex((step: {run?: string}) => step.run?.includes("scripts/smoke-video.py"));
  expect(lastTest).toBeGreaterThan(-1);
  expect(firstPublish).toBeGreaterThan(lastTest);
  const commands = workflow.jobs["video-image"].steps.map((step: {run?: string}) => step.run || "").join("\n");
  expect(commands).toContain("sh images/defleur-video/test-container.sh");
  expect(commands).toContain("python3 scripts/smoke-video.py");
  expect(commands).toContain("docker push ghcr.io/humanitylabs-org/defleur-video:0.2.1-testing");
});

test("video testing release is private, no-GUI and needs no token form", () => {
  expect(config.available).toBe(true);
  expect(config.exposable).toBe(false);
  expect(config.no_gui).toBe(true);
  expect(config.form_fields).toBeUndefined();
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
  expect(config.version).toBe("0.2.1-testing");
  expect(service.image).toBe(`ghcr.io/humanitylabs-org/defleur-video:${config.version}`);
  expect(service.environment.VIDEO_API_TOKEN).toBeUndefined();
  for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "depends_on"]) {
    expect(service[key]).toBeUndefined();
  }
});
