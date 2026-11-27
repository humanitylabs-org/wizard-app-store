---
wizard: 0.2
id: wizard-calendar
name: Calendar
type: view
category: app
version: 0.3.31
summary: Your Google and Microsoft calendars in one view. Add, edit and answer invites; private iCal links and snapshots too.
personal_data: reads your calendar   # holds the owner's personal data (wizard-os spec/WIZARD_MD.md "Personal data"); a label only
license: MIT
source: https://github.com/humanitylabs-org/wizard-calendar
runtime:
  package: source
  kind: runtipi
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
    build: python3 tools/check_view.py
    dist: web
provides: [calendar-viewing, calendar-import, calendar]
system: false
uses: [mail-calendar, wizard-google, wizard-microsoft, connected-accounts]
needs: []
health: /healthz
owner_proof: hmac-v1   # wizard-os#133: switch calls need the signed owner proof once the box turns owner proof on
# Feature switches (wizard.app-switches/1, wizard-os docs/APP_SWITCHES.md): the App Manager lists and flips them, so the
# WizardOS Tracker's Try it works the same in every browser. Off by default.
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Calendar — private test release

Empty by default; the first screen offers Connect Google / Connect Microsoft. Connecting runs inside Calendar
(web/connect.js, the same sheet as Wizard Mail): Quick connect through Composio in one window, or your own app in the
Google / Microsoft app. Connected calendars are read and changed through those apps' box-only
`wizard.mail-calendar/1` API (Calendar never holds a sign-in): Day / Week / Month, add, edit, delete, answer invites.
Owners can still add a private Google iCal link in Settings; Calendar stores it locally, refreshes a read-only
snapshot and never writes iCal or snapshot events. Calendars an owner shares from Connected accounts
(`connected-accounts`, its grant-scoped `/service/calendar/*` API) show read-only next to them; an account also
connected in the Google app shows once, from there. The API and MCP
expose only the redacted visible state. See OSCAR-SETUP.md for privacy and snapshot contracts.
The Wizard gateway must serve its approved shared app-client.js resource. A standalone
install uses tools/run_portable.py without an app image build. Not a public store listing.
