import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

// Tinfoil (wizard-tinfoil): the per-provider private AI connection app (decision #61). Its recipe lives in
// oscarhenrycollins/wizard-tinfoil; this store keeps only the image source and CI.
const dir = "images/wizard-tinfoil";
const workflow = parse(readFileSync(".github/workflows/tinfoil.yml", "utf8"));

test("the Tinfoil key only ever goes to the official attestation-verifying SDK", () => {
  const provider = readFileSync(`${dir}/app/provider.py`, "utf8");
  expect(provider).toContain("from tinfoil import TinfoilAI");
  expect(provider).not.toMatch(/base_url|api\.openai\.com|inference\.tinfoil\.sh/);
  const server = readFileSync(`${dir}/app/server.py`, "utf8");
  // The agent gets the box-only gateway token, never the upstream key; its default model is never changed.
  expect(server).toContain("'api_key':token");
  expect(server).toContain("'make_default':False");
  expect(readFileSync(`${dir}/requirements.lock`, "utf8")).toMatch(/^tinfoil==0\.14\.0 /m);
});

test("image runs as uid 1000 on a digest-pinned base with hash-locked dependencies", () => {
  const dockerfile = readFileSync(`${dir}/Dockerfile`, "utf8");
  expect(dockerfile).toContain("USER 1000:1000");
  expect(dockerfile).toMatch(/FROM python:3\.12-slim@sha256:[0-9a-f]{64}/);
  expect(dockerfile).toContain("--require-hashes");
  const ignore = readFileSync(`${dir}/.dockerignore`, "utf8");
  for (const f of ["!app/", "!web/", "!openapi.json", "!requirements.lock"]) expect(ignore).toContain(f);
});

test("workflow tests before it publishes, then checks the published image", () => {
  const steps = workflow.jobs.tinfoil.steps.map((s: { name?: string; run?: string; uses?: string }) => s.name ?? s.run ?? s.uses);
  const publish = steps.findIndex((s: string) => s.startsWith("Publish"));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Unit tests inside the image")));
  expect(publish).toBeGreaterThan(steps.findIndex((s: string) => s.startsWith("Read-only")));
  const text = readFileSync(".github/workflows/tinfoil.yml", "utf8");
  expect(text).toContain("linux/amd64,linux/arm64");
  expect(text).toContain("wizard-tinfoil:0.3.5");
});
