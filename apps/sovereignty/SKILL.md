---
name: sovereignty
description: Use when the owner asks how sovereign or self-hosted his setup is, or to update his sovereignty checklist.
version: 0.2.1
author: Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [sovereignty, self-hosting, checklist]
    related_skills: []
---
# Sovereignty checklist

The app rates each area of the owner's digital life on a 4-rung ladder (1 = rented from a big company or through a middleman, 4 = runs on his own box; 0 = not set up). `sovereignty_list` returns every area, its rungs, level, `via` (what he uses now), `evidence`, `next` step and the overall score.

To refresh it, check the live source for each area first (the owning app's status tool: Google for mail/calendar and how it connects, Claude/ChatGPT/Tinfoil for AI, Photos, Backup, Messenger, SimpleFIN/Monarch, Search, Contacts; `tailscale status` for the network), then call `sovereignty_set` with `id`, `level`, `via`, `evidence` (what you checked) and the one `next` step. Never rate from memory or old chats. Keep words plain; no app ids or jargon in `via` or `next`.

Areas can be added with `id`, `name`, `group` and 4 `rungs` (lowest first), or removed with `sovereignty_remove`.
