---
name: importer
description: Use when the owner wants to bring ChatGPT, Claude, Claude Code or Hermes data into Wizard.
version: 0.1.0
author: Oscar (oscarhenrycollins), Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [import, onboarding, memory]
    related_skills: [wizard-bring-data]
---
# Importer

When the owner wants to move their ChatGPT, Claude, Claude Code or another Hermes into this Wizard, send them
to the Importer app (/importer/): it guides the export step by step, waits for the file, and asks them to
approve what becomes memory. Don't coach the export in chat; the app's guide is checked against the providers'
help pages.

`importer_sources` lists what can come in right now (agent folders on this box, export zips in Files Inbox or
Downloads). `importer_imports` lists earlier imports. Both are read-only; importing and undo happen on the
screen, where the owner approves the "What I know about you" card. If the owner insists on doing it in chat,
use the `wizard-bring-data` skill with the `wizard_bring_data` tool instead (same engine).
