---
name: wizard-search
description: Search the web and images through the installed Search service.
---
Read /api/config first. Fresh installs search for free through the bundled SearXNG sidecar. AI overviews are optional: the owner turns them on with the Tinfoil app from the Search start screen (GET /api/overview-provider shows the state). If state is setup_required, read SETUP.md and setup.json from this
package; configure only the owner's approved providers. Never ask for keys in chat or embed
keys in source. MCP POST /mcp offers search_status, search_web, search_images, search_overview.
Each search takes {"q":"..."}. tools/call returns JSON in content[0].text and isError.
The same operations are GET /api/web?q=, /api/images?q=, /api/overview?q=.
Paths are relative to the installed app base; the legacy standalone base is /wizard-search.
Provider searches can consume credits. Cite returned URLs, do not invent results or treat
setup_required/provider failure as zero matches. Configuration booleans do not prove reachability.
No history is persisted. Image URLs/IDs are ephemeral; rerun expired image searches.
