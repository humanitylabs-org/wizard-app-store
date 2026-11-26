// Generated stock-Runtipi store (humanitylabs-org/wizard-os#822): compile steps and the generator, offline.
import { describe, expect, test } from "bun:test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { parse } from "yaml";
import {
  addStopInit, allowedPublisher, chatsModule, composeRisks, forkOnlyNeeds, loopbackMainPort, rewriteVolumes, stockConfig,
} from "../scripts/stock-store/compile.mjs";
import { buildApp, generate as generateJs, pickApps } from "../scripts/stock-store/generate.mjs";

const generate: (o: Record<string, unknown>) => Promise<any> = generateJs as never;

const C1 = "1".repeat(40);
const C2 = "2".repeat(40);
const HERMES = "e".repeat(40);
const tmp = () => mkdtempSync(path.join(process.env.TMPDIR || tmpdir(), "stock-store-test-"));

function fixtureRepo(dir: string, id: string, extra: { pkg?: string; compose?: string; type?: string } = {}) {
  mkdirSync(path.join(dir, "runtipi", "metadata"), { recursive: true });
  writeFileSync(
    path.join(dir, "wizard.md"),
    `---\nid: ${id}\nname: ${id} app\ntype: ${extra.type ?? "service"}\nsummary: Does ${id} things\ncategory: app\n` +
      `runtime:\n  config: runtipi/config.json\n  compose: runtipi/docker-compose.yml\n${extra.pkg ? `  package: ${extra.pkg}\n` : ""}---\n# ${id}\n\nBody.\n`,
  );
  writeFileSync(
    path.join(dir, "runtipi", "config.json"),
    JSON.stringify({
      $schema: "../../schema/app-info.json", name: `${id} app`, id, available: true, short_desc: "", author: "humanitylabs-org", port: 8899,
      categories: ["utilities"], description: "x", tipi_version: 3, version: "1.0.0", source: "https://github.com/humanitylabs-org/x",
      exposable: true, dynamic_config: true, no_gui: true, form_fields: [], supported_architectures: ["amd64", "arm64"], created_at: 1, updated_at: 2,
    }),
  );
  writeFileSync(
    path.join(dir, "runtipi", "docker-compose.yml"),
    extra.compose ??
      `services:\n  ${id}:\n    image: ghcr.io/humanitylabs-org/${id}:1.0.0\n    command: [python3, -m, server]\n    volumes:\n      - data:/data\n` +
        `    x-runtipi:\n      is_main: true\n      internal_port: 8000\nvolumes:\n  data: {}\nx-runtipi:\n  schema_version: 2\n  overrides: []\n`,
  );
  writeFileSync(path.join(dir, "runtipi", "metadata", "logo.jpg"), Buffer.from("ffd8ffe0", "hex"));
}

