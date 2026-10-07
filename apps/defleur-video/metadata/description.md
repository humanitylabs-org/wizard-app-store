# DeFleur Video (Testing)

Testing release of James DeFleur's DeFleur Video workflow, with his original helper scripts bundled. Hermes makes the editorial decisions; this app runs the media steps and returns evidence. It has no browser UI and makes no LLM or paid calls.

**Install the Transcriber app first.** This app sends audio to it for speech-to-text at `http://transcriber:8000`; change that in the settings if yours is elsewhere.

**Works now (audio/edit half):** upload an MP4 (up to 512 MiB / 5 min); probe it and decode lossless audio; transcribe with word timings (via the Transcriber); align words locally (stable-ts); cut sample-exact audio from your edit list; get waveform and spectrogram evidence for every cut edge; run the dialogue audio gate. The older 9:16 preview with cuts and captions still works.

**Not built yet:** face/crop audit, final captions, 1080×1920 encode, motion graphics and the delivery gate. See the [parity map](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/WORKFLOW-PARITY.md).

**Access:** no token is required, so anyone who can reach the port can use the API. Keep the server private (e.g. Tailscale only). Optionally set `VIDEO_API_TOKEN` (32+ characters) to require a bearer token.

[Hermes operator guide](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/HERMES.md) · [API details](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/README.md)
