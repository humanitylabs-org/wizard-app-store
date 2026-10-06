# Hermes connection and operator instructions

**Original-workflow integration is incomplete.** Read WORKFLOW-PARITY.md before claiming capability. Hermes is the intended creative/operator client, not an extra autonomous service.

Hermes is only an HTTP **client** here. Do not install the recovered plugin, change Hermes configuration, mount Hermes state, or add an agent runtime to the video app. The same commands work from a plain Python 3 shell.

## Connection

The user must authorize the source file, target service and editing scope. Supply `VIDEO_API_URL` (an http(s) origin, e.g. `http://<tailscale-host>:8787`). The default install needs no token; only if the administrator set one, also supply `VIDEO_API_TOKEN` through the invoking process's private environment. Do not put the token in chat, URLs, plan JSON, command arguments or review HTML. Default URL is loopback; for a separate host use the private reachable app URL, preferably HTTPS. A container's localhost is not another container's localhost. Copy `client.py` to the client's machine; it uses Python's standard library only. Use a dedicated credential for this video service, never an agent/provider credential. Current authorization is service-wide single-owner: it permits reading/mutating/deleting all this service's projects, not per-project or read-only scopes. Do not share it with untrusted clients. Configure its environment using your existing private credential mechanism; no Hermes core/plugin modification or global model switch is needed.

Ask the service for its actual contract before acting (from the directory containing `client.py`):

```sh
python3 -c 'import os; from client import Client; print(Client(os.environ["VIDEO_API_URL"], os.environ.get("VIDEO_API_TOKEN", "")).request("GET", "/v1/capabilities"))'
python3 client.py upload /authorized/path/source.mp4
```

## Actual stage operations

Capture the returned project ID. For the source stage create `empty.json` containing `{}`; author `edit-plan.json` only after reviewing the actual source. Preset input is `{ "owner": { ... }, "project": { ... } }` with the intended explicitly supplied preset JSON, not a filesystem path.

```sh
python3 client.py stage "$PROJECT_ID" source-audio empty.json
python3 client.py status "$JOB_ID" --wait
python3 client.py stage-bundle "$JOB_ID" ./private-source-bundle
# The following require the authorized private helper snapshot:
python3 client.py stage "$PROJECT_ID" pcm-assemble edit-plan.json
python3 client.py stage "$PROJECT_ID" resolve-preset preset-input.json
# Capture each returned job ID, wait and download its stage-bundle separately.
```

The client streams source upload and hash-verifies JSON/WAV artifacts. Source and edited PCM are real decoded/assembled audio, but no stage declares dialogue lock. The administrator may mount the authorized snapshot read-only at `/opt/workflow` and set `VIDEO_HELPER_ROOT=/opt/workflow`; the standard recipe intentionally does not mount it. Only two hash-pinned helpers are executable, using server-owned paths. This is not an arbitrary shell or a workaround for redistribution permission. Missing helpers fail closed. Do not expose their upstream scripts as a generic command endpoint.

For the original workflow, privately authorized skill instructions can remain client-side editorial guidance. They are not needed for basic HTTP operation and are not bundled here. Do not mount Hermes home/state into the app or read existing owner presets without explicit authorization. ASR/alignment and subsequent parity-map stages remain unavailable; stop rather than synthesize their receipts.

## Retained preview review mechanics

Capture the returned project ID. Review the actual source before authoring a decision; never manufacture a transcript, timestamps, face rectangle, source-specific cut reason or completed quality receipt. If those inputs cannot be obtained, ask for them. The API does not transcribe or decide edits. See [EDITING.md](EDITING.md) for the strict decision schema and source-vs-output time coordinates.

```sh
# Set these IDs to actual returned values, not fabricated examples.
python3 client.py decision "$PROJECT_ID" decision.json
python3 client.py decisions "$PROJECT_ID"
python3 client.py render "$PROJECT_ID" --decision "$DECISION_ID"
python3 client.py status "$JOB_ID" --wait
python3 client.py review "$JOB_ID" ./private-review-bundle
```

The client reads back mutations and verifies SHA-256 before saving downloads. Open the local `index.html`; listen to the full preview and every edge, inspect waveform/spectrogram, caption timing and framing. Describe generated evidence as **unreviewed** until someone actually reviews it. Persisted text and valid geometry are caller assertions, not ASR/alignment/face-detection proof. Never report `needs_review` as approved. There is no delivery-approval route and no autonomous creative selection or semantic animation.

A failed job is terminal. Inspect its error and explicitly submit a new job only when justified; do not blindly retry media failures or ignore budgets. On restart, interrupted work fails instead of replaying. For revisions save a new decision and new job. Keep downloaded bundles private: they contain original-context audio and rendered media.

Delete only when the user has authorized removal and needed files are safely retained:

```sh
python3 client.py delete "$PROJECT_ID"
```

This removes the app's original, decisions, jobs and artifacts, not just a preview. The client verifies deletion by reading back the target. No paid provider calls are made by the service or client; an external agent's own model use is separate.