describe("compile steps (same as the fork does at install/start)", () => {
  test("named volumes become folders in the app's data dir", () => {
    const out = rewriteVolumes({ services: { a: { volumes: ["data:/data", { type: "volume", source: "cache", target: "/c" }, "./x:/x"] } }, volumes: { data: {}, cache: null } }, "a");
    expect(out.services.a.volumes).toEqual(["${APP_DATA_DIR}/volumes/data:/data", { type: "bind", source: "${APP_DATA_DIR}/volumes/cache", target: "/c" }, "./x:/x"]);
    expect(out.volumes).toBeUndefined();
    expect(() => rewriteVolumes({ services: {}, volumes: { v: { external: true } } }, "a")).toThrow("Nonportable");
    expect(() => rewriteVolumes({ services: {}, volumes: { v: { name: "someone-else" } } }, "a")).toThrow("Fixed volume name");
    // A pre-rule-15 app keeps its own fixed-name volume (wam#289).
    expect(rewriteVolumes({ services: {}, volumes: { v: { name: "wizard-a-config" } } }, "a").volumes).toEqual({ v: { name: "wizard-a-config" } });
  });
  test("Python as PID 1 gets Docker's init; an image's own init is left alone", () => {
    const out = addStopInit({ services: { p: { command: ["python3", "-c", "x"] }, q: { command: "python -m x", init: false }, r: { entrypoint: ["tini"], command: ["python"] }, s: { command: ["node"] } } });
    expect(out.services.p.init).toBe(true);
    expect(out.services.q.init).toBe(false);
    expect(out.services.r.init).toBeUndefined();
    expect(out.services.s.init).toBeUndefined();
  });
  test("main port on loopback only", () => {
    const out = loopbackMainPort({ services: { a: { "x-runtipi": { is_main: true, internal_port: 80 } }, b: { "x-runtipi": { is_main: true, internal_port: 80 }, ports: ["1:1"] } } });
    expect(out.services.a.ports).toEqual(["127.0.0.1:${APP_PORT}:80"]);
    expect(out.services.b.ports).toEqual(["1:1"]);
  });
  test("host-level access is refused", () => {
    expect(composeRisks({ services: { a: { privileged: true, volumes: ["/var/run/docker.sock:/s"], network_mode: "host" } } })).toEqual([
      "a: privileged", "a: network_mode: host", "a: mounts the container runtime socket",
    ]);
    expect(composeRisks({ services: { a: { volumes: ["${APP_DATA_DIR}/data:/data"] } } })).toEqual([]);
  });
  test("source/build packaging is fork-only", () => {
    expect(forkOnlyNeeds({ runtime: { package: "source" } }, "image: x\n  - ${APP_SOURCE_DIR}:/app")).toHaveLength(2);
    expect(forkOnlyNeeds({ runtime: { package: "image" } }, "image: x")).toEqual([]);
  });
  test("first-party publishers only, unless WAM_PUBLISHERS says otherwise", () => {
    expect(allowedPublisher({ repo: "humanitylabs-org/x" })).toBe(true);
    expect(allowedPublisher({ repo: "stranger/x" })).toBe(false);
    expect(allowedPublisher({ repo: "stranger/x" }, "*")).toBe(true);
  });
  test("Wizard type maps to a native Runtipi category; tipi_version only rises", () => {
    const base = { tipi_version: 3, categories: ["x"] };
    expect(stockConfig(base, { id: "a", type: "agent" }, C1, null).categories).toEqual(["ai"]);
    expect(stockConfig(base, { id: "a", type: "external" }, C1, null).wizard_type).toBe("external");
    expect(stockConfig(base, { id: "a", type: "view" }, C1, { commit: C1, tipi_version: 7 }).tipi_version).toBe(7);
    expect(stockConfig(base, { id: "a", type: "view" }, C2, { commit: C1, tipi_version: 7 }).tipi_version).toBe(8);
    expect(stockConfig({ tipi_version: 12 }, { id: "a" }, C2, { commit: C1, tipi_version: 7 }).tipi_version).toBe(12);
  });
  test("Chats module admission matches the fork", () => {
    const m = { id: "a", provides: ["chats"], chats_view: { contract: "wizard.chats-view/1", module: "chats/view.js" } };
    expect(chatsModule(m, C1, () => Buffer.from("export default 1"))?.module).toBe("chats/view.js");
    expect(() => chatsModule(m, C1, () => Buffer.from("fetch('/x')"))).toThrow("banned");
    expect(chatsModule({ id: "a" }, C1, () => Buffer.alloc(0))).toBeNull();
  });
});

