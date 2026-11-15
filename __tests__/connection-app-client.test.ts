import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";

// Under the browser boundary (wizard-os#133) a Wizard window is sandboxed: the page's own fetch goes out with
// Origin null and the browser hides the answer, and sessionStorage throws. The shared app client
// (/wizard-os-home/core/app-client.js) routes the page's calls and storage through the shell, so each
// connection page loads it first, before any of its own scripts. A same-origin window behaves as before.
for (const path of [
  "images/wizard-claude/pool-static/index.html",
  "images/wizard-chatgpt/pool-static/index.html",
  "images/wizard-claude/static/index.html",
  "images/wizard-chatgpt/static/index.html",
  "images/wizard-tinfoil/web/index.html",
]) {
  test(`${path}: loads the shared app client before its own scripts`, () => {
    const head = readFileSync(path, "utf8").split("</head>")[0]!;
    const scripts = [...head.matchAll(/<script src="([^"]+)"([^>]*)><\/script>/g)];
    const client = scripts.findIndex(m => m[1] === "/wizard-os-home/core/app-client.js");
    expect(client).toBe(0);
    expect(scripts[0]![2]).toBe("");
    expect(scripts.filter(m => m[1] === "/wizard-os-home/core/app-client.js")).toHaveLength(1);
  });
}
