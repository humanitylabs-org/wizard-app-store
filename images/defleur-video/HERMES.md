# DeFleur Video + Hermes: connect once

DeFleur Video serves an MCP endpoint at `/mcp` on its port (8787). Hermes reads the tool descriptions and follows James DeFleur's workflow by itself, so you don't need a long prompt.

## 1. Install
Install **Transcriber** first, then **DeFleur Video**, from the Wizard App Store on the same Runtipi server.

## 2. Connect Hermes (once)
If Hermes runs on another machine in your Tailscale network:

```sh
hermes mcp add defleur-video --url http://<tailscale-ip-of-the-server>:8787/mcp
```

If Hermes runs as an app on the same Runtipi server (shared Runtipi network):

```sh
hermes mcp add defleur-video --url http://defleur-video:8787/mcp
```

When asked "Does this server require authentication?", answer **n**, unless you set `VIDEO_API_TOKEN`; then answer **y** and paste the token. Next, restart Hermes (or run `/reload-mcp` in an open session). To check the connection, run `hermes mcp test defleur-video`; it should list 8 tools.

## 3. Just ask
> "Edit this video: cut the ums and long pauses."

What Hermes then does:
- Calls `workflow_guide` and `capabilities`.
- Gives you an upload link: a one-time curl command, or the page at `http://<server>:8787/upload`.
- Transcribes and aligns the speech.
- **Shows you the proposed cut list for approval.**
- After you approve, applies the cuts and reports the seconds removed, any words lost or added, and the dialogue-gate result, with download links for the edited audio and a 9:16 preview.

## Tools
| Tool | Use |
|---|---|
| `workflow_guide` | What the app does, the order of steps, and what isn't built yet |
| `capabilities` | Whether the Transcriber is reachable and has its model, with the exact fix if not |
| `create_upload` | One-time upload URL (30 min) plus a curl command; video bytes never go through MCP |
| `start_edit(project_id, language?)` | Background run: source audio, ASR, preflight, alignment. Returns the transcript, word timings, filler/pause/repeat candidates, proposed cuts and James' editorial rules |
| `apply_cuts(project_id, segments)` | Background run: PCM assembly, cut audit, acoustic scan, re-ASR of the edit, dialogue gate. Reports the results and download URLs |
| `get_status(id)` | Waits up to ~55 s per call; Hermes keeps calling it until the run is `done` |
| `list_projects`, `delete_project` | Housekeeping |

HEVC or variable-frame-rate phone video is converted to H.264 at a constant frame rate on upload. The original's SHA-256 is kept in the project's provenance.

## Honest limits
- Face audit and 9:16 crop, burned captions, the final 1080×1920 encode, motion graphics and the delivery gate are **not built yet**.
- `apply_cuts` writes the edge and window review notes for the gate automatically from measurements. The gate therefore proves that the evidence is complete and its hashes match. It does not prove anyone listened, so always listen to the edit.
- ASR can miss fillers. A long pause candidate with sound in it is probably an untranscribed "um".

## Without MCP
The plain HTTP API and `client.py` (one command per stage, with hand-written reviews) still work unchanged; see [README.md](README.md) and [EDITING.md](EDITING.md).
