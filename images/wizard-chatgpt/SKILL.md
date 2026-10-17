---
name: wizard-chatgpt
description: Use when reading or managing chatgpt subscriptions on Wizard.
---
# Chatgpt subscriptions

Use `connection_status` or the box-only `GET /api/connection` for read-only status.
The `accounts` array carries independent quotas; top-level usage is not an aggregate.
The owner uses this app's Add subscription / Reconnect / Remove controls.
Never request authorization codes, passwords, or tokens in chat.
Hermes owns new subscription credentials; the app never receives their tokens.
Reconnect is a new sign-in and retains old grants for separately confirmed removal.
Removal targets the displayed exact grant ID, never an account's list position.
Same-account OpenAI sign-in can invalidate older grants and adds no quota.
Claude Code's existing login remains a labelled legacy source; it is not copied,
removed, or automatically migrated. Keep its existing shared volume and consumer configuration.
