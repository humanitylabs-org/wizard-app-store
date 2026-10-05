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
  });
}
