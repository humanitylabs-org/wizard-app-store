// Publish-time compile steps for the generated stock-Runtipi store (humanitylabs-org/wizard-os#822).
//
// The Wizard App Manager fork does these when an app is fetched or started (wizard-app-manager
// packages/backend: wizard-index-store.ts, wizard-storage.ts rewriteVolumes, wizard-stop-init.ts).
// Stock Runtipi does none of them, so the generator does them once, here, and writes plain Runtipi
// app folders. Every function is pure: same input, same output.
import { createHash } from "node:crypto";

export const ID = /^[a-z0-9][a-z0-9-]{0,62}$/;
export const SHA = /^[0-9a-f]{40}$/;

// Same list and override as the fork (wizard-os#138): only first-party publishers until apps stop acting as the owner.
export const FIRST_PARTY_PUBLISHERS = ["humanitylabs-org", "oscarhenrycollins", "jdefleur", "defleur-agents"];
export const allowedPublisher = (rec, env = "") => {
  const raw = String(env ?? "").trim();
  if (raw === "*") return true;
  const allow = raw ? raw.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean) : FIRST_PARTY_PUBLISHERS;
  const owner = String(rec?.publisher || String(rec?.repo ?? "").split("/")[0]).toLowerCase();
  return allow.includes(owner);
};

/** Container settings that would give an app control of the host. Same rule as the fork and the index checker. */
export const composeRisks = (doc) => {
  const risks = [];
  const services = doc?.services ?? {};
  const bad = ["ALL", "SYS_ADMIN", "SYS_MODULE", "SYS_PTRACE", "SYS_RAWIO", "NET_ADMIN", "DAC_READ_SEARCH", "BPF", "PERFMON"];
  for (const [name, s] of Object.entries(services)) {
    if (!s || typeof s !== "object") continue;
    if (s.privileged) risks.push(`${name}: privileged`);
    for (const k of ["network_mode", "pid", "ipc", "userns_mode", "uts"]) {
      if (String(s[k] ?? "").toLowerCase() === "host") risks.push(`${name}: ${k}: host`);
    }
    for (const c of s.cap_add ?? []) {
      if (bad.includes(String(c).toUpperCase().replace(/^CAP_/, ""))) risks.push(`${name}: cap_add ${c}`);
    }
    if (Array.isArray(s.devices) && s.devices.length) risks.push(`${name}: host devices`);
    for (const opt of s.security_opt ?? []) if (/unconfined/i.test(String(opt))) risks.push(`${name}: security_opt ${opt}`);
    for (const v of s.volumes ?? []) {
      const src = typeof v === "string" ? v.split(":")[0] : String(v?.source ?? "");
      if (/docker\.sock|containerd\.sock|podman\.sock/.test(src ?? "")) risks.push(`${name}: mounts the container runtime socket`);
      else if (src === "/" || /^\/(etc|root|boot|proc|sys|dev|var\/run|run|home|usr|lib|bin|sbin)(\/|$)/.test(src ?? ""))
        risks.push(`${name}: mounts host path ${src}`);
    }
  }
  return risks;
};

