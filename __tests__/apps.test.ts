import { describe, expect, test } from "bun:test";
import { appInfoSchema, dynamicComposeSchemaYaml } from "@runtipi/common/schemas";
import { type } from "arktype";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { parse } from "yaml";

for (const id of readdirSync("apps", { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name)) {
  const dir = `apps/${id}`;
  const config = JSON.parse(readFileSync(`${dir}/config.json`, "utf8"));
  const compose = parse(readFileSync(`${dir}/docker-compose.yml`, "utf8"));
  describe(id, () => {
    test("required metadata and real JPEG", () => {
      expect(existsSync(`${dir}/metadata/description.md`)).toBe(true);
      expect(readFileSync(`${dir}/metadata/logo.jpg`).subarray(0, 3).toString("hex")).toBe("ffd8ff");
      expect(config.id).toBe(id);
    });
    test("official Runtipi metadata schema", () => {
      const result = appInfoSchema.omit("urn")(config);
      if (result instanceof type.errors) throw new Error(result.summary);
    });
    test("official native Compose schema", () => {
      const result = dynamicComposeSchemaYaml(compose);
      if (result instanceof type.errors) throw new Error(result.summary);
      expect(compose["x-runtipi"].schema_version).toBe(2);
    });
    test("Wizard app type: agent, service, view or external", () => {
      // Runtipi's category list is fixed upstream, so the Wizard type lives in `wizard_type`,
      // is mirrored as the short_desc prefix (visible in the Runtipi UI) and maps to one native category.
      const types: Record<string, [string, string]> = {
        agent: ["Agent", "ai"], service: ["Service", "utilities"], view: ["View", "media"], external: ["External", "network"],
      };
      expect(Object.keys(types)).toContain(config.wizard_type);
      const [label, category] = types[config.wizard_type]!;
      expect(config.short_desc.startsWith(`${label}: `)).toBe(true);
      expect(config.categories).toEqual([category]);
      if (config.wizard_type === "service" || config.wizard_type === "external") expect(config.no_gui).toBe(true);
      if (config.wizard_type === "view") expect(config.no_gui ?? false).toBe(false);
    });
    if (id === "hermes-agent") {
    test("unmodified pinned image and supported startup", () => {
      const s = compose.services[id];
      expect(s.image).toMatch(new RegExp(`^nousresearch/hermes-agent:${config.version.replaceAll(".", "\\.")}@sha256:[a-f0-9]{64}$`));
      expect(s.command).toEqual(["gateway", "run"]);
      expect(s.entrypoint).toBeUndefined();
      expect(s.user).toBeUndefined();
      expect(s["x-runtipi"]).toEqual({is_main: true, internal_port: 9119});
    });
    test("isolated data, no host privileges or auth bypass", () => {
      const s = compose.services[id];
      expect(Object.keys(compose.services)).toEqual([id]);
      expect(s.volumes).toEqual(["${APP_DATA_DIR}/data:/opt/data"]);
      for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build"]) expect(s[key]).toBeUndefined();
      expect(s.environment.HERMES_DASHBOARD_INSECURE).toBeUndefined();
      expect(s.environment.HERMES_UMBREL_APP_PROXY_AUTH).toBeUndefined();
      expect(config.exposable).toBe(false);
      for (const suffix of ["USERNAME", "PASSWORD", "SECRET"]) {
        const key = `HERMES_DASHBOARD_BASIC_AUTH_${suffix}`;
        expect(s.environment[key]).toBe(`\${${key}}`);
        expect(config.form_fields.some((f: {env_variable: string}) => f.env_variable === key)).toBe(true);
      }
      const pwd = config.form_fields.find((f: {env_variable: string}) => f.env_variable.endsWith("PASSWORD"));
      expect(pwd.required).toBe(true);
      expect(pwd.default).toBeUndefined();
    });
    }
    if (id === "transcriber") {
      test("unmodified pinned Speaches image, private, unprivileged", () => {
        const s = compose.services[id];
        expect(Object.keys(compose.services)).toEqual([id]);
        expect(s.image).toMatch(new RegExp(`^ghcr\\.io/speaches-ai/speaches:${config.version.replaceAll(".", "\\.")}@sha256:[a-f0-9]{64}$`));
        expect(s.read_only).toBe(true);
        expect(s.cap_drop).toEqual(["ALL"]);
        expect(s.security_opt).toEqual(["no-new-privileges:true"]);
        expect(s.volumes).toEqual(["${APP_DATA_DIR}/data/huggingface:/home/ubuntu/.cache/huggingface"]);
        expect(s.environment.PRELOAD_MODELS).toBe('["${TRANSCRIBER_MODEL}"]');
        expect(s["x-runtipi"]).toEqual({is_main: true, internal_port: 8000});
        for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "command", "entrypoint", "user"]) expect(s[key]).toBeUndefined();
        expect(config.exposable).toBe(false);
        expect(config.uid).toBe(1000);
      });
    }
    if (id === "browser") {
      test("vanilla pinned headless Chromium, private, generous limits", () => {
        const s = compose.services[id];
        expect(Object.keys(compose.services)).toEqual([id]);
        expect(s.image).toMatch(new RegExp(`^chromedp/headless-shell:${config.version.replaceAll(".", "\\.")}@sha256:[a-f0-9]{64}$`));
        for (const key of ["privileged", "network_mode", "pid", "devices", "cap_add", "build", "command", "entrypoint", "volumes"]) expect(s[key]).toBeUndefined();
        expect(s.user).toBe("1000:1000");
        expect(s.read_only).toBe(true);
        expect(s.cap_drop).toEqual(["ALL"]);
        expect(s.security_opt).toEqual(["no-new-privileges:true"]);
        expect(s.init).toBe(true);
        // Unauthenticated DevTools: loopback-only on the host, Runtipi network for other apps.
        expect(s.ports).toEqual(["127.0.0.1:${APP_PORT}:9222"]);
        expect(s["x-runtipi"]).toEqual({is_main: true});
        expect(parseInt(s.mem_limit)).toBeGreaterThanOrEqual(4);
        expect(s.memswap_limit).toBe(s.mem_limit);
        expect(s.pids_limit).toBeGreaterThanOrEqual(1024);
        expect(s.shm_size).toBe("2g");
        expect(config.exposable).toBe(false);
        expect(config.form_fields).toEqual([]);
        expect([8787, 8791, 8792, 9119, 9120]).not.toContain(config.port);
      });
    }
    if (id === "files") {
      test("unmodified pinned File Browser on Runtipi's shared media folder only; optional login", () => {
        const s = compose.services[id];
        expect(Object.keys(compose.services)).toEqual([id]);
        expect(s.image).toMatch(new RegExp(`^filebrowser/filebrowser:${config.version.replaceAll(".", "\\.")}@sha256:[a-f0-9]{64}$`));
        // Only the standard shared folder (as the official store's filebrowser recipes mount it) plus its own database.
        expect(s.volumes).toEqual(["${ROOT_FOLDER_HOST}/media:/srv", "${APP_DATA_DIR}/data/db:/database"]);
        for (const key of ["privileged", "network_mode", "pid", "devices", "build", "command"]) expect(s[key]).toBeUndefined();
        expect(s.read_only).toBe(true);
        expect(s.cap_drop).toEqual(["ALL"]);
        // Root only to hand the root-owned media folder (not its contents) to uid 1000, then setuidgid.
        expect(s.cap_add).toEqual(["CHOWN", "SETUID", "SETGID"]);
        expect(s.security_opt).toEqual(["no-new-privileges:true"]);
        const script = s.entrypoint.join("\n");
        expect(script).not.toMatch(/chown -R|chmod -R/);
        expect(script).toContain("exec setuidgid user filebrowser");
        for (const d of ["Videos", "Videos/Edited", "Documents"]) expect(script).toContain(d);
        expect(script).toContain("--tus.chunkSize 10485760");
        expect(script).toContain("--auth.method noauth");
        expect(script).toContain("--auth.method json");
        expect(script).toContain("--perm.execute=false");
        expect(s["x-runtipi"]).toEqual({is_main: true, internal_port: 8080});
        expect(config.form_fields).toHaveLength(1);
        const pwd = config.form_fields[0];
        expect([pwd.env_variable, pwd.type, pwd.required, pwd.min]).toEqual(["FILES_PASSWORD", "password", false, 12]);
        expect(s.environment.FILES_PASSWORD).toBe("${FILES_PASSWORD}");
        expect(config.description).toMatch(/public domain/);
        expect([8787, 8791, 8792, 8793, 9119, 9120]).not.toContain(config.port);
      });
    }
    if (id === "hermes-frontend-3") {
      test("separate unprivileged frontend with no agent state or secrets", () => {
        const s = compose.services[id];
        expect(Object.keys(compose.services)).toEqual([id]);
        expect(s.image).toStartWith(`ghcr.io/humanitylabs-org/hermes-frontend-3:${config.version}`);
        expect(s.user).toBe("101:101");
        expect(s.cap_drop).toEqual(["ALL"]);
        expect(s.security_opt).toEqual(["no-new-privileges:true"]);
        expect(s.environment).toEqual({HERMES_BACKEND_URL: "${HERMES_BACKEND_URL}"});
        expect(s["x-runtipi"]).toEqual({is_main: true, internal_port: 8080});
        for (const key of ["volumes", "privileged", "network_mode", "pid", "devices", "cap_add", "build", "command", "entrypoint"]) expect(s[key]).toBeUndefined();
        expect(config.exposable).toBe(false);
        expect(config.form_fields).toHaveLength(1);
        expect(config.form_fields[0].required).toBe(true);
        expect(config.form_fields[0].env_variable).toBe("HERMES_BACKEND_URL");
      });
    }
  });
}
