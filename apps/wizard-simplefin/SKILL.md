---
name: wizard-simplefin
description: Use when the owner asks about his bank accounts, balances or transactions, or another app needs bank data.
version: 0.1.0
author: Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [banking, simplefin, transactions, finance]
    related_skills: [card-benefits]
---
# SimpleFIN

The box's bank connection (`bank-connection` spot). Read-only: `bank_status` (linked banks, last sync, any bank needing attention; `behind: true` means that bank stopped updating without an error, so treat its numbers as stale and tell the owner to reconnect it on SimpleFIN), `bank_accounts` (accounts with balances), `bank_transactions` (search by date range, account id/last digits/name, text, amount range, posted/pending). `bank_sync` fetches now, but SimpleFIN refreshes banks only about once a day and allows a few requests a day, so prefer the synced copy.

Setup happens only in the SimpleFIN app screen (/wizard-simplefin/): never ask the owner for his setup token or bank password in chat. If `bank_status` shows `not_configured`, tell him to open the SimpleFIN app and follow its four steps. Banks are added or fixed on SimpleFIN's own site.

Amounts: negative = money out. Card refunds and statement credits are positive; card balances are negative when owed. Match benefit credits by account, date, amount and description, and report them as "looks posted"; the owner confirms in his own apps.
