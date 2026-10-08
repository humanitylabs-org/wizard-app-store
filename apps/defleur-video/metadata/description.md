# DeFleur Video (Testing)

Testing release of James DeFleur's DeFleur Video workflow, with his original helper scripts bundled. Hermes makes the editorial decisions; this app runs the media steps and returns evidence. It makes no LLM or paid calls.

**Connect Hermes:** Hermes Agent from the Wizard App Store on the same server connects it automatically within a minute. For another Hermes, run `hermes mcp add defleur-video --url http://<server>:8787/mcp` and restart it. Then just ask it to edit a video. The app describes its own workflow through MCP tools: upload link, transcript and proposed cuts for your approval, the edited audio, then the finished 1080×1920 captioned vertical video and a report.

**Install the Transcriber and Browser apps first.** Speech-to-text goes to the Transcriber at `http://transcriber:8000`; motion graphics are captured in the shared Browser app at `http://browser:9222` (only needed for motion). Change either address in the settings if yours is elsewhere. Hermes' `capabilities` check tells you exactly what is missing.

**Edit:** upload an MP4/MOV (up to 20 minutes and 8 GiB, up to 4K; 4K, HEVC and variable-frame-rate video is converted to 1080p H.264 for editing, with the original's hash kept) with a one-time link or the small `/upload` page. Transcribe with word timings (via the Transcriber), align words locally, cut sample-exact audio from the cut list you approve, with waveform/spectrogram evidence per edge and James' dialogue gate.

**Finished video:** one fixed 9:16 crop per camera setup from a local face audit (more than one setup per video; for two-person shots Hermes can choose who each segment frames), optional motion graphics that Hermes writes as a small HTML/SVG/GSAP page following James' motion contract, optional fullscreen B-roll inserts, captions burned in with James' `caption_layer.py` (hidden only where a graphic says the same words), his 1080×1920 `encode.py`, full decode and pixel checks, final re-transcription and his delivery gate. Videos up to 6 minutes long.

**Honest limits:** the app checks mechanics (determinism, motion only where planned, no lost words), not taste; watch the result on a phone. Crops never pan (James' rule). Pauses are cut only where the audio measures silent; sound the transcript doesn't explain is listed for you to review, never cut automatically. Resources: up to 10 GB memory, no CPU cap (a 2-minute video with motion graphics peaked at 3 GB and took about 19 minutes end to end on a 4-core server, 16 of them rendering; without motion graphics it is much faster); `capabilities` reports host RAM, free disk and per-job estimates, and jobs stop early with a clear message instead of running out of memory. See the [parity map](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/WORKFLOW-PARITY.md).

**Access:** no token is required, so anyone who can reach the port can use the API. Keep the server private (e.g. Tailscale only). Optionally set `VIDEO_API_TOKEN` (32+ characters) to require a bearer token.

[Hermes operator guide](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/HERMES.md) · [API details](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/README.md)
