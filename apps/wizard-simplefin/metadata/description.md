# SimpleFIN

The bank connection for your Wizard. Create your own SimpleFIN Bridge account ($15 a year, paid to SimpleFIN), link your banks there, create a setup token and paste it here. Your bank passwords go to SimpleFIN, never to this app. SimpleFIN covers thousands of U.S. and Canadian banks, including Chase and American Express, and refreshes them about once a day.

The app keeps its private SimpleFIN access address and a local copy of accounts, balances and transactions in its own folder, syncs a few times a day within SimpleFIN's request limits, and offers the data read-only to other apps on this box (`bank-connection` spot, contract `wizard.bank-connection/1`). Disconnect deletes the copy here.
