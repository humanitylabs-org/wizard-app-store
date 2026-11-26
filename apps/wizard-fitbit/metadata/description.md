# Fitbit

Connects one Fitbit or Pixel Watch account to your Wizard. Google switched the old Fitbit Web API off in October 2026, so this app reads your data through the Google Health API, the official replacement.

**You need your own developer credentials.** The app walks you through it on its own screen: your Fitbit must sync to a personal Google account; you create a free Google Cloud project, enable the Google Health API, set up Google sign-in with yourself as a test user and three read-only scopes, create a Web OAuth client and paste its Client ID and Client secret here. Then you sign in with Google once in your own browser and paste the address it lands on back into the app. The keys and sign-in stay inside this app and are never shown again. While your Google project is in Testing mode, Google ends the sign-in after 7 days and the app asks you to connect again.

After sign-in the app downloads up to a year of history, then checks for new data every 20 minutes. It keeps the copy here and offers it, read-only, to other apps on this box through the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`). The Health app shows it.

Google's API does not include Fitbit's Daily Readiness or Sleep Score, so this source sends no readiness score (Health shows recovery as "no score") and measures activity in Active Zone Minutes, with its own targets.

Disconnect ends the app's Google access and deletes the local copy.
