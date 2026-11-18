# Private first: what the provider images ask the Agent Service

wizard-os DECISIONS #115 and `spec/AGENTS.md` section 10 (wizard-os#676). Switch: `wizard/private-first-setup`
(shell tweak in the owner's Look file; Agent Service env `WIZARD_PRIVATE_FIRST=1` forces it on, `0` off). Off by
default. Built for wizard-app-store#77; the Agent Service side is wizard-agent-service#545.

The Claude, ChatGPT and Tinfoil images never read the Look file. They ask the Agent Service through the wizard-os
plugin on the main Hermes dashboard (the standard agent), which they already sign in to. Any answer other than the
one below (an older plugin's 404, unreachable, another shape) means **off**, and the image does what it did before.
`WIZARD_PRIVATE_FIRST=0` in an image's own env turns it off there without asking.

## `GET /api/plugins/wizard-os/private-first`

```json
{"schema": "wizard.private-first/1", "on": true, "standard_agent": "hermes", "private_agent": "<id or null>"}
```

Only `schema` and `on: true` are read.

## `POST /api/plugins/wizard-os/private-first/standard-agent` (Claude, ChatGPT)

Sent after a finished sign-in, instead of the image's own `POST /api/model/set {scope: main}`.

```json
{"provider": "claude-subscription-directsdk-experimental", "model": "claude-opus-5-5[1m]"}
```

`provider` is the Hermes provider slug (`openai-codex` for ChatGPT). `model` is a suggestion (newest Opus, else
Hermes' recommended default, else the first listed model; may be `""`). The Agent Service switches the standard agent
on (creates it if the box has none), attaches the provider there, and applies the model only if the standard agent
has none. It never changes the private agent. Answer `{"ok": true, "agent": "hermes"}`; anything else counts as not
done (the image reports `agentDefault: "skipped"` and sets nothing itself).

## `POST /api/plugins/wizard-os/private-first/private-agent` (Tinfoil)

Sent on Connect, on Test and on every start (idempotent), instead of registering Tinfoil as a custom provider on the
main Hermes.

```json
{"provider": "tinfoil", "model": "kimi-k3", "models": ["kimi-k3", "glm-5-3"]}
```

No key or token travels: the Agent Service fetches the private agent's relay token from Tinfoil's box-only
`POST /api/private-clients` as it already does. It makes Tinfoil the first-run private agent's provider (creating
that agent if the box has none, `private` preset, `fallback: false`, `is_default: true`). Answer
`{"ok": true, "agent": "<private agent id>"}`; then Tinfoil's status shows `chatIntegration: "private_agent"`.
Anything else: `"unavailable"`, nothing is added to the main Hermes, and the next start retries. With the switch off
again, the next start registers on the main Hermes as before.
