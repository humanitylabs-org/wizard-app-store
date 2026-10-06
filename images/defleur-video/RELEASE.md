# Private development candidate: 0.2.1-testing

**NOT approved as a preview-only release.** Latest scope requires the original agent-operated workflow. Preserve these packaging fixes but keep the listing disabled and manual publication off. See [WORKFLOW-PARITY.md](WORKFLOW-PARITY.md) for actual helpers/stages and unfinished work; remote publication alone would not make this the requested app.

## Clean publication, not a branch push

`release-files.json` is the **exact allowlist** to export from this private candidate onto a clean branch based on the store's existing `main`. It includes original service/client/tests/docs, the independently drawn geometric JPEG, app metadata, isolated build workflow and translator smoke tooling. Existing main files, including its license and schema-test infrastructure, remain in place. It excludes all recovered vendor source, recovery documents and generated evidence. Copy file contents only; **do not merge, cherry-pick or push this development branch**, whose ancestry contains those excluded files. Deleting vendor files in a later commit would not remove them from history.

Suggested parent workflow (after selecting/verifying the local candidate commit): create a separate worktree from `main`; use the JSON list to `git archive <candidate> -- <each listed path>` and extract there; inspect the diff and history; run tests; then commit on that clean branch. No bulk `git add` from the private branch, no Git bundle/history export, no copying `.git`, scratch files, `node_modules`, media, credentials or owner state. Keep the original vendor snapshot and provenance privately, unchanged. The list is finite and tested for completeness and exclusion of vendor/evidence paths.

## Upstream licensing finding

The recovered `vendor/defleur-video/plugin.json` declares `"license":"MIT"`; that snapshot contains no LICENSE/COPYING file or complete copyright/permission notice. The declaration is not a supplied notice that we can preserve faithfully. Do not invent attribution, reconstruct an assumed copyright holder or apply the store's license to the recovered code. Obtain the actual notice/redistribution permission before publishing those original helpers. No legal opinion about derivative-work status is implied by this packaging check.

This candidate is a separately written stdlib/FFmpeg service informed by the upstream workflow contracts, not a plugin wrapper. It imports no vendor or Hermes runtime. The original service adapters contain no redistributed helper source; hash-pinned helpers execute only when an authorized administrator supplies a private read-only snapshot. That is not licensing clearance for redistribution. The image copies only `service.py`, `editing.py`, `client.py`, `workflow.py` from the allowlisted build context. Ubuntu/FFmpeg/fonts and their existing distribution notices remain in the base filesystem; no invented license notices or unsupported OCI-license label is added.

The public-facing provenance is retained in the image README without linking to private recovery files. The app icon was regenerated from basic color/rectangle primitives with FFmpeg, not sourced from an upstream asset. Runtipi's pinned public translator modules are fetched into ephemeral scratch only for tests and their hashes verified; they are not committed or added to the image.

## Release workflow

`.github/workflows/video.yml` follows this store's GitHub Actions/GHCR convention: checkout, Node/npm validation, bounded local build/tests, actual translator/lifecycle smoke, verification-log artifact, GHCR login with `GITHUB_TOKEN`, then tag and push the **exact tested local image** as:

```
ghcr.io/humanitylabs-org/defleur-video:0.2.1-testing
```

Normal pushes test only. GHCR login/push require an explicit workflow_dispatch `publish:true` (default false), reserved for approved original-workflow parity and licensing. The build context is only `images/defleur-video`, enforced by `.dockerignore`. amd64 only. The workflow does not mutate the app's availability or package visibility. No workflow has been dispatched and no image has been pushed as part of local preparation.

Parent release gates:

1. Complete the original-workflow port and its real review gates; resolve licensing/runtime decisions in WORKFLOW-PARITY.md. Export only the allowlisted candidate files onto clean main ancestry; inspect that no vendor/recovery/evidence history is reachable.
2. Run CI and publish the image; make that GHCR package public. Verify anonymous pull and record the actual remote digest. A successful push alone is insufficient.
3. Keep `available:false` until the parent explicitly promotes the published recipe. Validate the user's actual Runtipi installation/upgrade and private reachability; this candidate has not installed an app on an owner host.
4. Share the API/client and [Hermes operator instructions](HERMES.md). Hermes owns instruction-led editorial judgment; an autonomous-director daemon is not a release prerequisite. API mechanics and actual workflow gates are. No in-app timeline editor is promised.

## Verified locally

- 22 host and 22 network-disabled/read-only/non-root container tests passed with the authorized private snapshot mounted. Host discovery additionally skips the separately opt-in scale test. The public-image test explicitly skips private-helper execution when the snapshot is absent, not a false parity pass. Real FFmpeg/HTTP, actual upstream PCM/preset helpers, VFR rejection, helper hash/symlink rejection, immutable decisions, caption timing/geometry, evidence hashes and failure cleanup are exercised. SQLite regression retains strong references to 202 connections, proves commit/rollback and immediate close; a separate idle-worker regression catches the polling leak without relying on garbage collection.
- Container observed UID 1000; 1536 MiB memory/no swap and two CPU equivalents enforced. Cgroup peak in the latest private-helper regression run was 62,361,600 bytes (a tiny synthetic fixture, not a production sizing result).
- Actual Runtipi 4.8.0 `DockerComposeBuilder`, pinned revision `102f1ac87cf4aeb4871595c127df765fba37c67a`, type-erased with unchanged builder logic. Test-only substitutions: cached image, disposable external bridge, loopback ephemeral port. Its installation permission step is verified against pinned source and mirrored on disposable data; the entire Runtipi orchestrator/dashboard is not running.
- Fresh Docker-created bind: container root UID 0, mode 0755. Runtipi's post-up recursive chmod makes it 0777, **not** UID 1000. Two initial permission-failure restarts occurred before successful non-root readiness. The recipe's translated `unless-stopped` policy recovered. This broad permission model is a documented private-host limitation, not claimed secure chown behavior.
- A real authenticated captioned HTTP render produced a 153,747-byte MP4, SHA-256 `c6761b640a54232b7bc6c7d8a579b679b321847bd1b30f0629610c1c44d998ca`, state `needs_review`; seven evidence artifacts verified. Exact project/decision/job/source/preview survived restart, stop/start and forced container recreation. Offline review bundle checksum validation repeated afterward; delete read-back returned missing targets.

- Store/schema tests: 16 passed, 197 assertions; TypeScript no-emit succeeded. Original upstream audio-gate negative regression ran separately: one test passed, without exposing an approval API.
- A separately measured 270MiB/184s synthetic HTTP+upstream-PCM capacity test passed, peak417,062,912 bytes. It uses tiny frames and padding, not the original footage or full workflow. See WORKFLOW-PARITY.md.

The internal-only bridge variant suppressed published ports on this Docker host; the successful lifecycle test therefore uses an ordinary disposable bridge and loopback port. Separate media regression tests still run with `--network none`. This distinction is intentional, not evidence of remote reachability.

## Remaining limits, not promised features

Remote publication/anonymous pull and real user-host installation remain unverified. ASR/alignment, complete acoustic review/lock, portrait ledger, semantic capture, upstream caption/encode and delivery-gate adapters remain engineering gaps. Source admission is 512MiB/300s; legacy preview output remains60s. Original source/owner preset validation and suitable model/runtime resources are required, without inventing paid results. Production filesystem quotas/crash-orphan cleanup, HTTP/TLS/rate-limit hardening, package/SBOM/security review and broader architecture testing remain work. Base digest is pinned; apt versions are not locked, so builds are not byte-reproducible. Scope is the original Hermes-operated workflow, NOT an accepted private preview demo.
