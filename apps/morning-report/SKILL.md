---
name: morning-report
description: Use when the owner asks about their morning report or briefing archive.
version: 0.1.0
author: Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [morning-report, briefing, reports]
    related_skills: []
---
# Morning Report

Read-only reader for the owner's dated morning reports. `reports_list` returns dates newest first with which formats exist; `report_read` returns one report's Markdown (omit `date` for the latest). The app never writes or generates reports; the owner's scheduled briefing job does that. Quote report text literally and report the exact app error if a call fails.
