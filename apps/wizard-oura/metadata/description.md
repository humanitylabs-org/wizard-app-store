# Oura

Connects one Oura account to your Wizard. **You need your own Oura developer app and its credentials**: Oura ended personal access tokens in December 2025, so the only way in is a free application you create on Oura's developer site with your Oura account. The app walks you through it on its own screen: an Oura Ring with an active Oura Membership (Oura shares data only while it runs), a new application on Oura's developer site filled in with the values the screen shows (each with a Copy button), its Client ID and Client Secret pasted here, then one sign-in to Oura. The keys and sign-in stay inside this app and are never shown again.

After sign-in the app downloads your Oura history, then checks for new data every 20 minutes (Oura's webhooks need a public address, and your box is private). It keeps the copy here and offers it, read-only, to other apps on this box through the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`). The Health app shows it. Readiness maps to recovery; Oura has no strain, so the app estimates a 0-21 activity effort from Oura's activity minutes (the formula is in the contract doc) and keeps Oura's own Activity score alongside. Your agent gets narrow tools to check the connection and ask for a sync.

Disconnect signs out of Oura and deletes the local copy.
