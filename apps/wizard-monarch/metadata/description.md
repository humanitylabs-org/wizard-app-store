# Monarch

The Monarch connection for your Wizard. Sign in to Monarch once in Monarch's own window and choose Read access (your Monarch password never reaches this app). The app talks to Monarch's official MCP server, keeps the sign-in private and refreshes it on its own, and keeps a local copy of your accounts, balances and categorized transactions, plus Monarch's budget, cash flow, net worth and recurring bills.

The connector screen contains only guided sign-in, connection status and Disconnect. No dashboard or companion view is required. Only read access is requested; no financial write action is implemented.

Monarch limits MCP use per week, so the app syncs twice a day and other apps read the copy (`bank-connection` spot, contract `wizard.bank-connection/1`, the same one the Teller connector offers). Disconnect and the app signs out of Monarch and deletes its copy.
