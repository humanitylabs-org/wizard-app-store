# Withings

Connects one Withings account to your Wizard. You need your own free Withings developer application (your own developer credentials): the app walks you through creating it on its own screen. You create a "Public API integration" application on the Withings Developer Dashboard with this box's own callback address, paste its Client ID and Client Secret here, then allow access once in your own browser; Withings sends you straight back to this box and the app finishes the sign-in. The keys and sign-in stay inside this app and are never shown again.

After sign-in the app downloads your recent history (a year) of sleep summaries, daily activity and workouts, then checks for new data every 20 minutes. It keeps the copy here and offers it, read-only, to other apps on this box through the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`). Withings has no recovery score, so Health shows "no score" for recovery instead of a made-up one; activity is intensity minutes. On Withings' free developer plan, sleep score, overnight HRV and breathing rate may be held back; the app notices and syncs everything else.

Disconnect revokes the app's access on Withings and deletes the local copy.
