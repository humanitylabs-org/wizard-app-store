---
name: profiles
description: Use when the owner asks about his Wizard profile, friends, or sharing his build, skin or apps.
version: 0.1.0
author: Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [profiles, friends, sharing]
    related_skills: []
---
# Profiles

The owner's Wizard profile: his build (his version of the Wizard shell), his look (skin plus his own CSS touches) and his App Store apps. Each part is Private (default), Friends or Public. Identity is a Nostr ID (npub) the app keeps for this Wizard; friends are added by npub alone. Sharing goes through public Nostr relays (public parts signed, friends' parts NIP-44 encrypted per friend, requests NIP-59 gift-wrapped); nobody connects to the owner's Wizard. Changes share automatically, no Publish step. Trying on a build is friends-only.

- `profile_get` reads visibility, the published snapshot, friends and requests. `profile_preview` with `as: friend|public` shows exactly what others see.
- `profile_set_visibility` changes one part. Only when the owner asked. Sharing is a privacy decision; never widen it on your own.
- `friends_list` and `friend_profile` (friend id) read friends and what a friend shares.
- Backing up or restoring the Nostr identity happens only in the Profiles screen (Back up your identity, under the Nostr ID). Never ask for, read, print or move the key or the backup password yourself; point the owner there.
- Adding friends, choosing who sees what, wearing a look and trying on a build happen in the Profiles screen. Point the owner there instead of doing it for him. There is no Publish step: the screen shares changes by itself.

Rules the app enforces (don't work around them): an app is shared only if the Wizard App Index lists its public repo, so local and private apps never show; a build is shared only if its exact commit is public shell code and never with everyone; a friend's profile is checked on this box (signature, App Index, CSS) before it is shown.

## Setup: put Profiles on the Wizard's own address
Profiles reads the look, build and apps from the Wizard it runs in, so it must open on the shell's own address (`/profiles/`), not on a port of its own. If the screen says "Profiles can't see your Wizard yet":
1. Back up `~/.wizard-os/links.json`.
2. In its `links` list, set the `profiles` entry's `open` to `/profiles/` and add `"gateway_strip": true` (keep the other fields).
3. Run `wam links`, then check that `https://<box>:<shell port>/profiles/healthz` answers. Reload Profiles.
Trying on a friend's build also needs the box's try-on helper; without it the button says so, and everything else works.
