# WHOOP

Connects one WHOOP account to your Wizard. The app walks you through setup on its own screen: you need a WHOOP membership (any tier), you create a free app on WHOOP's developer dashboard, paste its Client ID and Client Secret here, then sign in to WHOOP once in your own browser and paste the address it lands on back into the app. The keys and sign-in stay inside this app and are never shown again.

After sign-in the app downloads your full WHOOP history, then checks for new data every 20 minutes, and every 5 minutes between 05:00 and 11:00 your time so last night shows up soon after you wake (a private box can't receive WHOOP webhooks). It keeps the copy here and offers it, read-only, to other apps on this box through the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`). The Health app shows it: today, trends and workouts. Your agent gets narrow tools to check the connection and ask for a sync.

Disconnect signs out of WHOOP and deletes the local copy.
