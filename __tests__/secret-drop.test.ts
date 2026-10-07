import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { parse } from "yaml";

const config = JSON.parse(readFileSync("apps/secret-drop/config.json", "utf8"));
const compose = parse(readFileSync("apps/secret-drop/docker-compose.yml", "utf8"));
const service = compose.services["secret-drop"];
const workflow = parse(readFileSync(".github/workflows/secret-drop.yml", "utf8"));

test("private, versioned, optional token, port not used by other store apps", () => {
  expect(config.available).toBe(true);
  expect(config.exposable).toBe(false);
  expect(config.port).toBe(8792);
  for (const id of readdirSync("apps").filter((d) => d !== "secret-drop")) {
    expect(JSON.parse(readFileSync(`apps/${id}/config.json`, "utf8")).port).not.toBe(8792);
  }
  const fields = Object.fromEntries(config.form_fields.map((f: { env_variable: string }) => [f.env_variable, f]));
  expect(fields.SECRET_DROP_API_TOKEN.type).toBe("password");
  expect(fields.SECRET_DROP_API_TOKEN.required).toBe(false);
  expect(fields.SECRET_DROP_PUBLIC_URL.required).toBe(false);
  expect(service.image).toBe(`ghcr.io/humanitylabs-org/secret-drop:${config.version}`);
  expect(service.x_runtipi ?? service["x-runtipi"]).toEqual({ is_main: true, internal_port: 8792 });
});

test("bounded, unprivileged, read-only service with only its own data dir", () => {
  expect(Object.keys(compose.services)).toEqual(["secret-drop"]);
  expect(service.user).toBe("1000:1000");
  expect(service.read_only).toBe(true);
  expect(service.cap_drop).toEqual(["ALL"]);
  expect(service.security_opt).toEqual(["no-new-privileges:true"]);
  expect(service.volumes).toEqual(["${APP_DATA_DIR}/data:/data"]);
  expect(service.mem_limit).toBeDefined();
  expect(service.pids_limit).toBeGreaterThan(0);
  for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "ports"]) {
    expect(service[key]).toBeUndefined();
  }
});

test("image context ships only the relay, client, skill and static page", () => {
  expect(readFileSync("images/secret-drop/.dockerignore", "utf8").trim().split("\n"))
    .toEqual(["*", "!Dockerfile", "!server.py", "!client.py", "!SKILL.md", "!LICENSE", "!static/"]);
  const dockerfile = readFileSync("images/secret-drop/Dockerfile", "utf8");
  expect(dockerfile).toMatch(/^FROM python:3\.12-alpine@sha256:[a-f0-9]{64}$/m);
  expect(dockerfile).toContain("USER 1000:1000");
  expect(dockerfile).not.toMatch(/pip install|apk add|npm /);
});

test("page has no inline script and pins every asset with SRI", () => {
  const html = readFileSync("images/secret-drop/static/index.html", "utf8");
  expect(html).not.toMatch(/<script>(?!<\/script>)/);
  expect(html).not.toMatch(/https?:\/\//);
  for (const name of ["noble-crypto.js", "hpke.js", "app.js", "app.css"]) {
    expect(html).toContain(`integrity="{{sri:${name}}}"`);
  }
  const app = readFileSync("images/secret-drop/static/app.js", "utf8");
  expect(app).not.toMatch(/innerHTML|eval\(|new Function|localStorage|sessionStorage/);
});

test("vendored crypto is exact-pinned and its banner matches the lockfile", () => {
  const pkg = JSON.parse(readFileSync("images/secret-drop/vendor/package.json", "utf8"));
  const lock = JSON.parse(readFileSync("images/secret-drop/vendor/package-lock.json", "utf8"));
  const bundle = readFileSync("images/secret-drop/static/noble-crypto.js", "utf8");
  for (const [name, version] of Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })) {
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
    expect(lock.packages[`node_modules/${name}`].version).toBe(version);
  }
  for (const name of ["@noble/ciphers", "@noble/curves", "@noble/hashes"]) {
    const entry = lock.packages[`node_modules/${name}`];
    expect(entry.license).toBe("MIT");
    expect(bundle).toContain(`${name}@${entry.version} ${entry.integrity}`);
  }
  expect(createHash("sha256").update(bundle).digest("hex")).toMatch(/^[a-f0-9]{64}$/);
});

test("release workflow publishes only after unit, bundle, container and browser smoke", () => {
  const steps = workflow.jobs["secret-drop-image"].steps as { uses?: string; run?: string; with?: Record<string, unknown> }[];
  const commands = steps.map((s) => s.run || "").join("\n");
  const index = (needle: string) => steps.findIndex((s) => (s.run || "").includes(needle));
  const firstPublish = steps.findIndex((s) => s.uses?.startsWith("docker/login-action") || s.uses?.startsWith("docker/build-push-action"));
  for (const needle of ["python -m unittest", "node build.mjs", "test-container.sh", "scripts/smoke-secret-drop.py"]) {
    expect(index(needle)).toBeGreaterThan(-1);
    expect(firstPublish).toBeGreaterThan(index(needle));
  }
  expect(commands).toContain("git diff --exit-code");
  const push = steps.find((s) => s.uses?.startsWith("docker/build-push-action"));
  expect(push?.with?.tags).toBe(`ghcr.io/humanitylabs-org/secret-drop:${config.version}`);
  expect(workflow.on.push.paths).toContain("apps/secret-drop/**");
});
