---
name: feedback
description: Use when the owner wants to report a bug, ask for a feature, or check his feedback.
version: 0.3.2
author: Humanity Labs, Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [feedback, bugs, requests]
    related_skills: []
---
# Feedback

The Feedback app files the owner's bug reports and requests for WizardOS and shows how each is doing, in plain words.

- `feedback_send(kind, text)`: kind `bug` (something's broken) or `feature` (something new; `idea` also works). Pass
  the owner's own words; the first sentence becomes the title. It is filed as the owner's GitHub account, or, when the owner is not signed in or not
  on the team, through the Wizard relay, where a person on the team reviews it first. Confirm
  with `feedback_list`; never claim it was sent if the tool returned an error.
- `feedback_list()`: the owner's own feedback, newest first: `id`, `title`, `kind` (bug/idea), `status` (one plain line,
  e.g. "Coming up — in line to be built", "Done ✓ · 10 Nov", "Declined by the team · 11 Nov, 9:52"). Read it to the
  owner as is.
- `feedback_get(id)`: one item: full text, a dated timeline in `steps` (Received → Being built → Being tested → Done),
  `note` + `team_note` when the team declined it (`team_note.text` is the reason the reviewer wrote — read it as "From the team: …"; the kind can change when the team approves it as the other kind), and `comments` from people on the team.

Never ask the owner for a GitHub token or password. If a tool says to sign in, tell the owner: open **Feedback** and tap
**Sign in with GitHub**. If it says feedback from outside the team opens soon, say exactly that. Do not mention repo
names, labels or PR numbers to the owner. Never run wam or docker to reach this app; use the tools above.
