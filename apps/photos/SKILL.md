---
name: photos
description: "Use when the owner asks about his photos, Google Photos, Takeout import, faces/people, or deleting photos."
version: 0.2.0
author: Oscar Henry Collins, Hermes Agent
license: AGPL-3.0-only
metadata:
  hermes:
    tags: [photos, immich, google-takeout, faces, backup]
    related_skills: [files]
---
# Photos (Immich)

The owner's own Google Photos replacement: unmodified Immich on his box, opened in Wizard at `?open=photos`. Tools come through the single Wizard MCP gateway as `photos_*`.

## Tools
- `photos_status`: start here. Immich up?, Photos' own account made (`immich.has_owner_account`, `sign_in.ready`)?, agent connected?, photo/video counts, background work (face detection/grouping, search indexing), import state, free disk, links (`links.mobile_server_url` is what the Immich phone app needs), and `next` = the owner's next step. Read `next` back to him in plain words.
- `photos_people`: face groups by name with photo counts (`include_unnamed` for unnamed groups). Faces appear only after the background work finishes; a big import takes hours to a day on CPU.
- `photos_search`: `query` = meaning search ("dog on the beach"); without it, filters (`person` name or id, `taken_after`/`taken_before` YYYY-MM-DD, `media_type`, `city`, `favorite`) with an exact `total_matching`.
- `photos_move_to_trash`: by `asset_ids` or by `person` and/or dates. Always twice: first call (no `confirmed`) returns the count and a sample. Tell the owner the exact number, get his explicit yes, then call with `confirmed=true, expected_count=<that number>`. Moves to Immich's trash (30 days by default); never permanent. It refuses an empty filter.
- `photos_restore_from_trash`: undo, by ids or `everything=true`.
- `photos_import_status` / `photos_import_start`: Google Takeout import (below). `photos_import_start` without `confirmed` only lists the files.

Permanent deletion is the owner's own act in Immich: Trash › Empty trash (or wait 30 days). Never claim a photo is gone for good after `photos_move_to_trash`.

## Monthly print review (only while the app switch print-review is on)
- `photos_print_review(month="YYYY-MM")` (default last month, read only): the photos the owner approved to print for that month and his note (`approved_by_owner: true`), or Photos' suggested shortlist when he has not saved one yet. The owner picks and saves in **Photos › Print review**.
- Never order, mail, buy or pay for prints, and never say a set was ordered: Photos has no way to do that. Printing is a separate step the owner takes himself; ask him first.

## No sign-in (Tailscale is the lock)
The owner never makes an account or types a password; never ask him for one or offer to "set up a login". On first start Photos creates Immich's one account itself (placeholder email `owner@photos.wizard`, random password kept only in the app's private state volume as `owner.json`; never read, print or share it), marks Immich's first-run tour done, and connects the agent with a narrow API key. Every visit from his tailnet arrives signed in: the Wizard screen (`?open=photos`), Immich full screen (`links.immich`) and the phone app. A different tailnet user than the owner, or a cross-site write from a web page, meets Immich's normal sign-in instead.

- Not ready yet (`sign_in.ready` false, `next` says setting up): Immich is still starting; check again in a minute. `sign_in.problem` names a real setup failure; report it as is.
- Phone backup: install **Immich** (Google Play / F-Droid / App Store), Tailscale on, server URL = `links.mobile_server_url` (his Tailscale address with port 8871) › **Next** › **Continue** (one button, no email/password form). Then Backup › choose albums (Camera) › turn on backup; optional Settings › Background backup. If an older app still shows email/password, any text works (e.g. `me@photos` / `x`).
- "Sign out" in Immich just returns to the library. Account settings › Devices lists the sessions; removing the phone's session makes the app show **Continue** again.

## Google Takeout (Photos only)
1. On a computer: takeout.google.com › **Deselect all** › tick only **Google Photos** (All photo albums included) › Next step.
2. Destination **Send download link via email**, Frequency **Export once**, File type **.zip**, File size **50 GB** › Create export. Google emails a link in hours to days.
3. Download every part (`takeout-…-001.zip`, `-002.zip`, …). Put all of them in **Files › Photos › Import** (upload in Files, or copy to `~/runtipi/media/Photos/Import/` on the box). Downloading straight on the box is fine too.
4. Wait until every part is there (parts share JSON across zips), then **Photos › Import from Google › Import now**, or `photos_import_start(confirmed=true)`.
5. Watch `photos_import_status`. Re-running is safe: immich-go skips what Immich already has (checksums). Options on the Import sheet: archived (on), partner-shared (on), albums (on), Google trash (off).
6. After it finishes and he has checked the library, the zips in Import can be deleted to free space (the photos now live in Photos/Library). Wiping Google is his own step; suggest he keeps the Takeout zips until he has checked.

immich-go v0.32.0 (AGPL-3.0, github.com/simulot/immich-go) is downloaded on the first import and checked against its pinned SHA-256; it runs inside the Photos front with Immich's jobs paused during upload.

## Where things are
- Originals and thumbnails: `~/runtipi/media/Photos/Library` (Immich-managed; don't rename or edit files there). Takeout drop folder: `~/runtipi/media/Photos/Import`.
- Database, its random password, Photos' own account (`owner.json`), the agent key and ML models: the app's Docker volumes `photos_wizardapps_photos-db`, `…_photos-secrets`, `…_photos-state`, `…_photos-model-cache` (kept across app updates; an uninstall that removes volumes deletes the database, not the photo files).
- Immich full screen: the app's own port (`links.immich`). The Wizard page at `/photos/` frames it and adds Import and Agent (phone steps and what the agent may do).

## Failure notes
- "still setting itself up" or 401: Photos remakes the agent's key by itself (on the next call or within 5 minutes); just retry. Never ask the owner to sign in.
- Import `failed`: read `log_tail`; common causes are a missing zip part or a full disk (`photos_status.disk`). Re-run after fixing.
- Immich not reachable for >5 min after install: check `docker ps --filter name=photos` health and `docker logs photos_wizardapps-photos-server-1`.
