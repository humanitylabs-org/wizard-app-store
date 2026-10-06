# DeFleur Video (Testing)

Testing release of James/DeFleur's agent-operated video workflow. Hermes makes the editorial decisions; this app stores files, runs edit jobs and returns previews. No browser UI, no paid providers, no Hermes runtime dependency.

**Works now:** upload an MP4 (up to 512 MiB / 5 min), save edit decisions, render a 9:16 preview (up to 60 s) with cuts, burned captions and a fixed portrait crop, then download the preview and review artifacts.

**Not built yet:** transcription/alignment, audio lock, face tracking, motion graphics and final delivery. See the [parity map](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/WORKFLOW-PARITY.md).

**Access:** no token required. Anyone who can reach the port can use the API, so keep the server private (e.g. Tailscale only). Optionally set `VIDEO_API_TOKEN` (32+ characters) to require a bearer token.

[Hermes connection](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/HERMES.md) · [API details](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/README.md)
