import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";

for (const [workflow, context] of [
  ["ai-accounts", "hermes-agent"],
  ["claude", "wizard-claude"],
  ["router", "wizard-connection-router"],
]) {
  test(`${context} publishes the packaging repo and commit together`, () => {
    const text = readFileSync(`.github/workflows/${workflow}.yml`, "utf8");
    const block = text.split(`context: images/${context}\n`)[1]?.split("platforms:")[0];
    expect(block).toContain("org.opencontainers.image.source=https://github.com/${{ github.repository }}");
    expect(block).toContain("org.opencontainers.image.revision=${{ github.sha }}");
  });
}
