# DeFleur Video (Testing)

Testing release of James DeFleur's DeFleur Video workflow, with his original helper scripts bundled. Hermes makes the editorial decisions; this app runs the media steps and returns evidence. It makes no LLM or paid calls.

**Connect Hermes once:** `hermes mcp add defleur-video --url http://<server>:8787/mcp` (or `http://defleur-video:8787/mcp` from inside Runtipi), restart Hermes, then just ask it to edit a video. The app describes its own workflow through MCP tools: upload link, transcript and proposed cuts for your approval, the edited audio, then the finished 1080×1920 captioned vertical video and a report.

**Install the Transcriber app first.** This app sends audio to it for speech-to-text at `http://transcriber:8000`; change that in the settings if yours is elsewhere.

**Works now (audio/edit half):** upload an MP4/MOV (up to 512 MiB / 5 min) with a one-time link or the small `/upload` page. HEVC or variable-frame-rate phone video is converted to H.264; probe it and decode lossless audio; transcribe with word timings (via the Transcriber); align words locally (stable-ts); cut sample-exact audio from your edit list; get waveform and spectrogram evidence for every cut edge; run the dialogue audio gate. The older 9:16 preview with cuts and captions still works.

**Finished video (new in 0.5):** after the cut, the app finds the speaker's face (local OpenCV YuNet model) and sets one fixed 9:16 crop per setup that keeps the face clear of the captions. It burns in captions from the edited audio's word timings with James' `caption_layer.py`, encodes a 1080×1920 H.264/AAC MP4 with his `encode.py`, fully decodes it, checks the crop and captions in the decoded pixels, re-transcribes the final audio, and runs his delivery audio gate.

**Not built yet:** motion graphics (James' HTML/SVG/GSAP layer) and B-roll/fullscreen inserts. The final video is live footage plus captions. See the [parity map](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/WORKFLOW-PARITY.md).

**Access:** no token is required, so anyone who can reach the port can use the API. Keep the server private (e.g. Tailscale only). Optionally set `VIDEO_API_TOKEN` (32+ characters) to require a bearer token.

[Hermes operator guide](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/HERMES.md) · [API details](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/README.md)
