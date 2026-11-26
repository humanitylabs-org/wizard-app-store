---
name: movies
description: Use when reading or changing the owner's Movies watch queue.
---
# Movies agent skill

Use this app's `/mcp` JSON-RPC endpoint (or the documented `/api`), never files in its container.
For exact-title/year resolution, enrichment, request lifecycle and safe maintenance, follow
[`references/card-workflow.md`](references/card-workflow.md). The app id is `movies`;
`cinequeue_*` method names remain compatibility contracts, not app IDs.
- `cinequeue_list`: queue in order (`view` queue|watched|archived|all, optional `search`, `limit`).
- `cinequeue_get`: one card with queue position and watch history.
- `cinequeue_add`: `text` ("Stalker 1979, Heat") or `title`+`year`; new titles go to the top.
  Already in the list? Never duplicate it or leave it in place: queued → `cinequeue_bump`; watched → `cinequeue_watch_again` (history kept);
  archived → `cinequeue_archive` (archived false) then `cinequeue_bump`. Fill missing card fields and tell the
  owner it was already there and is now first. `cinequeue_add` does this itself and returns it in `bumped`.
- `cinequeue_update`: enrich a card (poster, description, genres, directors, cast, trailer_url,
  imdb_id/imdb_url, runtime_minutes, notes, featured_episodes, letterboxd_url/slug, media_type).
  Queue order and watch history are never touched by it.
- `cinequeue_bump`: move to the top. `cinequeue_mark_watched` (`watched_on` YYYY-MM-DD optional).
- `cinequeue_watch_again`: requeue a watched title, keeping history. `cinequeue_history`: newest first.
- `cinequeue_archive`: hide/restore; nothing is deleted.
- `cinequeue_request` / `cinequeue_requests` / `cinequeue_request_update`: the "find and add"
  request log. When you are handed a request, mark it `processing`, resolve the exact title (when
  ambiguous, mark `blocked` with `detail` = one short question, no URLs, and `choices` = 2-6 short
  tappable answers; the owner's tap comes back to you as a new run), add + enrich, verify with
  `cinequeue_get`, then mark `completed`. Completed requests are hidden in the app.

Ratings: only set `rating`, `rating_count`, `rating_source: imdb` from IMDb's official
`title.ratings.tsv.gz`; never relabel another site's score. Keep synopses clean; human notes go in
`notes`, highlighted episodes in `featured_episodes` ({title, season, episode, runtime_minutes}).
Agent requests and where-to-watch are optional operator integrations; report `sent:false` or a
disabled region honestly instead of claiming availability. No live agent submissions in QA.
