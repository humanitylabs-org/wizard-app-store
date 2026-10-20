import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

const dir = "images/wizard-private-client";
const read = (name: string) => readFileSync(`${dir}/${name}`, "utf8");
const workflowText = readFileSync(".github/workflows/private-client.yml", "utf8");
const workflow = parse(workflowText);

test("private client pins official verifier and EHBP transport without a provider key", () => {
  const pkg = JSON.parse(read("package.json"));
  const lock = JSON.parse(read("package-lock.json"));
  expect(pkg.dependencies).toEqual({ tinfoil: "1.2.2", ehbp: "0.3.3" });
  for (const dep of Object.keys(pkg.dependencies)) {
    expect(lock.packages[`node_modules/${dep}`].version).toBe(pkg.dependencies[dep]);
    expect(lock.packages[`node_modules/${dep}`].integrity).toStartWith("sha512-");
  }
  const source = read("server.mjs");
  expect(source).toContain("from 'tinfoil'");
  expect(source).toContain("from 'ehbp'");
  expect(source).toContain("await verifier.verifyBundle(bundle)");
  expect(source).toContain("doc?.securityVerified");
  expect(source).toContain("Identity.fromPublicKeyHex(key)");
  expect(source).not.toMatch(/TINFOIL_API_KEY|UnverifiedClient|createUnverified|api\.openai\.com|\.well-known\/.*keys/);
});

test("private client image has non-root runtime, digest-pinned base and no mutable SDK install", () => {
  const dockerfile = read("Dockerfile");
  expect(dockerfile).toMatch(/FROM node:22-alpine@sha256:[0-9a-f]{64}/);
  expect(dockerfile).toContain("USER 1000:1000");
  expect(dockerfile).toContain("npm ci --omit=dev --ignore-scripts");
  expect(dockerfile).toContain("EXPOSE 3301");
  expect(read(".dockerignore").split("\n")[0]).toBe("**");
});

test("private client workflow gates multi-arch publication and never publishes PRs", () => {
  const steps = workflow.jobs["private-client"].steps;
  const testIndex = steps.findIndex((s: { run?: string }) => s.run?.includes("python3 tests/run.py"));
  const publishIndex = steps.findIndex((s: { name?: string }) => s.name?.startsWith("Publish"));
  expect(testIndex).toBeGreaterThan(-1);
  expect(publishIndex).toBeGreaterThan(testIndex);
  expect(steps[publishIndex].if).toBe("github.event_name != 'pull_request' && github.ref == 'refs/heads/main'");
  expect(steps[publishIndex].with.platforms).toBe("linux/amd64,linux/arm64");
  expect(steps[publishIndex].with.tags).toBe("ghcr.io/humanitylabs-org/wizard-private-client:0.1.0");
  expect(workflowText).toContain("Verify the published runtime");
  expect(workflowText).not.toContain("--live");
});
