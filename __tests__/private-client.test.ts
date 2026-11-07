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

test("published private-client examples pin the independently verified image digest", () => {
  const release = JSON.parse(read("release.json"));
  expect(release.image).toMatch(/^ghcr\.io\/humanitylabs-org\/wizard-private-client@sha256:[0-9a-f]{64}$/);
  expect(release.source_sha).toMatch(/^[0-9a-f]{40}$/);
  expect(release.platforms).toEqual(["linux/amd64", "linux/arm64"]);
  expect(read("README.md")).toContain(`    image: ${release.image}`);
  expect(readFileSync("images/CONNECTION_RELEASE.md", "utf8")).toContain(release.image);
  expect(release.backend_pin_target).toBe("ops/agent-runtime/private_providers.py:CLIENT_IMAGE");
});

test("private client workflow gates exact-head publication and separates anonymous readback", () => {
  const quality = workflow.jobs["private-client"];
  expect(quality.steps.some((s: { run?: string }) => s.run?.includes("python3 tests/run.py"))).toBe(true);
  const publish = workflow.jobs.publish;
  expect(publish.needs).toBe("private-client");
  expect(publish.permissions.packages).toBe("write");
  expect(publish.if).toContain("github.repository == 'humanitylabs-org/wizard-app-store'");
  expect(publish.if).toContain("github.event_name == 'push' && github.ref == 'refs/heads/main'");
  expect(publish.if).toContain("github.event_name == 'workflow_dispatch'");
  expect(publish.if).toContain("inputs.expected_sha == github.sha");
  expect(publish.if).toContain("inputs.confirm_version == inputs.version");
  expect(publish.if).not.toContain("pull_request");
  const build = publish.steps.find((s: { uses?: string }) => s.uses?.startsWith("docker/build-push-action@"));
  expect(build.with.platforms).toBe("linux/amd64,linux/arm64");
  expect(build.with.tags).toContain("sha-${{ github.sha }}");
  expect(build.with.tags).toContain("github.event_name == 'workflow_dispatch'");
  expect(build.with.labels).toContain("org.opencontainers.image.revision=${{ github.sha }}");
  const verify = workflow.jobs["verify-public"];
  expect(verify.needs).toBe("publish");
  expect(verify.permissions.packages).toBeUndefined();
  expect(verify.env.DIGEST).toBe("${{ needs.publish.outputs.digest }}");
  expect(verify.steps.some((s: { run?: string }) => s.run?.includes("verify_release.py"))).toBe(true);
  expect(verify.steps.some((s: { uses?: string }) => s.uses?.includes("docker/login"))).toBe(false);
  const readOnly = parse(readFileSync(".github/workflows/private-client-verify.yml", "utf8"));
  expect(readOnly.permissions).toEqual({ contents: "read" });
  expect(readOnly.jobs["anonymous-pulls"].steps.some((s: { uses?: string }) => s.uses?.includes("docker/login"))).toBe(false);
  expect(workflowText).not.toContain("--live");
});
