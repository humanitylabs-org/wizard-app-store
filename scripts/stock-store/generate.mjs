#!/usr/bin/env node
// Generate the stock-Runtipi Wizard store (humanitylabs-org/wizard-os#822).
//
// Reads every app the Wizard App Index approves, fetches each one's repo at exactly the approved commit, does the
// fork's publish-time compile steps (compile.mjs) and writes a plain Runtipi app store: <out>/apps/<id>/...
// Apps that still need the fork are left out and named, with the reason, in <out>/stock-store.json.
// hermes-agent is taken at the commit the App Manager's Hermes lock pins today (wam/hermes-lock.json), never newer.
//
//   node scripts/stock-store/generate.mjs --out <dir> [--previous <dir>] [--index URL] [--only id,id] [--images <repo> [--push]]
//
// --images ships source/build apps as images built from their approved commit (images.mjs); --push publishes them.
//
// Nothing reads this output unless a box is pointed at the `stock` branch, which only the off-by-default
// installer switch WIZARD_STOCK_RUNTIPI=1 does.
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { parse, stringify } from "yaml";
import { appInfoSchema, dynamicComposeSchemaYaml } from "@runtipi/common/schemas";
import { type } from "arktype";
import {
  ID, SHA, addStopInit, allowedPublisher, body, chatsModule, composeRisks, forkOnlyNeeds, frontMatter, imageTag, loopbackMainPort,
  mountAppGrants, packageImages, rewriteVolumes, stockConfig,
} from "./compile.mjs";
import { dockerPublisher } from "./images.mjs";

export const DEFAULT_INDEX = "https://apps.aiwizards.com";
export const HERMES_LOCK_URL = "https://raw.githubusercontent.com/humanitylabs-org/wizard-app-manager/main/wam/hermes-lock.json";
// The For testers release (wizard-os releases/latest): its default apps go in at the release's own commits, so a
// stock box gets the same shell, Agent Service, connections and services a fork box of that release gets.
export const RELEASES_URL = "https://raw.githubusercontent.com/humanitylabs-org/wizard-os/main/releases";

async function getText(url) {
  const res = await fetch(url, { headers: { "user-agent": "wizard-app-store-stock-generator" }, signal: AbortSignal.timeout(30000) });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.text();
}

/** The release whose default apps the store carries: releases/latest -> releases/<version>.json. */
export async function latestRelease(get = getJson, text = getText, base = RELEASES_URL) {
  const version = String(await text(`${base}/latest`)).trim();
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`releases/latest is not a version: ${version.slice(0, 40)}`);
  return get(`${base}/${version}.json`);
}

// A release also pins the shell and Agent Service images (built from those same commits). Their recipes name them as
// ${WIZARD_UX_IMAGE:-...}; the fork's App Manager fills that variable, stock Runtipi can't, so the store writes it in.
export const IMAGE_VARS = { "wizard-shell": "WIZARD_SHELL_IMAGE", "wizard-ux": "WIZARD_UX_IMAGE", "wizard-agent-service": "WIZARD_AGENT_SERVICE_IMAGE" };

/** repo@digest for a release image pin (wam release_pins.image_ref), or null. */
export function releaseImage(im) {
  const digest = String(im?.digest ?? "");
  const repo = String(im?.ref ?? "").replace(/(@.*|:[^/:]*)$/, "");
  if (!/^sha256:[0-9a-f]{64}$/.test(digest) || !/^[a-z0-9.-]+(?::[0-9]+)?(?:\/[a-z0-9._-]+)+$/.test(repo)) return null;
  return `${repo}@${digest}`;
}

/** Recipe images spelled ${<var>:-...} (or ${<var>}) become the pinned image. */
export function pinImages(compose, pins) {
  for (const svc of Object.values(compose?.services ?? {})) {
    const m = /^\$\{([A-Z_][A-Z0-9_]*)(?::?-[^}]*)?\}$/.exec(String(svc?.image ?? ""));
    if (m && pins?.[m[1]]) svc.image = pins[m[1]];
  }
  return compose;
}

