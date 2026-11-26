---
wizard: 0.2
id: wizard-cloudflare
name: Cloudflare
type: external
category: system
version: 1.4.6
summary: "Sign in to Cloudflare once; your Wizard publishes sites, stores backups and manages domains."
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/wizard-cloudflare
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 18805
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 18805
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 18805
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [cloudflare-connection, website-publishing, backup-storage, domains]
system: true
uses: [notifications]
needs: []
health: /healthz
icon: icon.png
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Cloudflare

Sign in with Cloudflare once (or create a free account there). The app then shows a small card per account (websites, storage, domains) and nothing else: you ask your Wizard to publish a website, back up a folder from Files, find a domain or change DNS, and it does the work.

- Provides `cloudflare-connection` (contract `wizard.cloudflare-connection/1`) plus the jobs `website-publishing`, `backup-storage` and `domains`; several logins and accounts.
- Every change the Wizard prepares waits for one tap: a "Your Wizard wants to …" card with Approve / Decline in the app (plus a Notifications ping when that app is installed). The Wizard cannot approve its own changes.
- Possible changes: publish a Files folder as a `workers.dev` website, back up a Files folder to R2, create a bucket, upload an object, create or update DNS records, deploy a Worker. Nothing is deleted. Domains can be searched and priced, never bought.
- Opened inside the Wizard shell at `/wizard-cloudflare/`; the owner is the signed-in tailnet user named by Tailscale Serve (`WIZARD_OWNER_LOGINS`), plus exact Host/Origin checks and CSRF on every write. MCP is box-only.
- Files is mounted read-only. Tokens stay in this app's private volume.
