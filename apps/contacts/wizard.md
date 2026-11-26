---
wizard: 0.2
id: contacts
name: Contacts
type: view
category: app
version: 0.4.4
summary: One private contact list for Messenger, email and every app.
license: GPL-3.0-only
source: https://github.com/oscarhenrycollins/contacts
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8822
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8822
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8822
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides:
- contacts
system: false
uses: [wizard-calendar]   # Calendar's Radicale server keeps the address book for phones when its radicale switch is on
needs: []
health: /healthz
switches:
  contract: wizard.app-switches/1
  path: /api/switches
---

# Contacts

One private address book on your Wizard. People, their phones, emails and their account on each network (WhatsApp, Telegram, Instagram, email and more), a photo and notes. Messenger adds people with "Add to Contacts" and shows their contact name; any app with an approved link to Contacts can look people up. Import and export vCard (.vcf), review suggested duplicates without automatic merges, share a contact or network link by QR code, and opt in to CardDAV phone sync. Keep iCloud enabled until phone sync has been confirmed on the device. When Calendar's `radicale` switch is on, the address book is also kept on Calendar's Radicale server (CalDAV + CardDAV in one phone account); this app's list stays the working copy and a full mirror, so switching it off loses nothing.
