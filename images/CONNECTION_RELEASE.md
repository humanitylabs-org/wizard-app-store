# Connection release image sources

These are image build contexts, not duplicate public app index entries.

| Image | Runtime source |
|---|---|
| wizard-claude:0.2.0 | humanitylabs-org/claude-connection main `51d28c61e067ae1270b147aa022dcb8a54a48707` |
| wizard-chatgpt:0.2.0 | humanitylabs-org/chatgpt-connection main `d745933fd8899757062b7cfe3592917b1b019d35` |
| wizard-connection-router:0.1.0 | humanitylabs-org/wizard-connection-router main `88b77dfae3e3be9b25fd9691f9e75081f387ec29` |
| wizard-connection-router:0.1.4 | this repo `images/wizard-connection-router` (adds `GET /v1/owner/needs/<app>` for the Store install sheet) |

Runtime and provider tests are copied without modification. Router's additional `test-container.sh` belongs to this release route. The provider forks preserve Miguel's repositories as canonical in the public index. All Docker builds execute on GitHub-hosted Actions; PRs run tests without publishing. Main publishes each new tag once, then re-runs container checks against the published image. Never repush an existing version.
