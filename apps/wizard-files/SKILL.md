---
name: wizard-files
description: Browse and search files in the Wizard owner-files root.
---
Use the installed MCP tools `files_list` (relative folder) and `files_search` (name query).
HTTP: GET api/files?folder=, GET api/index?q=&type=, GET api/files/content?path=.
Read paths are relative, with no symlinks or hidden components. Search is bounded;
when truncated, browse folders. No legacy host indexes or private-agent stores exist here.
Upload only through the shared Wizard resumable transfer service: POST /wizard/v1/uploads
with destination:{folder}, PATCH bounded chunks with Upload-Offset, GET offset to resume,
POST /complete, then HEAD/read back through this app. Do not invent a whole-file cap.
An empty folder destination follows the system Inbox date convention, not a new taxonomy.
