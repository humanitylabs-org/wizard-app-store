---
wizard: 0.2
id: connected-accounts
renamed_from: [wizard-connectors]
name: Connected accounts
type: external
category: app
version: 0.9.1
summary: Owner-managed Google account broker and simulated private chat summaries.
license: MIT
source: https://github.com/humanitylabs-org/wizard-connectors
runtime:
  kind: runtipi
  package: image
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [connector-status, simulated-private-summary, calendar-source]
system: false
uses: []
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---
# Connected accounts
Ask your wizard **Set up my Google app**, or choose **Set it up myself** for seven guided screens. Your own main Google account owns one app for all your accounts; your wizard needs no Google account. See docs/GOOGLE_SETUP.md for the secret-free agent intake and shipped browser script.

Bring your own Google OAuth app in **Your Google app**, then connect each account,
authorize Calendar read-only scope, and explicitly allow Calendar to use it.
Music binding is separate; private chat remains synthetic-only.

Calendar consumer base URL: **http://wizard-connectors-calendar:8799** (the
`wizard-connectors-calendar` ingress service name, reached over the private WAM link network for
the approved Calendar connection; the app joins no shared main network). Paths:
`/service/calendar/status`, `/service/calendar/calendars`, `/service/calendar/events`.
WAM layer-2 grants must contain an incoming SHA-256 row for `wizard-calendar`;
Calendar sends its key as `X-Wizard-Grant`. There is no owner-session requirement
on this service API. Report-only mode does not weaken Calendar authentication.
WAM injects the standard read-only grants directory into all app services; the
recipe must not mount an app-specific bridge. The `wizard-connectors-calendar` ingress service is `is_main`, port 8799, so
WAM publishes it under `provider_endpoints["connected-accounts"]` for fresh installs
(legacy installs may retain `provider_endpoints["wizard-connectors"]`). Calendar
must declare `uses: [connected-accounts]` or the `calendar-source` slot; see the
fresh-install compatibility contract and upstream Calendar gap in docs/CALENDAR_API.md. There is no
`WIZARD_MAIN_NETWORK` setting any more. See docs/CALENDAR_API.md.
