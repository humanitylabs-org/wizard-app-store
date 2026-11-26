---
wizard: 0.2
id: wizard-health
name: Health
type: view
category: app
version: 0.19.0
summary: Your recovery, sleep and activity from your wearables, each in one plain sentence, every day as a square like a GitHub graph.
tags: [data]
license: GPL-3.0-only
icon: icon.png
source: https://github.com/oscarhenrycollins/wizard-health
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8826
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8826
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8826
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [health]
system: false
uses: [health-data]
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Health

A health tracker over the wearables you connect, in plain words, with one traffic light for everything: **green good, yellow okay, red needs attention** (grey = no data). Glance at it and read "green, green, green" or "green, yellow, yellow".

- **Recovery · how ready your body is**: Ready (67–100) green, So-so (34–66) yellow, Run down (0–33) red.
- **Sleep · did you get enough**: judged against what your body needed. 85% of your need or more is green (Enough), 70–85% yellow (A bit short), under 70% red (Short).
- **Activity · did it match your recovery**: effort is not good or bad by itself, so Health compares it with that day's recovery (WHOOP's guidance: Ready about 14–18 on the 0–21 scale, So-so about 10–14, Run down under 10). Inside the target, or resting on a run-down day, is green (Right amount); a little outside is yellow (A bit much / Room to push); well over is red (Too much for today). Doing less is never red.

Each gets one card for the selected day, filled with that day's colour: a big number, a word, one plain sentence and the few numbers behind it (heart rate variability, resting heart rate, blood oxygen and skin temperature; sleep stages; the day's target, calories, steps and workouts). Below it, **every day as a square**, like a GitHub contribution graph, with one shared legend. Tap a square to see that day everywhere (Back to today and Back return to today).

In a wide window all three sit in one row, Activity (the one to act on) half the width and Recovery and Sleep a quarter each; all three move together. In a narrow window (a phone) you see one at a time and pick Activity or Recovery & sleep in a bar at the bottom (it opens on Activity, which says how much more to do today), within reach of your thumb; the squares are big enough to tap, about the last three months fit the screen and older weeks scroll sideways.

A dot in the corner shows how fresh your sources are and opens them.

Health reads every connector app that fills the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`): WHOOP, Oura, Fitbit, Polar, Withings or any other, with no change to Health. Sources lists each one (connected, behind, or not set up with a **Set up** link to its own app). With two or more connected you pick the **main** source; each day uses its numbers, and anything it missed that day comes from another wearable with a small "from Oura" note. Activity targets follow each wearable's own scale. A wearable that gives no recovery score shows "No score from …", never a made-up one. Connecting happens in each connector's own app; Health never asks for a wearable's keys. It keeps its own copy of the days it has read, so the screen and your agent stay fast, and other apps (such as a morning report) can read the daily summary at `GET /api/summary`. The Morning Report reads its Health section from `GET /api/report` (shared report-section format), which says when you woke (`woke_at`, straight from your wearable) and whether last night is final yet (about 30 minutes after you wake), so the report can turn final as soon as you are up. Agents ask the same with `health_wake`.