/** Release default apps replace (or add) index records, at the release's commit. hermes-agent is left to the lock. */
export function applyRelease(apps, release) {
  const pinned = [];
  for (const row of Object.values(release?.default_apps ?? {})) {
    if (!row || typeof row !== "object") continue;
    const { app, repo, commit } = row;
    if (!ID.test(String(app ?? "")) || !SHA.test(String(commit ?? "")) || !/^[\w.-]+\/[\w.-]+$/.test(String(repo ?? ""))) continue;
    if (app === "hermes-agent") continue;
    const rec = { id: app, repo, install: { git: `https://github.com/${repo}`, commit } };
    const img = IMAGE_VARS[app] ? releaseImage(release?.images?.[app]) : null;
    if (img) rec.imagePins = { [IMAGE_VARS[app]]: img };
    const at = apps.findIndex((a) => a.id === app);
    if (at >= 0) apps[at] = { ...apps[at], ...rec };
    else apps.push(rec);
    pinned.push({ id: app, repo, commit, ...(img ? { image: img } : {}) });
  }
  return pinned;
}

export const args = (argv) => {
  const o = {};
  for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) o[argv[i].slice(2)] = i + 1 >= argv.length || argv[i + 1].startsWith("--") ? true : argv[++i];
  return o;
};

async function getJson(url) {
  const res = await fetch(url, { headers: { accept: "application/json", "user-agent": "wizard-app-store-stock-generator" }, signal: AbortSignal.timeout(30000) });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

/** Every listed app, in index order. */
export async function listIndex(index, get = getJson) {
  const out = [];
  let offset = 0;
  for (let page = 0; page < 100 && offset != null; page++) {
    const res = await get(`${index}/v1/search?${new URLSearchParams({ q: "", limit: "50", offset: String(offset) })}`);
    out.push(...(res.apps ?? []));
    offset = res.next_offset;
  }
  return out;
}

/** One record per id: first-party only, the index's first hit wins (what the fork picks on a fresh box). */
export function pickApps(records, publishers = process.env.WAM_PUBLISHERS ?? "") {
  const seen = new Map();
  const dropped = [];
  for (const r of records) {
    if (!ID.test(String(r?.id ?? "")) || !SHA.test(String(r?.install?.commit ?? ""))) continue;
    if (!allowedPublisher(r, publishers)) {
      dropped.push({ id: r.id, repo: r.repo, reason: "publisher is not first-party (wizard-os#138)" });
      continue;
    }
    if (seen.has(r.id)) {
      dropped.push({ id: r.id, repo: r.repo, reason: `id already published by ${seen.get(r.id).repo}` });
      continue;
    }
    seen.set(r.id, r);
  }
  return { apps: [...seen.values()], dropped };
}

/** Fetch exactly one commit into dest and check it is that commit. */
export function fetchCommit(git, commit, dest) {
  mkdirSync(dest, { recursive: true });
  const run = (...a) => execFileSync("git", ["-C", dest, ...a], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, GIT_TERMINAL_PROMPT: "0" } }).toString().trim();
  run("init", "-q");
  run("fetch", "-q", "--depth=1", git, commit);
  run("-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD");
  const head = run("rev-parse", "HEAD");
  if (head !== commit) throw new Error(`fetched ${head} instead of ${commit}`);
}

const schemaErrors = (cfg, compose) => {
  const errs = [];
  const a = appInfoSchema.omit("urn")(cfg);
  if (a instanceof type.errors) errs.push(`config.json: ${a.summary}`);
  const c = dynamicComposeSchemaYaml(compose);
  if (c instanceof type.errors) errs.push(`docker-compose.yml: ${c.summary}`);
  return errs;
};

const readPrevious = (prevDir, id) => {
  if (!prevDir) return null;
  try {
    const cfg = JSON.parse(readFileSync(path.join(prevDir, "apps", id, "config.json"), "utf8"));
    const commit = readFileSync(path.join(prevDir, "apps", id, ".wizard-commit"), "utf8").trim();
    let compose = null;
    try {
      compose = readFileSync(path.join(prevDir, "apps", id, "docker-compose.yml"), "utf8");
    } catch {}
    return { tipi_version: cfg.tipi_version, commit, compose };
  } catch {
    return null;
  }
};

