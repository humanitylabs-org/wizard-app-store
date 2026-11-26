# Finances

A simple money app over your bank connection. Review new transactions with one tap, give them a category and a clearer name, add a note, and tick "always use this" to make a rule for next time. See spending by category for any month, and every account's balance.

Add manual accounts for things no bank sees, like a cold-storage Bitcoin wallet (enter the BTC amount; it's valued at the live price). Bring over past history from another money app once, and every row says where it came from.

Finances reads from a bank-connection app on your box: SimpleFIN by default, or Monarch or Teller if you have those. It never changes the bank's data. Your reviews, categories, names, notes and rules live in Finances' own database, so a fresh sync never overwrites them, and switching connections keeps each connection's edits.

No bank connection yet? With the "Use Finances without a bank" switch on, import a CSV, OFX or QFX file downloaded from any bank's website (columns are remembered per bank, and importing again skips what's already there), or add spending by hand. Those transactions get the same review, categories, rules and monthly spending.

Reply: open a transaction (or an alert at the top) and tap Reply to start a new chat with your agent about it. It opens an unsent Chats draft with the item attached; Finances never sends anything.
