import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

const workflow = parse(readFileSync(".github/workflows/router.yml", "utf8"));
test("router publishes immutable dual-architecture images only after unit and container gates", () => {
  const steps = workflow.jobs.router.steps;
  const publish = steps.findIndex((s: { uses?: string }) => s.uses?.startsWith("docker/build-push-action"));
  const unit = steps.findIndex((s: { run?: string }) => s.run?.includes("unittest discover"));
  const smoke = steps.findIndex((s: { run?: string }) => s.run === "sh images/wizard-connection-router/test-container.sh");
  expect(unit).toBeGreaterThan(-1);
  expect(smoke).toBeGreaterThan(-1);
  expect(publish).toBeGreaterThan(unit);
  expect(publish).toBeGreaterThan(smoke);
  expect(steps[publish].if).toBe("github.event_name != 'pull_request'");
  expect(steps[publish].with.platforms).toBe("linux/amd64,linux/arm64");
  expect(steps[publish].with.tags).toBe("ghcr.io/humanitylabs-org/wizard-connection-router:0.1.1");
  const dockerfile = readFileSync("images/wizard-connection-router/Dockerfile", "utf8");
  expect(dockerfile).toContain("USER 1000:1000");
  expect(dockerfile).toMatch(/FROM python:3\.12-alpine@sha256:[0-9a-f]{64}/);
  expect(dockerfile).toContain("COPY mcp/");
});
