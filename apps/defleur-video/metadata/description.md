# DeFleur Video — original-workflow port (incomplete; disabled)

The intended app is James/DeFleur's agent-operated workflow, not a separately showcased preview demo. Hermes makes editorial decisions; a standalone authenticated service owns files, jobs and bounded execution. It has no Hermes runtime dependency or paid providers.

Implemented: streaming upload/probe and 48k PCM, immutable edits, bounded private execution of the actual pinned PCM assembler and owner/project preset resolver, plus retained caption/crop/edge-evidence preview mechanics. Source admission is 512 MiB / 300 seconds; the legacy preview output still caps at 60 seconds. Actual upstream helpers require an authorized private read-only snapshot and are not distributed in this image.

**Not yet usable as the full original workflow:** ASR/alignment, complete cut-review/audio lock, portrait review ledger, semantic browser motion, original caption/encode and final delivery gates still need adapters/runtime validation. All outputs require review. Caller geometry/timestamps and synthetic capacity tests are not perceptual guarantees. See the [feature/parity map](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/WORKFLOW-PARITY.md).

Development tag: `ghcr.io/humanitylabs-org/defleur-video:0.2.0-review-1` (amd64). The listing stays `available:false` pending original-workflow parity, licensing, publication and user-host installation validation. No public image or completed install is claimed. [API details](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/README.md) · [Hermes connection](https://github.com/humanitylabs-org/wizard-app-store/blob/main/images/defleur-video/HERMES.md).

Private single-owner API, not an internet-hardened gateway or timeline editor. Use a dedicated bearer credential and private TLS/access controls. Runtipi's app-data chmod can broaden bind permissions; use a trusted host.
