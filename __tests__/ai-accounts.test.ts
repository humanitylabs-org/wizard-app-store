import { expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { parse } from "yaml";

const id = "wizard-ai-accounts";
const config = JSON.parse(readFileSync(`apps/${id}/config.json`, "utf8"));
const compose = parse(readFileSync(`apps/${id}/docker-compose.yml`, "utf8"));
const service = compose.services[id];
const hermes = parse(readFileSync("apps/hermes-agent/docker-compose.yml", "utf8"));
const workflow = parse(readFileSync(".github/workflows/ai-accounts.yml", "utf8"));

test("private, versioned, own port, optional page password", () => {
  expect(config.available).toBe(true);
  expect(config.exposable).toBe(false);
  expect(config.port).toBe(8795);
  for (const other of readdirSync("apps").filter((d) => d !== id)) {
    expect(JSON.parse(readFileSync(`apps/${other}/config.json`, "utf8")).port).not.toBe(8795);
  }
  expect(service.image).toBe(`ghcr.io/humanitylabs-org/wizard-ai-accounts:${config.version}`);
  expect(service["x-runtipi"]).toEqual({ is_main: true, internal_port: 8795 });
  expect(config.form_fields).toHaveLength(1);
  expect(config.form_fields[0]).toMatchObject({ type: "password", env_variable: "AI_ACCOUNTS_PASSWORD", required: false });
  expect(service.environment.AI_ACCOUNTS_PASSWORD).toBe("${AI_ACCOUNTS_PASSWORD:-}");
});

test("bounded, unprivileged, read-only; only the shared login volume", () => {
  expect(Object.keys(compose.services)).toEqual([id]);
  expect(service.user).toBe("1000:1000");
  expect(service.read_only).toBe(true);
  expect(service.cap_drop).toEqual(["ALL"]);
  expect(service.security_opt).toEqual(["no-new-privileges:true"]);
  for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "ports"]) expect(service[key]).toBeUndefined();
  expect(service.volumes).toEqual(["claude-login:/claude"]);
  expect(JSON.stringify(compose)).not.toContain("/media");
});

test("the login volume is declared identically in both apps, with a fixed name", () => {
  const volume = { "claude-login": { name: "wizard-ai-accounts-claude" } };
  expect(compose.volumes).toEqual(volume);
  expect(hermes.volumes).toEqual(volume);
  expect(hermes.services["hermes-agent"].volumes).toContain("claude-login:/claude");
  // Both sides run as 1000:1000 so Claude Code can refresh the login in place from either app.
  expect(hermes.services["hermes-agent"].environment.HERMES_UID).toBe("1000");
  expect(hermes.services["hermes-agent"].environment.HERMES_GID).toBe("1000");
  expect(config.uid).toBe(1000);
  expect(config.gid).toBe(1000);
});

test("both images pin the same official Claude Code with the same integrity hashes", () => {
  const a = readFileSync(`images/${id}/fetch-claude-code.py`, "utf8");
  expect(readFileSync("images/hermes-agent/fetch-claude-code.py", "utf8")).toBe(a);
  expect(a).toMatch(/^VERSION = "\d+\.\d+\.\d+"$/m);
  const version = a.match(/^VERSION = "([^"]+)"$/m)![1];
  for (const dockerfile of [`images/${id}/Dockerfile`, "images/hermes-agent/Dockerfile"]) {
    const text = readFileSync(dockerfile, "utf8");
    expect(text).toContain(`CLAUDE_CODE_VERSION=${version}`);
    expect(text).toContain("DISABLE_AUTOUPDATER=1");
  }
  const plugin = readFileSync("images/hermes-agent/fetch-directsdk-plugin.py", "utf8");
  expect(plugin).toMatch(/^COMMIT = "[0-9a-f]{40}"$/m);
  expect(plugin).toContain('"LICENSE":');
});

test("the server never reads or serves credential files", () => {
  const server = readFileSync(`images/${id}/server.py`, "utf8");
  expect(server).not.toContain(".credentials.json");
  expect(server).not.toMatch(/accessToken|refreshToken|setup-token/);
  expect(server).not.toContain("send_file");
  // Static routes are an explicit allow-list.
  expect(server).toMatch(/STATIC = \{"\/": \("index.html"/);
});

test("workflow tests before it publishes both images", () => {
  const steps = workflow.jobs["ai-accounts"].steps.map((s: { name?: string; run?: string; uses?: string }) => s.name ?? s.run ?? s.uses);
  const publish = steps.findIndex((s: string) => s.startsWith("Publish"));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.includes("test-container.sh") || s.startsWith("Build and test AI Accounts")));
  const text = readFileSync(".github/workflows/ai-accounts.yml", "utf8");
  expect(text).toContain(`ghcr.io/humanitylabs-org/wizard-ai-accounts:${config.version}`);
  const hermesConfig = JSON.parse(readFileSync("apps/hermes-agent/config.json", "utf8"));
  expect(text).toContain(`ghcr.io/humanitylabs-org/hermes-agent:${hermesConfig.version}`);
});
