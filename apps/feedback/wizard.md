---
wizard: 0.2
id: feedback
name: Feedback
type: service
category: app
version: 0.3.2
summary: Report a bug or ask for something new, and follow your own feedback in plain words.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizardos-feedback
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides:
- feedback
system: false
uses: []
needs: []
health: /healthz
switches: /api/switches
---

# Feedback

One friendly screen for non-technical people: a warm welcome ("Tell us what's broken or what you'd love. We'll keep you
posted here.") with a big **Report or request** button (two steps: pick one of two large cards, Something's broken /
I'd like something new, then one text box and optional screenshots), a clear thank-you card after sending, and **Your
feedback**, newest first: kind icon, title, a status pill coloured by kit tokens, four progress dots and "Sent 2 hours
ago". Tap a row for the full text, a vertical timeline with the date each step was reached (Received → Being built →
Being tested → Done; from label events when signed in) and words from people on the team (builder and bot accounts are
skipped). No repo names, labels or numbers are shown.

## Sending
- **Signed in with GitHub, member of humanitylabs-org**: filed exactly like the WizardOS Tracker reporter, in
  `humanitylabs-org/wizard-os` with labels `triage` + `bug`/`feature`, as the person. The builder moves it on.
  History is `org:humanitylabs-org author:<login> is:issue` (60 s cache), so Tracker-filed items show too.
- **Signed in, not on the team** (or membership unknown): sends through the relay whenever a relay address is set
  (`FEEDBACK_RELAY_URL` env or `relay_url` in `DATA_DIR/policy.json`), passing `gh_token`.
- **Not signed in**: one-tap send through the relay when the address is set *and* the app switch `anonymous` is on
  (off by default). Under Send a soft line offers "Sign in with GitHub to follow it from any device and see replies
  from the team" (starts the same device-flow sign-in; never blocks sending). After sending, a thank-you card: "Someone on the
  team will look at it soon. You can follow it below." The relay decides who goes straight to the builder and who waits for a person
  ("Waiting for the team to look at it").
- Otherwise Send is off with the reason ("Sign in with GitHub to send feedback"; non-members without a relay:
  "Feedback from outside the team opens soon"). `route()` in app/server.py is the one decision (tests).
- Relay-sent items are kept on this box in `DATA_DIR/sent.json` (id, kind, title, created, receipt); signed out, the
  list says "Saved on this Wizard. Sign in with GitHub to see replies." Relay screenshots: ≤3, ≤2 MB each (bigger ones
  are shrunk to JPEG in the browser). Relay down/5xx/no answer: "Couldn't send right now. Your words are saved; try
  again in a minute." (form and screenshots kept); 429: "That's a lot of reports in a short time. Try again in a few
  minutes."

## Relay contract (client side; fixed)
- `POST {relay}/v1/report` `{kind, text, wizard_version?, device?, gh_token?, screenshots? (≤3, ≤2 MB, {type, data base64})}`
  → `{receipt, status_key, line}`. Signed-in non-members pass `gh_token`.
- `GET {relay}/v1/status?receipt=A,B` (≤50) → `{results: {receipt: {status_key, line, title, kind, updated, done_at,
  closed_at}}}`; `closed_at` (and `done_at`) are set for every closed item, declined ones included.
- status_keys: `waiting_review, received, queued, building, checking, ready, done, not_planned`; `not_found` (a fresh
  report, ~1 min) shows as "Got it — the team is sorting it". Errors: JSON `{error, message}`; 429 on rate limit.

## Status mapping
`status_of()` / `keyed()` in app/server.py are the one mapping (tests: `python3 -m unittest discover -s tests`), in plain
words: closed completed → "Done ✓ · 11 Nov"; closed not planned / duplicate, or a reviewer's `rejected` label → "Declined
by the team · 11 Nov, 9:52" (closed_at in local time; year only when not this year) and, in the detail, "The team looked
at this and decided not to go ahead with it." plus the team's closing comment when a person left one; `needs-review` →
Waiting for the team to look at it; `ready-to-test` → Almost there — the team is trying it out; `ai-review` → Being
tested; `building` → Being built now; `triage` → Got it — the team is sorting it; no stage label → Coming up — in line to
be built. Rows also carry `status_base`, `status_at`, `status_show` so the screen redraws the date in the viewer's own
time zone; the view passes `?tz=` so agents (MCP) read the same local times (`DATA_DIR/timezone.json`;
`FEEDBACK_TIMEZONE` overrides).

The GitHub token stays on this box (`DATA_DIR/private/account.json`, 0600); it is never returned to the view or MCP.
Appearance: shared kit only ([style guide](https://github.com/humanitylabs-org/wizard-os/blob/main/style/APP-DESIGN-RULES.md)).

## Changelog
- **0.3.2**: Works straight from the Store: a fresh install reaches the team's relay with no setup, so anyone can send feedback.
- **0.3.1**: Calmer page: the welcome card is gone — just the title and one **Report or request** button; the list is flat
  rows with thin dividers (no cards), smaller status pills and progress dots. Filter chips **All · Open · Done · Declined**
  with counts (plus **Bugs · Ideas** when they fit on one line), remembered on this device; one plain line when a filter
  is empty. When the team declines something with a reason, the detail shows **From the team: “…”** under the
  explanation (relay `/v1/status` `team_note`; signed in: the relay's reason comment or the Tracker's Drop / Not a bug
  *Why*). When the team approves it as the other kind (an idea sent as a bug), the row follows the new kind.
- **0.3.0**: Friendly for everyone: "Not planned" is now "Declined by the team · <day, time>" with a calm explanation and
  the team's closing words; every status in plain sentences with dates; warm welcome, big button, kind cards with icons,
  status pills with progress dots, relative times, a gentle empty state, a thank-you moment after sending and a dated
  timeline in the detail. Relay /v1/status returns `closed_at`.
- **0.2.1**: Megaphone icon.
- **0.2.0**: Send without signing in through the relay (switch `anonymous`, default off) with a soft GitHub sign-in
  offer; signed-in non-members use the relay whenever it is set; plain relay-down and rate-limit messages that keep the
  form; relay screenshots capped at 3 × 2 MB (shrunk in the browser); "Saved on this Wizard" note on the signed-out list.
- **0.1.0**: Report or request + My feedback with plain status; GitHub sign-in path, relay path behind switch `anonymous`.
