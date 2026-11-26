---
name: wizard-notes
description: Use when taking or finding notes in the owner's private Markdown vault.
---
# Wizard Notes
Use the installed Notes MCP endpoint from the Wizard app registry. One Markdown vault backs API and tools.

- `notes_tree {}` lists folders and notes. `notes_search {q:"topic"}` ranks titles before body matches; empty query returns recent notes.
- `notes_read {path:"Inbox/Idea.md"}` returns exact content and `rev`.
- Read before writing. `notes_write {path,content,rev}` replaces the note only if the revision still matches. `append:true` appends content but still requires the current revision. On conflict, reread and reconcile; never retry a stale revision or discard either person's text.
- Create with `notes_write {path,content,create:true}`; parent must exist. Use `notes_mkdir {path:"Work"}` to create one folder at a time.
- `notes_move {from,to}` renames or moves without overwriting. Link text is not automatically rewritten; prefer stable note titles.
- Never call `notes_delete {path}` unless the owner asks to delete it. Deletion moves files/folders into `.trash`, not permanent removal. Returned `trash_id` supports `POST /api/restore {trash_id}`; original paths remain in `.trash/<id>/original.json`.
- Paths are visible vault-relative names, notes end in `.md`. No absolute paths, dot segments, hidden names or symlinks.
- `[[Title]]` and `[[Title|alias]]` resolve case-insensitively, preferring the same folder, then exact vault path, then stable path order. Duplicate basenames are allowed but ambiguous; qualify them with folders.
- Today uses the Asia/Bangkok calendar day and opens `Daily/YYYY-MM-DD.md`.

The Wizard gateway owns authorization and exposes tools only to agents the owner ticks. This app is private by default. Notes are plain Markdown files. By default they live in the app-owned `/data/vault` mount. The owner may instead point Notes at a folder that already exists on the host (`NOTES_VAULT_DIR`), such as an Obsidian vault synced to his other devices, so other apps and devices can change notes between your calls. Always read before writing, keep the returned `rev`, and use these tools, not direct file access, even when you can see the folder on disk. Do not bypass the gateway or access another agent's private files. Uninstall retains the data folder and never touches an owner-chosen folder.
