---
name: contacts
description: Use when the owner asks about his contacts - who someone is, their number, email or accounts, adding or editing a person.
---
# Contacts

The owner's private address book. Tools (MCP server `contacts`):
- `contacts_search {query?, limit?}`: name, nickname, company, phone, email or account text. Empty query lists everyone.
- `contacts_get {id}`: one person with phones, emails, accounts per network, notes, birthday.
- `contacts_lookup {email | phone | network+value}`: who owns this address.
- `contacts_add {name, phones?, emails?, accounts?, ...}`: phones/emails are `[{value,label}]`, accounts `[{network,value,label}]`.
- `contacts_update {id, ...}`: only fields sent change; a sent list replaces that list.

Deleting and merging people is owner-only, in the Contacts screen. Never merge or delete on your own. Confirm each add or update by reading the contact back.
