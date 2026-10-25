import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";

for (const path of [
  "images/wizard-claude/pool-static/index.html",
  "images/wizard-chatgpt/pool-static/index.html",
  "images/wizard-tinfoil/web/index.html",
]) {
  test(`${path}: one deferred shell identity hook in the head`, () => {
    const head = readFileSync(path, "utf8").split("</head>")[0]!;
    const hooks = head.match(/<script src="\/wizard-os-home\/core\/app-identity\.js" defer><\/script>/g) ?? [];
    expect(hooks).toHaveLength(1);
  });
}
