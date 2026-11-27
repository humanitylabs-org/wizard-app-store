---
wizard: 0.2
id: messenger
name: Messenger
version: 0.2.0-unified.16.135
type: service
category: app
summary: Encrypted text conversations with your peers, inside Wizard.
personal_data: reads your messages   # holds the owner's personal data (wizard-os spec/WIZARD_MD.md "Personal data"); a label only
license: MIT
# Listed in the official public Wizard App Index (Standard release only).
source: https://github.com/humanitylabs-org/wizard-messenger
icon: icon.png
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  path: /api
  port: 8765
  spec: API-contract.json
mcp:
  path: /mcp
  port: 8765
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8765
  source:
    path: static
    build: "python3 tools/build_view.py"
    dist: static
health: /healthz
# Passphrase-free owner access through the platform owner edge (wizard-os spec/OWNER_PROOF.md, DECISIONS 106 approved, amended by 107). An App Manager that
# doesn't know this key ignores it, and Messenger then keeps its passphrase sign-in.
owner_proof:
  scheme: hmac-v1
  wrap_key: true                    # independent key for the remembered-unlock envelope, kept outside /data
  activity: [/api/drafts]           # the visible view polls drafts; the hidden long poll does not count
  strip: [X-Messenger-Owner-Proof]  # legacy proof header: never accepted from a browser
# Feature switches (wizard.app-switches/1, wizard-os docs/APP_SWITCHES.md): the App Manager lists and flips them here,
# server-side with the owner proof, so the WizardOS Tracker's Try it works the same in every browser.
switches:
  contract: wizard.app-switches/1
  path: /api/view/switches
provides: [messaging]
# Contacts: names, Add to Contacts and My card when the Wizard sandboxes Messenger's window (contacts_link.py).
# Tinfoil: Translate, Catch me up and transcripts use the connected Tinfoil app's box gateway (tinfoil_link.py).
# Notifications: new messages are posted to the Notifications app (phone_notify.py).
uses: [contacts, tinfoil-api-key, notifications]
needs: []
---

Chats can be put in your own labels (a label is a named group of chats, e.g. WizardOS) from any chat's info sheet; the Inbox filters show a label's chats from every network.

The Inbox shows each chat with its last message (Settings > Inbox view: Chats, the default, or Compact for denser rows).

Open a busy chat and tap Catch me up (the sparkle beside the chat menu, or Summarize these under the new-messages line) for a private summary of everything you missed, written by Tinfoil. It asks once per chat (just this once, 24 hours, or always); turn it off in the chat's info or Settings.

Messenger runs entirely in its own isolated container. Its web view uses only its documented HTTP API; the UI source is shipped separately so a Wizard can customize it. Marmot MDK supplies encrypted conversation and relay synchronization.

This candidate implements text DMs with dedicated messaging identities, invitations, local encrypted history and explicit passphrase unlock after restart. The protected root Wizard ID is never imported. Public contact codes are shareable; secret keys are not exposed.

The API requires a generated capability for trusted integrations; browser access uses a scoped HttpOnly session, exact-origin checks and CSRF. Initial owner setup uses a single-use install capability. Without a key the MCP exposes public identity/status only. Each agent can get its own Messenger key with an owner-chosen level (Draft-only recommended) that adds chat listing, thread reading and draft tools; only the owner sends.

For the current public Store installation, see README.md. The recipe uses public digest-pinned GHCR images; no developer computer is required. PRIVATE-BETA.md preserves historical 0.1.2-beta.1 instructions only. Recipient contact and access grants are separate actions.
