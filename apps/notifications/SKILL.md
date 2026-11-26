---
name: notifications
description: Use when the owner asks to be told when something happens or finishes, when a long job you started is done, or when something needs their attention. Send them a short notification with the Notifications app.
---

# Notifications

The Notifications app is the owner's own notification server on this box. What you send shows up on their phone (ntfy app) and in the Notifications web app.

## Tools

- `notify` — send one notification. `message` is required; add a short `title`. Use `priority: high` only when it needs them soon and `urgent` only for real problems. Add a `link` (https) when there is something to open. When it is about one installed app (a Sniper scan, a backup, a sale), pass that app's id as `app` (e.g. `app: sniper`): it is listed under that app and follows that app's own notification choice; leave it empty for your own news.
- `notifications_recent` — what was sent lately (default: last 24 hours). Check it before repeating yourself.
- `notifications_inbox` / `notifications_mark` — the owner's inbox with read, flagged and archived state; mark items only when they ask.

## Scheduled jobs

The app forwards the agent's scheduled-job (cron) results to the inbox by itself once its "Hermes scheduled jobs folder" setting points at the agent's cron folder (for example `/home/<user>/.hermes/cron`). Silent runs post nothing; an unchanged failure alerts once, then once a day; a changed error or a failure after a success alerts at once. Jobs named in "Jobs to keep quiet when they succeed" post only their failures. "Which app each job is about" (`job=app` pairs) lists a job's results under that app instead of under the agent. Don't `notify` again for a job result the relay already posted.

## When to notify

- They asked: "tell me when…", "let me know if…", "ping me when it's done".
- A long job you started for them finished or failed, and they are probably not watching the chat.
- Something needs their decision or action.

## When not to

- Don't notify for every small step, or for things you are already telling them in the chat they are looking at.
- Never put passwords, keys, codes or other secrets in a notification.
- One notification per event. If nothing changed, don't send another.

## Style

Plain and short: what happened and what (if anything) they need to do. For example: title "Video ready", message "Your edit of beach.mp4 is in Files → Videos/Edited."
