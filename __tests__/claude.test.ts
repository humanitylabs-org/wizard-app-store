import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

// Claude (wizard-claude): the per-provider AI connection app (decision #61). Its recipe lives in
// Release fork: humanitylabs-org/claude-connection; this store keeps only the image source and CI.
const dir = "images/wizard-claude";
const workflow = parse(readFileSync(".github/workflows/claude.yml", "utf8"));

test("pins the same official Claude Code as AI Accounts and Hermes Agent", () => {
  const fetcher = readFileSync(`${dir}/fetch-claude-code.py`, "utf8");
  expect(readFileSync("images/hermes-agent/fetch-claude-code.py", "utf8")).toBe(fetcher);
  const version = fetcher.match(/^VERSION = "([^"]+)"$/m)![1];
  const dockerfile = readFileSync(`${dir}/Dockerfile`, "utf8");
  expect(dockerfile).toContain(`CLAUDE_CODE_VERSION=${version}`);
  expect(dockerfile).toContain("DISABLE_AUTOUPDATER=1");
  // The shared login volume is created 1000:1000 0700 by whichever app starts first.
  expect(dockerfile).toContain("chown 1000:1000 /claude && chmod 0700 /claude");
  expect(dockerfile).toContain("USER 1000:1000");
});

test("only usage.py touches the credential file, and nothing refreshes the token", () => {
  const server = readFileSync(`${dir}/server.py`, "utf8");
  expect(server).not.toContain(".credentials.json");
  expect(server).not.toMatch(/accessToken|refreshToken|setup-token/);
  const usage = readFileSync(`${dir}/usage.py`, "utf8");
  expect(usage).not.toMatch(/refreshToken|grant_type|oauth\/token/);
  expect(usage).toContain('"anthropic-beta": "oauth-2025-04-20"');
  expect(usage).toContain('CONTRACT = "wizard.ai-connection/1"');
  expect(server).toMatch(/STATIC = \{"\/": \("index.html"/);
});

test("every file the Dockerfile copies is allowed by .dockerignore", () => {
  const ignore = readFileSync(`${dir}/.dockerignore`, "utf8");
  for (const f of ["inference.py", "models.json", "server.py", "usage.py", "SKILL.md", "LICENSE", "fetch-claude-code.py", "static/"]) expect(ignore).toContain(`!${f}`);
});

test("workflow tests before it publishes, then checks the published image", () => {
  const steps = workflow.jobs.claude.steps.map((s: { name?: string; run?: string; uses?: string }) => s.name ?? s.run ?? s.uses);
  const inference = workflow.jobs.claude.steps.findIndex((s: { run?: string }) => s.run?.includes("test-inference.py"));
  expect(inference).toBeGreaterThan(-1);
  const publish = steps.findIndex((s: string) => s.startsWith("Publish"));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Build and test Claude")));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Usage normalization")));
  const text = readFileSync(".github/workflows/claude.yml", "utf8");
  expect(text).toMatch(/ghcr\.io\/humanitylabs-org\/wizard-claude:\d+\.\d+\.\d+/);
  expect(text).toContain("linux/amd64,linux/arm64");
  const version = readFileSync(`${dir}/server.py`, "utf8").match(/^VERSION = "([^"]+)"$/m)![1];
  expect(text).toContain(`wizard-claude:${version}`);
});
