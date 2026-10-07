# DeFleur Video + Hermes: connect once

DeFleur Video serves an MCP endpoint at `/mcp` on its port (8787). Hermes reads the tool descriptions and follows James DeFleur's workflow by itself, so you don't need a long prompt.

## 1. Install
Install **Transcriber** and **Browser** first, then **DeFleur Video**, from the Wizard App Store on the same Runtipi server. The Browser is only needed for motion graphics; plain captioned edits work without it. `capabilities` tells Hermes (and you) the exact fix if either is missing.

## 2. Connect Hermes (once)
If Hermes runs on another machine in your Tailscale network:

```sh
hermes mcp add defleur-video --url http://<tailscale-ip-of-the-server>:8787/mcp
```

If Hermes runs as an app on the same Runtipi server (shared Runtipi network):

```sh
hermes mcp add defleur-video --url http://defleur-video:8787/mcp
```

When asked "Does this server require authentication?", answer **n**, unless you set `VIDEO_API_TOKEN`; then answer **y** and paste the token. Next, restart Hermes (or run `/reload-mcp` in an open session). To check the connection, run `hermes mcp test defleur-video`; it should list 9 tools.

## 3. Just ask
> "Edit this video into a vertical short: cut the ums and long pauses, frame me, add captions, and add one or two motion graphics that explain the key idea."

What Hermes then does:
- Calls `workflow_guide` and `capabilities`.
- Gives you an upload link: a one-time curl command, or the page at `http://<server>:8787/upload`.
- Transcribes and aligns the speech.
- **Shows you the proposed cut list for approval.**
- After you approve, applies the cuts and reports the seconds removed, any words lost or added, and the dialogue-gate result, with download links for the edited audio and a 9:16 preview.
- Then renders the finished short with `render_final`: a 1080×1920 H.264/AAC MP4 with the speaker framed by a fixed crop and burned-in captions, plus James' delivery gate. It reports the resolution, duration, crop result, caption count, gate result, any words lost, and the download link.

## Tools
| Tool | Use |
|---|---|
| `workflow_guide` | What the app does, the order of steps, James' motion contract (`motion_contract`) and limits |
| `capabilities` | Whether the Transcriber (with its model) and the Browser are reachable, with the exact fix if not; host RAM, free disk and per-job estimates |
| `create_upload` | One-time upload URL (30 min) plus a curl command; video bytes never go through MCP |
| `start_edit(project_id, language?)` | Background run: source audio, ASR, preflight, alignment. Returns the transcript, word timings, filler/pause/repeat candidates, proposed cuts and James' editorial rules |
| `apply_cuts(project_id, segments)` | Background run: PCM assembly, cut audit, acoustic scan, re-ASR of the edit, dialogue gate. Reports the results and download URLs |
| `preview_framing(project_id, framing?)` | Optional: fixed crop per setup with face-audit evidence images; choose which person each kept segment frames (`targets`) or force new setups (`new_setup_at`) |
| `submit_motion(project_id, files, plan, replace?)` | Optional motion graphics: Hermes' HTML/SVG/GSAP composition and James' visual plan (beats, caption_suppress, inserts) |
| `create_asset_upload(project_id, path)` | One-time upload URL for a big asset, e.g. a B-roll clip for a fullscreen insert |
| `capture_motion(project_id, 'smoke'\|'proof', framing?)` | James' capture.cjs through the Browser app; returns frame images and a contact sheet to look at; proof also runs his reverse-seek determinism check |
| `render_final(project_id, options?)` | Background run: face audit + fixed crops, full motion capture if `{'motion': true}` (after a passing proof), burned captions (suppressed only where declared), James' 1080×1920 encode, decode and pixel checks, final re-ASR and James' delivery gate |
| `get_status(id)` | Waits up to ~55 s per call; Hermes keeps calling it until the run is `done` |
| `list_projects`, `delete_project` | Housekeeping |

HEVC or variable-frame-rate phone video is converted to H.264 at a constant frame rate on upload. The original's SHA-256 is kept in the project's provenance.

## Honest limits
- Motion graphics are authored by Hermes. The app verifies the mechanics (determinism, motion only inside planned windows, captions suppressed only where declared, no network) but not whether a beat explains well; watch it on a phone.
- Crops are fixed per setup, never animated (James' rule). Limits: 20-minute / 8 GiB uploads up to 4K (edited at 1080p), finished videos up to 6 minutes.
- The face audit samples frames (about 2 per second) with a local detector. A face it misses isn't audited, and a video with no detectable face gets a centered crop that is flagged in the report.
- The final-audio window notes for the delivery gate are written automatically from measurements and the final transcript. Always watch the final video on a phone before posting.
- `apply_cuts` writes the edge and window review notes for the gate automatically from measurements. The gate therefore proves that the evidence is complete and its hashes match. It does not prove anyone listened, so always listen to the edit.
- ASR can miss fillers. A long pause candidate with sound in it is probably an untranscribed "um".

## Without MCP
The plain HTTP API and `client.py` (one command per stage, with hand-written reviews) still work unchanged; see [README.md](README.md) and [EDITING.md](EDITING.md).
