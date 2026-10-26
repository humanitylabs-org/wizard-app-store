# Subscription compatibility and release boundary

## Safe defaults and compatibility

- Inventory and usage work independently of `auth.adopt_external_logins`. Do not change that setting or the owner's existing login. No token copying, adoption changes, or Hermes core patches.
- Add/reconnect/remove are OFF unless the dashboard host explicitly sets `WIZARD_ACCOUNT_CHANGES=1`. Default-off listing reads no Hermes config; all top-level and per-row actions are false; POST refuses with 403 before parsing a request.
- Capability negotiation is explicit: `management.contract=wizard.account-management/1`, `management.status=available`, and exact boolean action permissions are all required. Connection-app UI and server-side POST gate fail closed on missing, unsupported, blocked, off, or unavailable broker capabilities. A refresh failure preserves the last read-only cards/meters but removes mutation controls. Initial HTML hides Add; CSS honors hidden attributes.
- Reconnect adds a fresh grant and retains existing grants. Removal uses an exact managed credential ID with confirmation; no provider logout or positional deletion. Stock CLI runs only in the owning Hermes profile. Same-account enrollment may add no quota and may invalidate older grants; the UI warns and compares distinct principals after completion.
- Group grants only when account+subject identity proves they are the same ChatGPT subscription, never by nickname/email. Legacy `CODEX`, `CODEX-2`, `CODEX-3` are a ChatGPT display family, not proof of a shared account. The companion UX normalization keeps each subscription ID and meter intact under one ChatGPT column.

## Claude 0.2.5 release changes

- Any number of subscriptions: nothing in the app, its proxy or its UI counts or caps accounts; fixtures cover 3, 5 and 12 listed and a 4th/5th add (`tests/claude-pool-accounts.py`, `tests/claude-pool-ui.cjs`).
- No page password (the default on a Tailscale-only box, as with the original Connect): account changes are accepted only from same-origin browser requests carrying `X-Wizard-Account-Action: 1` (Origin must match Host; `Sec-Fetch-Site` same-origin or none). A set page password still gates everything as before.
- The original Claude Code sign-in page stays reachable at `claude-code/` (Connect, code, Test, Sign out of the login the agent's Claude Code provider uses). Its row shows "Sign in again" when that login is not working, and "Sign in" falls back to it when the agent has no account broker (older plugin, fresh-mode agent or changes off).
- The Claude Code mirror folds into the original row also for plugins that predate the `mirror` flag (unmanaged grants labelled `claude_code`), so a single-login box never reports a second subscription.

## Legacy Claude Code ownership and renewal

The existing Claude shared volume, ownership, provider/model and DirectSDK configuration remain unchanged. Legacy Claude Code is a separate source, not a Hermes-owned account; no broker reconnect/remove controls are offered for it.

The pool entrypoint now uses the same owning Claude app `ConnectionReader` and `server.renew_if_expired` policy as the prior entrypoint. Only the official Claude Code CLI in that app can renew its own login. Existing `WIZARD_CLAUDE_AUTO_RENEW=0` disables this behavior. This is separate from the default-off Hermes account-change switch: it preserves the existing app's declared policy, not a new sign-in/migration mechanism.

On an expired reading only, at most one noninteractive `run_test` (one Haiku turn, no tools, no session persistence, 120-second timeout, stdin closed) runs at a time in a background daemon thread. GET returns immediately with `renewing` while the CLI runs. A fresh read after completion reports connected or expired truthfully. A 600-second cooldown starts after completion, including challenge/failure/timeout; polling during cooldown does not extend it. No automatic login flow, token refresh implementation, cron, retry loop, credential copy or provider-wide auth action is added. A future deployed renewal can consume the already-declared single Haiku test turn; tests mock the CLI and make no real calls/spend. Errors retain `expired` and a reconnect reason, not generic provider-unavailable; service projection drops any old usage when expired.

Both packaged pool entrypoints preserve main's `wizard.ai-connection/2` discovery, models and `/api/infer` handler, including Claude's warm spare. Only ready/connected accounts imply aggregate connected status. Releases use fresh tags above main: ChatGPT 0.2.3 and Claude 0.2.4, then Claude 0.2.5 (the publish job now refuses an existing tag; 0.2.4 was re-pushed once by a later main build, so release pins use digests). The preceding ChatGPT 0.2.2 / Claude 0.2.3 publication exposed a BuildKit directory-permission defect; do not use those tags. They remain immutable.

## Verification and release boundary

Local tests use synthetic inventories, loopback HTTP, fake CLI subprocesses and browser fixtures. Real provider authorization, MFA, quota, and refresh success are not claimed. Current exact test results and candidate SHAs are recorded on the linked PRs.

The reconciliation PR supersedes the original review-only candidate: the owner authorized its merge and the resulting CI image publication, but not deployment or changes to the owner's live box. No production state/auth was changed. Before a future authorized deployment, preserve volumes and configure the authenticated dashboard bridge and app passwords through the existing secret/config channel. Keep account changes off until the owning box has been checked. Actual enrollment and renewal verification require separately authorized owner-supervised execution.