describe("generator", () => {
  test("one record per id, first-party, index order wins", () => {
    const r = (repo: string, id: string) => ({ repo, id, install: { git: `https://github.com/${repo}`, commit: C1 } });
    const { apps, dropped } = pickApps([r("oscarhenrycollins/files", "files"), r("humanitylabs-org/files", "files"), r("evil/x", "x"), { id: "BAD" }], "");
    expect(apps.map((a) => a.repo)).toEqual(["oscarhenrycollins/files"]);
    expect(dropped.map((d) => d.reason)).toEqual(["id already published by oscarhenrycollins/files", "publisher is not first-party (wizard-os#138)"]);
  });

  test("writes stock Runtipi folders, leaves fork-only apps out with a reason, pins Hermes to the lock", async () => {
    const root = tmp();
    const repos = path.join(root, "repos");
    for (const id of ["notes", "hermes-agent"]) fixtureRepo(path.join(repos, id), id, { type: id === "hermes-agent" ? "agent" : "service" });
    fixtureRepo(path.join(repos, "router"), "router", { pkg: "source", compose: "services:\n  router:\n    image: node:22\n    volumes:\n      - ${APP_SOURCE_DIR}:/app:ro\n" });
    fixtureRepo(path.join(repos, "root"), "root", { compose: "services:\n  root:\n    image: x\n    privileged: true\n" });
    const index: any[] = [
      { repo: "humanitylabs-org/notes", id: "notes", install: { git: "https://github.com/humanitylabs-org/notes", commit: C1 } },
      { repo: "humanitylabs-org/hermes-agent", id: "hermes-agent", install: { git: "https://github.com/humanitylabs-org/hermes-agent", commit: C2 } },
      { repo: "humanitylabs-org/router", id: "router", install: { git: "https://github.com/humanitylabs-org/router", commit: C1 } },
      { repo: "humanitylabs-org/root", id: "root", install: { git: "https://github.com/humanitylabs-org/root", commit: C1 } },
    ];
    const fetched: string[] = [];
    const out = path.join(root, "out");
    mkdirSync(path.join(out, "apps", "gone"), { recursive: true });
    const report = await generate({
      out,
      index: "https://index.test",
      get: async () => ({ apps: index, next_offset: null }),
      hermesLock: { agent_recipe: { repo: "oscarhenrycollins/hermes-agent", commit: HERMES } },
      fetch: (git: string, commit: string, dest: string) => {
        fetched.push(`${git}@${commit}`);
        cpSync(path.join(repos, git.split("/").pop()!), dest, { recursive: true });
      },
    });
    if (!report.included.length) console.log(report.left_out);
    expect(report.included.map((a: any) => a.id)).toEqual(["notes", "hermes-agent"]);
    expect(fetched).toContain(`https://github.com/oscarhenrycollins/hermes-agent@${HERMES}`);
    expect(report.hermes_pin.commit).toBe(HERMES);
    expect(readFileSync(path.join(out, "apps", "hermes-agent", ".wizard-commit"), "utf8").trim()).toBe(HERMES);
    expect(report.left_out.find((a: any) => a.id === "router")?.fork_only).toBe(true);
    expect(report.left_out.find((a: any) => a.id === "root")?.reason).toContain("host-level access");
    expect(existsSync(path.join(out, "apps", "gone"))).toBe(false);
    const compose = parse(readFileSync(path.join(out, "apps", "notes", "docker-compose.yml"), "utf8"));
    expect(compose.services.notes.volumes).toEqual(["${APP_DATA_DIR}/volumes/data:/data"]);
    expect(compose.services.notes.init).toBe(true);
    expect(compose.services.notes.ports).toEqual(["127.0.0.1:${APP_PORT}:8000"]);
    const cfg = JSON.parse(readFileSync(path.join(out, "apps", "notes", "config.json"), "utf8"));
    expect(cfg.categories).toEqual(["utilities"]);
    expect(cfg.short_desc).toBe("Does notes things");
    expect(existsSync(path.join(out, "apps", "notes", "metadata", "logo.jpg"))).toBe(true);
    expect(readFileSync(path.join(out, "apps", "notes", "metadata", "description.md"), "utf8")).toStartWith("# notes");

    // A new commit for the same app raises tipi_version over the last generated store, so boxes see the update.
    const next = path.join(root, "out2");
    const rep2 = await generate({
      out: next, previous: out, index: "https://index.test",
      get: async () => ({ apps: [{ ...index[0], install: { ...index[0].install, commit: C2 } }], next_offset: null }),
      hermesLock: { agent_recipe: { repo: "oscarhenrycollins/hermes-agent", commit: HERMES } },
      fetch: (git: string, _c: string, dest: string) => cpSync(path.join(repos, git.split("/").pop()!), dest, { recursive: true }),
    });
    expect(rep2.included[0].tipi_version).toBe(4);
  });

  test("an app whose wizard.md id differs from the index is left out", () => {
    const root = tmp();
    fixtureRepo(path.join(root, "src"), "other");
    expect(() => buildApp({ rec: { id: "notes", repo: "humanitylabs-org/notes", install: { git: "g", commit: C1 } }, src: path.join(root, "src"), dst: path.join(root, "dst"), previous: null })).toThrow("wizard.md id");
  });
});
