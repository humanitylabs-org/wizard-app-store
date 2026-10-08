# Wizard apps sync (Hermes Agent)

This is the one store-specific addition to the Hermes Agent app. Install Hermes Agent, then
install any Wizard app (for example DeFleur Video), and the first chat message works: "use the
DeFleur video editor to edit this video". No `hermes mcp add`, no SSH, no extra instructions.

It runs as one small second service (`wizard-apps`) in the Hermes Agent recipe and has two
separate parts:

| File | Role |
|---|---|
| `wizard_core.py` | **Discovery core.** Agent-agnostic and deterministic. Writes `apps.json`. |
| `hermes_adapter.py` | **Hermes adapter.** Applies `apps.json` to Hermes and renders the skill. |
| `bootstrap.py` | Loads both into the one sidecar process. |
| `test_wizard_apps.py` | Unit tests: byte-identical `apps.json` on re-runs, no config write when nothing changed, owner entries untouched. |

## Core: input/output contract (reuse it for another agent app)

`wizard_core.refresh(state_dir, repo, ref, now, refresh_s=3600, fetch=…, tcp=…, mcp=…)`

**Inputs**
- **Store app list.** About once an hour the core reads `apps/*/config.json` and
  `apps/*/docker-compose.yml` from the public store (`repo@ref`, default
  `humanitylabs-org/wizard-app-store@main`) through the GitHub contents API and raw URLs.
  - It keeps apps whose `wizard_type` is `service` or `external`. The port is the main service's
    `x-runtipi.internal_port`, or the container side of its `ports` entry.
  - An app serves MCP when its `config.json` sets `"wizard_mcp_path": "/mcp"` (validated by the
    store tests). A new MCP app needs only that field; no agent app needs an update.
  - The list is cached in `<state_dir>/store.json`. When the store can't be reached, the core uses
    that cache, or `BUILTIN_APPS` if it has never fetched successfully.
- **Probes on the Runtipi network.**
  - TCP connect to `<app-id>:<port>` (Runtipi gives every app its id as a DNS alias).
  - For MCP apps, an MCP `initialize` POST to the MCP URL. The session it opens is deleted again.

**Output.** `<state_dir>/apps.json`:

```json
{
  "apps": [
    {"description": "Service: …", "id": "defleur-video", "mcp_ready": true,
     "mcp_url": "http://defleur-video:8787/mcp", "name": "DeFleur Video (Testing)", "note": "",
     "type": "mcp", "url": "http://defleur-video:8787"}
  ],
  "version": 1
}
```

- `apps` holds only the reachable apps, sorted by `id`.
- `type` is `mcp` or `http`.
- `mcp_url` is `null` for `http` apps.
- `mcp_ready` is `false`, with a short `note`, when the MCP endpoint didn't answer (for example
  `needs a token`).

**Guarantees**
- **Deterministic.** The same store list and probe results give byte-identical `apps.json`,
  whatever the store order or time. Keys and apps are sorted. There are no timestamps or
  randomness in the output, and no LLM.
- **Write-only-on-change.** `apps.json` is atomically replaced only when its bytes change.
  `refresh` returns `(apps, changed)`.
- **Read-only towards the agent.** The core never touches any agent's files. Nothing outside
  `state_dir` is written.

**Writing an adapter for another agent:** call `refresh()` every cycle, then map `apps` onto that
agent's own config through its own CLI or API. Copy the adapter's ownership rules (below), which
the store expects of every adapter.

## Hermes adapter

Each cycle (every 30 seconds):

1. **MCP entries.** For each `mcp_ready` app it runs
   `hermes config set mcp_servers.<app-id> '{"url": <mcp_url>, "enabled": true}'` (all tools, no
   auth), so the tools appear as `mcp__<app_id>__*`. Hermes' running gateway connects new entries
   live (its MCP config reconcile chore), without a restart. When one of its own apps has been
   gone for 10 minutes, it runs `hermes config unset` for that entry. When the app comes back, the
   entry is re-added.
2. **Skill.** It renders `/opt/data/skills/wizard-apps/SKILL.md` from a fixed template.
   - MCP apps get one line ("tools connected; call `workflow_guide`/`capabilities` first"),
     because they describe themselves through their tools.
   - Detailed text is kept for apps without MCP (Transcriber, Secret Drop, Browser) and for files:
     chat attachments into upload URLs, and internal download links (fetch the file and send it as
     an attachment, or swap in the server's Tailscale address).
3. **Idempotent.** With an unchanged `apps.json` and `config.yaml` it makes no CLI call and writes
   no file.

**Ownership rules (it never edits the owner's settings)**
- Its own entries are recorded in `/opt/data/wizard-apps/hermes-state.json`. It changes an entry
  only while that entry is still exactly `{url, enabled: true}` as it wrote it. If the owner edits,
  disables or removes the entry, it is released for good.
- It skips an app when the name is already taken, or when the owner has connected the same host
  under another name.
- It only writes a skill file that carries its `managed-by: wizard-apps-sync` marker.
- Config writes go only through the Hermes CLI. That is Hermes' own atomic writer, which keeps
  comments, key order and every other setting. Hermes' config lock is per process, so before each
  write the adapter waits until `config.yaml` has gone a few seconds without changes. It writes
  only when an app appears or goes away.

**Turning it off.** Set **Connect Wizard apps** to off in the app's Runtipi settings
(`WIZARD_APPS_SYNC=false`). The adapter removes only its own entries and skill, then stays idle.

## Why this design

- **Same official image** (`nousresearch/hermes-agent`, same digest as the main service) with the
  entrypoint `python3 -c BOOTSTRAP CORE ADAPTER`. The sidecar gets the matching `hermes` CLI,
  Python and PyYAML, and it updates with every Hermes bump. There's no extra image to build,
  publish or trust, and the `hermes-agent` service itself stays vanilla. If the sidecar fails,
  Hermes keeps running.
- **Sources inline in the compose file**, because Runtipi installs only recipe files.
  `scripts/embed-wizard-apps-sync.py` copies the reviewed `.py` files into
  `apps/hermes-agent/docker-compose.yml`, and the store tests fail if they differ.
- **Hardened:**
  - uid 1000 (the owner of Hermes' files)
  - read-only root filesystem, all capabilities dropped, `no-new-privileges`
  - 512 MB memory
  - 1 MB × 2 log rotation, with log lines only when something changes

## Known gap

DeFleur Video builds upload and download links from the host Hermes used
(`http://defleur-video:8787/...`). Hermes can use them, but the owner's phone can't open them. The
skill covers this, as described above.

## Verification

- `python3 -m unittest discover -s sidecars/wizard-apps`: the unit tests, also run by
  `npm test`.
- `scripts/e2e-wizard-apps.py`: real containers with the real Runtipi 4.8.0 compose builder and
  permission step. It covers Hermes alone, DeFleur Video appearing, owner settings surviving, the
  app stopping and returning, Hermes restart and recreate, and the off switch.
