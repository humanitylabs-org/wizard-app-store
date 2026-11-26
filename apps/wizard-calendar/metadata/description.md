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
