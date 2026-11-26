---
name: files
description: Use when the owner mentions their Files, a folder, or a document/video they saved, or asks you to save something for them. List, find, read and save files in the shared Files folder through the Files app's tools.
---

# Files

Files is the owner's own folder on this box. The Files app shows it, and every other app (video editor, transcriber...) reads from and writes to the same folder. Paths are always relative to it: `Videos/clip.mp4`, `Documents/notes.md`.

## Tools

- `files_list` — what's in a folder (empty path = the top). Start here when the owner says "my files".
- `files_find` — find by part of a name, e.g. "invoice" or ".mp4". Use it when the owner names a file loosely.
- `files_read` — the text of a text file (notes, markdown, CSV, JSON, subtitles). Videos, PDFs and other binary files are only described: pass their path to the app that handles them.
- `files_write` — save a text file so the owner can open it in the Files app. It won't replace an existing file unless you set `overwrite`; ask first before replacing something the owner made.
- `files_new_folder` — make a folder.

## Rules

- There is no delete tool on purpose. If the owner wants something removed, tell them to do it in the Files app.
- Hidden (dot) files and anything outside the Files folder are off limits.
- Put new things where the owner expects them: documents in `Documents/`, videos in `Videos/`, edited videos in `Videos/Edited/`.
- After saving, tell the owner the exact path so they can find it in the Files app.
