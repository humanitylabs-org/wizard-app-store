---
wizard: 0.2
id: hermes-agent
name: Hermes Agent
type: agent
category: agent
version: v2026.9.24-wizard2
summary: The self-improving AI agent by Nous Research, with the optional Claude app sign-in share.
license: MIT
source: https://github.com/humanitylabs-org/wizard-app-store
icon: metadata/logo.jpg
runtime:
  kind: runtipi
  config: config.json
  compose: docker-compose.yml
skill: SKILL.md
view:
  path: /
  port: 9119
provides: [agent]
mounts:
- app: wizard-claude
  share: claude-login
  path: /claude
---

# Hermes Agent (legacy store recipe)

This manifest adds the Wizard OS #79/#80 share contract to the existing store app. The Claude app owns `data/claude`; App Manager mounts its `claude-login` share at `/claude` only while the owner grants it. The official Claude Code client uses the entire folder, including its refresh lock. The recipe never hard-codes a provider host path or a shared named volume.

The App Manager storage compiler reads the installed app's `wizard.md` alongside its `config.json` and compose file. Stock Runtipi alone ignores `mounts:`; use the matching App Manager share-grant implementation. Revoke removes the mount on restart; it does not erase the provider's files.

This is not a newly published standalone index app. It preserves the upstream image/version and dashboard unchanged. Its pre-existing version has a `v` prefix and this legacy image has no MCP front, so the full standalone `wizard.md` checker reports those two compatibility gaps. Do not invent an MCP endpoint or change the image merely to hide them. Storage rule 15 must pass. See `metadata/description.md` for setup and migration.