/** Turn one checked-out app repo into a stock Runtipi app folder at dst. Throws with a plain reason when it can't. */
// `publish` (images.mjs dockerPublisher) builds the images that replace source/build packaging; without it such apps
// stay fork-only and are left out.
export function buildApp({ rec, src, dst, previous, publish = undefined }) {
  const commit = rec.install.commit;
  const wizardPath = path.join(src, "wizard.md");
  if (!existsSync(wizardPath)) throw new Error("no wizard.md");
  const wizardText = readFileSync(wizardPath, "utf8");
  const d = parse(frontMatter(wizardText)) ?? {};
  if (d.id !== rec.id) throw new Error(`wizard.md id ${String(d.id)} != ${rec.id}`);
  const rt = d.runtime ?? {};
  if (!rt.config || !rt.compose) throw new Error("wizard.md runtime.config/compose missing");
  const cfgFile = path.join(src, rt.config);
  const composeFile = path.join(src, rt.compose);
  if (!existsSync(cfgFile) || !existsSync(composeFile)) throw new Error(`runtime files missing at ${commit}`);
  const composeText = readFileSync(composeFile, "utf8");
  const needs = forkOnlyNeeds(d, composeText, !!publish);
  if (needs.length) throw Object.assign(new Error(`needs the fork: ${needs.join("; ")}`), { forkOnly: true });
  let compose = parse(composeText);
  const risks = composeRisks(compose);
  if (risks.length) throw new Error(`asks for host-level access: ${risks.join("; ")}`);
  if (rec.imagePins) pinImages(compose, rec.imagePins);
  const packaged = publish ? packageImages(compose, d, rec.id, commit) : { compose, images: [] };
  compose = packaged.compose;
  const images = [];
  if (packaged.images.length) {
    // The fork copies the source without .git (packaging.ts copySource); so does the image.
    rmSync(path.join(src, ".git"), { recursive: true, force: true });
    for (const img of packaged.images) {
      const dfText = img.kind === "build" ? readFileSync(path.join(src, img.dockerfile), "utf8") : "";
      const ref = publish({ appId: rec.id, img, tag: imageTag(rec.id, img, commit, dfText), src, commit });
      compose.services[img.service].image = ref;
      images.push({ service: img.service, kind: img.kind, image: ref });
    }
  }
  compose = loopbackMainPort(mountAppGrants(addStopInit(rewriteVolumes(compose, rec.id))));
  const composeOut = stringify(compose, { lineWidth: 0 });
  // Same commit but a different recipe (e.g. a newly pinned release image) is an update too: count it as a new commit.
  const prev = previous && previous.compose != null && previous.compose !== composeOut ? { ...previous, commit: null } : previous;
  const cfg = stockConfig(JSON.parse(readFileSync(cfgFile, "utf8")), d, commit, prev);
  const errs = schemaErrors(cfg, compose);
  if (errs.length) throw new Error(`stock Runtipi rejects it: ${errs.join("; ")}`);

  const tmp = `${dst}.tmp-${process.pid}`;
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(path.join(tmp, "metadata"), { recursive: true });
  writeFileSync(path.join(tmp, "config.json"), `${JSON.stringify(cfg, null, 2)}\n`);
  writeFileSync(path.join(tmp, "docker-compose.yml"), composeOut);
  const desc = body(wizardText);
  writeFileSync(path.join(tmp, "metadata", "description.md"), `${desc.startsWith("# ") ? "" : `# ${String(d.name ?? rec.id)}\n\n`}${desc}\n`);
  writeFileSync(path.join(tmp, "wizard.md"), wizardText);
  const chats = chatsModule(d, commit, (m) => {
    const f = path.resolve(src, m);
    if (!f.startsWith(path.resolve(src) + path.sep) || !statSync(f).isFile()) throw Error("Chats module must be a file in the repo");
    return readFileSync(f);
  });
  if (chats) {
    mkdirSync(path.dirname(path.join(tmp, chats.module)), { recursive: true });
    writeFileSync(path.join(tmp, chats.module), chats.bytes);
    writeFileSync(path.join(tmp, ".wizard-chats-view.json"), chats.meta);
  }
  if (typeof d.skill === "string" && existsSync(path.join(src, d.skill))) cpSync(path.join(src, d.skill), path.join(tmp, "SKILL.md"));
  const cfgDir = path.dirname(cfgFile);
  for (const cand of [path.join(cfgDir, "metadata", "logo.jpg"), typeof d.icon === "string" ? path.join(src, d.icon) : "", path.join(cfgDir, "logo.jpg"), path.join(src, "metadata", "logo.jpg")]) {
    if (cand && existsSync(cand) && statSync(cand).isFile()) {
      cpSync(cand, path.join(tmp, "metadata", "logo.jpg"));
      break;
    }
  }
  if (existsSync(path.join(cfgDir, "data"))) cpSync(path.join(cfgDir, "data"), path.join(tmp, "data"), { recursive: true });
  writeFileSync(path.join(tmp, ".wizard-commit"), `${commit}\n`);
  writeFileSync(path.join(tmp, ".wizard-source"), `${JSON.stringify({ repo: rec.repo, git: rec.install.git, source: "stock-store" })}\n`);
  rmSync(dst, { recursive: true, force: true });
  mkdirSync(path.dirname(dst), { recursive: true });
  cpSync(tmp, dst, { recursive: true });
  rmSync(tmp, { recursive: true, force: true });
  return { id: rec.id, repo: rec.repo, commit, version: cfg.version, tipi_version: cfg.tipi_version, ...(images.length ? { images } : {}) };
}

export async function generate({ out, previous, index = DEFAULT_INDEX, only, get = getJson, fetch: fetchRepo = fetchCommit, hermesLock, release, publish }) {
  const lock = hermesLock ?? (await get(HERMES_LOCK_URL));
  const recipe = lock?.agent_recipe;
  if (!recipe || !SHA.test(String(recipe.commit)) || !recipe.repo) throw new Error("Hermes lock has no agent_recipe pin");
  const { apps, dropped } = pickApps(await listIndex(index, get));
  // hermes-agent: exactly today's pin (James's lock), whatever the index lists.
  const hermes = apps.find((a) => a.id === "hermes-agent");
  if (hermes) Object.assign(hermes, { repo: recipe.repo, install: { git: `https://github.com/${recipe.repo}`, commit: recipe.commit } });
  const rel = release === undefined ? await latestRelease(get) : release;
  const releasePins = applyRelease(apps, rel);
  const want = only ? new Set(String(only).split(",")) : null;
  const work = mkdtempSync(path.join(process.env.TMPDIR || tmpdir(), "stock-store-822-"));
  const included = [];
  const left_out = [...dropped];
  mkdirSync(path.join(out, "apps"), { recursive: true });
  try {
    for (const rec of apps) {
      if (want && !want.has(rec.id)) continue;
      const src = path.join(work, rec.id);
      try {
        fetchRepo(rec.install.git, rec.install.commit, src);
        included.push(buildApp({ rec, src, dst: path.join(out, "apps", rec.id), previous: readPrevious(previous, rec.id), publish }));
      } catch (e) {
        left_out.push({ id: rec.id, repo: rec.repo, commit: rec.install.commit, reason: String(e?.message ?? e), fork_only: !!e?.forkOnly });
        rmSync(path.join(out, "apps", rec.id), { recursive: true, force: true });
      } finally {
        rmSync(src, { recursive: true, force: true });
      }
    }
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
  // Apps no longer listed leave the store (Runtipi keeps installed copies; it just offers no update).
  if (!want) {
    const keep = new Set(included.map((a) => a.id));
    for (const name of readdirSync(path.join(out, "apps"))) if (!keep.has(name)) rmSync(path.join(out, "apps", name), { recursive: true, force: true });
  }
  const report = { schema: 1, index, hermes_pin: { repo: recipe.repo, commit: recipe.commit },
    release: rel ? { version: rel.version ?? null, default_apps: releasePins } : null, included, left_out };
  writeFileSync(path.join(out, "stock-store.json"), `${JSON.stringify(report, null, 2)}\n`);
  return report;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const o = args(process.argv.slice(2));
  if (!o.out) {
    console.error("usage: generate.mjs --out <dir> [--previous <dir>] [--index URL] [--only id,id] [--images <image repo> [--push]]");
    process.exit(2);
  }
  const report = await generate({ out: path.resolve(o.out), previous: o.previous ? path.resolve(o.previous) : undefined, index: o.index || DEFAULT_INDEX, only: o.only,
    publish: o.images ? dockerPublisher({ repo: o.images, push: !!o.push, platforms: process.env.STOCK_IMAGE_PLATFORMS || undefined }) : undefined });
  console.log(`stock store: ${report.included.length} apps written, ${report.left_out.length} left out`);
  for (const a of report.included) console.log(`  + ${a.id} ${a.version ?? ""} (${a.repo}@${a.commit.slice(0, 12)})`);
  for (const a of report.left_out) console.log(`  - ${a.id} (${a.repo}): ${a.reason}`);
}
