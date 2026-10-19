import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

// ChatGPT (wizard-chatgpt): the per-provider AI connection app (decision #61). Its recipe lives in
// Release fork: humanitylabs-org/chatgpt-connection; this store keeps only the image source and CI.
const dir = "images/wizard-chatgpt";
const workflow = parse(readFileSync(".github/workflows/chatgpt.yml", "utf8"));

test("never holds a ChatGPT token: drives the agent's own sign-in through its dashboard only", () => {
  const server = readFileSync(`${dir}/server.py`, "utf8");
  // Codex refresh tokens are single-use: no auth.json, no token fields, no token endpoint, no usage call.
  expect(server).not.toMatch(/auth\.json|access_token|refresh_token|id_token|oauth\/token|wham|backend-api/);
  expect(server).toContain('CONTRACT = "wizard.ai-connection/2"');
  expect(server).toContain('"usage": None');
  expect(server).toContain('PROXY_HEADERS = ("tailscale-user-login", "x-forwarded-for", "forwarded", "x-real-ip")');
  expect(server).toMatch(/STATIC = \{"\/": \("index.html"/);
  const dockerfile = readFileSync(`${dir}/Dockerfile`, "utf8");
  expect(dockerfile).toContain("USER 1000:1000");
  expect(dockerfile).toMatch(/FROM python:3\.12-alpine@sha256:[0-9a-f]{64}/);
});

test("every file the Dockerfile copies is allowed by .dockerignore", () => {
  const ignore = readFileSync(`${dir}/.dockerignore`, "utf8");
  for (const f of ["inference.py", "server.py", "SKILL.md", "LICENSE", "static/"]) expect(ignore).toContain(`!${f}`);
});

test("workflow tests before it publishes, then checks the published image", () => {
  const steps = workflow.jobs.chatgpt.steps.map((s: { name?: string; run?: string; uses?: string }) => s.name ?? s.run ?? s.uses);
  const inference = workflow.jobs.chatgpt.steps.findIndex((s: { run?: string }) => s.run?.includes("test-inference.py"));
  expect(inference).toBeGreaterThan(-1);
  const publish = steps.findIndex((s: string) => s.startsWith("Publish"));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Build and test ChatGPT")));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Device-code flow")));
  const text = readFileSync(".github/workflows/chatgpt.yml", "utf8");
  expect(text).toContain("linux/amd64,linux/arm64");
  const version = readFileSync(`${dir}/server.py`, "utf8").match(/^VERSION = "([^"]+)"$/m)![1];
  expect(text).toContain(`wizard-chatgpt:${version}`);
});