/** Things only the fork can run today. Each is a reason the app is left out of the stock store (listed in the report). */
export const forkOnlyNeeds = (manifest, composeText) => {
  const needs = [];
  const pkg = manifest?.runtime?.package;
  if (pkg === "source" || pkg === "build") needs.push(`runtime.package ${pkg} (the fork copies or builds the source at install; ship an image package)`);
  if (/\$\{?APP_SOURCE_DIR\b/.test(composeText)) needs.push("uses ${APP_SOURCE_DIR}, which only the fork sets");
  if (/^\s*build\s*:/m.test(composeText)) needs.push("builds an image on the box");
  return needs;
};

export const VOLUME = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
export const LEGACY_CLAUDE = "wizard-ai-accounts-claude";
const ownVolumeName = (appId, name) =>
  typeof name === "string" && VOLUME.test(name) && [appId, `wizard-${appId}`].some((p) => name === p || name.startsWith(`${p}-`));
const ownFixed = (appId, opts) =>
  !!opts && typeof opts === "object" && Object.keys(opts).join() === "name" && opts.name !== LEGACY_CLAUDE && ownVolumeName(appId, opts.name);

/**
 * File-backed storage (DECISIONS #79/#80): named volumes become folders under the app's data dir, so backups,
 * restores and moves see every byte. Same mapping as the fork's rewriteVolumes, done at publish time.
 * Throws on volumes that cannot be portable (external, drivers, fixed foreign names).
 */
export function rewriteVolumes(input, appId) {
  const doc = structuredClone(input);
  const aliases = {};
  for (const [name, opts] of Object.entries(doc.volumes ?? {})) {
    if (!VOLUME.test(name) || name === "." || name === "..") throw new Error("Unsafe volume id");
    const claude = appId === "wizard-claude" && opts?.name === LEGACY_CLAUDE;
    const legacyConsumer = opts?.name === LEGACY_CLAUDE && !claude && appId !== "hermes-agent";
    if ((opts?.external && !legacyConsumer) || opts?.driver || opts?.driver_opts) throw new Error(`Nonportable volume ${name}`);
    if (ownFixed(appId, opts) || legacyConsumer) {
      aliases[name] = opts;
      continue;
    }
    if (opts && "name" in opts && opts.name !== LEGACY_CLAUDE) throw new Error(`Fixed volume name ${name}`);
    const relative = claude ? "data/claude" : `volumes/${name}`;
    for (const svc of Object.values(doc.services ?? {})) {
      if (!svc || typeof svc !== "object" || !Array.isArray(svc.volumes)) continue;
      svc.volumes = svc.volumes.map((v) => {
        if (typeof v === "string") {
          const parts = v.split(":");
          if (parts.length > 1 && parts[0] === name) return [`\${APP_DATA_DIR}/${relative}`, ...parts.slice(1)].join(":");
        } else if (v?.source === name && (!v.type || v.type === "volume")) {
          const { volume: _volume, ...rest } = v;
          return { ...rest, type: "bind", source: `\${APP_DATA_DIR}/${relative}` };
        }
        return v;
      });
    }
  }
  if (Object.keys(aliases).length) doc.volumes = aliases;
  else delete doc.volumes;
  return doc;
}

// Python servers as PID 1 ignore `docker stop` (wizard-app-manager#738); Docker's own init passes the signal on.
const PYTHON = /^(?:.*\/)?python(?:\d+(?:\.\d+)*)?$/;
const program = (command) =>
  Array.isArray(command) ? (typeof command[0] === "string" ? command[0] : undefined) : typeof command === "string" ? command.trim().split(/\s+/)[0] : undefined;
export const startsPythonAsPid1 = (s) => {
  if (!s || typeof s !== "object" || s.init !== undefined || s.entrypoint !== undefined) return false;
  const prog = program(s.command);
  return prog !== undefined && PYTHON.test(prog);
};
export function addStopInit(compose) {
  const doc = structuredClone(compose);
  for (const s of Object.values(doc.services ?? {})) if (startsPythonAsPid1(s)) s.init = true;
  return doc;
}

/** Box-only by default: the main port is published on loopback (Tailscale or a Cloudflare Tunnel carry it further). */
export function loopbackMainPort(compose) {
  const doc = structuredClone(compose);
  for (const svc of Object.values(doc.services ?? {})) {
    const xr = svc?.["x-runtipi"] ?? {};
    if (xr.is_main && xr.internal_port && !(Array.isArray(svc.ports) && svc.ports.length)) svc.ports = [`127.0.0.1:\${APP_PORT}:${xr.internal_port}`];
  }
  return doc;
}

// Runtipi's category list is fixed upstream; the Wizard type maps to one native category (same table as apps/ here).
export const TYPE_CATEGORY = { agent: "ai", service: "utilities", view: "media", external: "network" };
export const CATEGORY_FALLBACK = { agent: "ai", interface: "utilities", app: "utilities", system: "utilities" };

/** config.json for stock Runtipi. `previous` is this app's entry from the last generated store, if any. */
export function stockConfig(cfgIn, manifest, commit, previous, now = Date.now()) {
  const cfg = structuredClone(cfgIn);
  const id = String(manifest.id);
  cfg.id = id;
  const wtype = String(manifest.type ?? "").toLowerCase();
  if (TYPE_CATEGORY[wtype]) cfg.wizard_type = wtype;
  cfg.categories = [TYPE_CATEGORY[wtype] ?? CATEGORY_FALLBACK[String(manifest.category ?? "")] ?? "utilities"];
  cfg.short_desc = cfg.short_desc || String(manifest.summary ?? "");
  // A new commit is always an update, even if the author forgot to raise tipi_version; never go backwards.
  const own = Number(cfg.tipi_version) || 1;
  const old = Number(previous?.tipi_version) || 0;
  cfg.tipi_version = previous ? (previous.commit === commit ? Math.max(own, old) : Math.max(own, old + 1)) : own;
  for (const k of ["created_at", "updated_at"]) if (typeof cfg[k] === "number" && cfg[k] >= now) cfg[k] = now - 1000;
  return cfg;
}

/** Same admission rules as the fork's chats-module.ts / wam chats_views.py; returns the files to copy or null. */
export function chatsModule(manifest, commit, readModule) {
  const view = manifest.chats_view;
  const provides = Array.isArray(manifest.provides) ? manifest.provides : [];
  if (view === undefined && !provides.includes("chats")) return null;
  if (!view || typeof view !== "object" || Object.keys(view).sort().join(",") !== "contract,module" || manifest.id === "wizard-chats" ||
      view.contract !== "wizard.chats-view/1" || !provides.includes("chats") || typeof view.module !== "string" ||
      !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*\.js$/.test(view.module) || !SHA.test(commit)) throw Error("Invalid Chats module declaration");
  const bytes = readModule(view.module);
  if (!bytes.length || bytes.length > 128 * 1024) throw Error("Chats module exceeds 128 KiB");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  if (/\b(?:addEventListener|setTimeout|setInterval|requestAnimationFrame|fetch|XMLHttpRequest|__wos|__wux|localStorage|sessionStorage|innerHTML|outerHTML|history|eval|Function|WebSocket|import)\b|document\s*\.\s*cookie/.test(text))
    throw Error("Chats module uses a banned API or exceeds 128 KiB");
  const meta = { contract: "wizard.chats-view/1", module: view.module, sha256: createHash("sha256").update(bytes).digest("hex"), bytes: bytes.length, commit };
  return { module: view.module, bytes, meta: `${JSON.stringify(meta)}\n` };
}

export const frontMatter = (text) => {
  const m = String(text).match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m?.[1]) throw new Error("wizard.md has no front matter");
  return m[1];
};
export const body = (text) => String(text).replace(/^---\n[\s\S]*?\n---\n?/, "").trim();
