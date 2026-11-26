// Build and push the images that replace source/build packaging in the generated stock store
// (humanitylabs-org/wizard-os#822). Used by generate.mjs --images <repo>.
//
// Each image is built once, from exactly the approved commit; its tag (compile.mjs imageTag) names the app, service,
// commit and recipe, so a scheduled run that finds the tag already pushed reuses it and builds nothing.
// --push publishes multi-arch and pins the compose to the pushed digest; without it the image is built locally only
// (pull requests: proves it builds, publishes nothing).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

export const STORE_SOURCE = "https://github.com/humanitylabs-org/wizard-app-store";
const DIGEST = /^sha256:[0-9a-f]{64}$/;

const sh = (cmd, args) => execFileSync(cmd, args, { stdio: ["ignore", "pipe", "pipe"], maxBuffer: 64 * 1024 * 1024 }).toString();

/** Digest of an already pushed tag, or null. */
export function pushedDigest(ref, run = sh) {
  try {
    const m = JSON.parse(run("docker", ["buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"]));
    return DIGEST.test(String(m?.digest)) ? m.digest : null;
  } catch {
    return null;
  }
}

/**
 * Can a box pull it without signing in? Boxes pull anonymously, so a private package would break the install;
 * such an app is left out (with this reason) until the package is public. Only checked for ghcr.io.
 */
export function anonymousPull(ref, run = sh) {
  const m = String(ref).match(/^ghcr\.io\/([^:@]+):([^@]+)/);
  if (!m) return true;
  try {
    const token = JSON.parse(run("curl", ["-fsS", "--max-time", "20", `https://ghcr.io/token?scope=repository:${m[1]}:pull`])).token;
    const code = run("curl", ["-sS", "--max-time", "20", "-o", "/dev/null", "-w", "%{http_code}", "-I", "-H", `Authorization: Bearer ${token}`,
      "-H", "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
      `https://ghcr.io/v2/${m[1]}/manifests/${m[2]}`]).trim();
    return code === "200";
  } catch {
    return false;
  }
}

export function dockerPublisher({ repo, push = false, platforms = "linux/amd64,linux/arm64", run = sh, log = console.error } = {}) {
  if (!/^[a-z0-9.:/_-]+$/.test(String(repo ?? ""))) throw new Error(`bad image repo ${repo}`);
  const pullable = (ref) => {
    if (!anonymousPull(ref, run)) throw new Error(`image ${ref.split("@")[0]} is not public yet, so boxes could not pull it`);
    return ref;
  };
  return ({ appId, img, tag, src, commit }) => {
    const ref = `${repo}:${tag}`;
    if (push) {
      const have = pushedDigest(ref, run);
      if (have) {
        log(`  = ${appId}/${img.service}: ${ref} already pushed`);
        return pullable(`${ref}@${have}`);
      }
    }
    const dir = mkdtempSync(path.join(process.env.TMPDIR || tmpdir(), "stock-image-822-"));
    try {
      let dockerfile = path.join(src, img.dockerfile ?? "Dockerfile");
      if (img.kind === "source") {
        dockerfile = path.join(dir, "Dockerfile");
        writeFileSync(dockerfile, img.dockerfileText);
        writeFileSync(`${dockerfile}.dockerignore`, ".git\n");
      }
      const meta = path.join(dir, "meta.json");
      const args = ["buildx", "build", "--platform", push ? platforms : "linux/amd64", "-f", dockerfile, "-t", ref,
        "--build-arg", `REVISION=${commit}`, "--label", `org.opencontainers.image.source=${STORE_SOURCE}`,
        "--label", `org.opencontainers.image.revision=${commit}`, "--provenance=false", "--metadata-file", meta,
        push ? "--push" : "--load", path.join(src, img.context || ".")];
      log(`  + ${appId}/${img.service}: building ${ref}${push ? " and pushing" : ""}`);
      run("docker", args);
      if (!push) return ref;
      const digest = JSON.parse(readFileSync(meta, "utf8"))["containerimage.digest"];
      if (!DIGEST.test(String(digest))) throw new Error(`no digest for ${ref}`);
      return pullable(`${ref}@${digest}`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  };
}
