# Apple Health

Brings your iPhone's Apple Health data (sleep with stages, heart rate variability, resting heart rate, blood oxygen, Exercise minutes, active energy, steps and workouts) to your Wizard. Apple has no cloud service for this, so the data comes from the iPhone itself through the third-party iOS app Health Auto Export (by HealthyApps, not by Apple), whose REST API automation needs its Premium tier ($0.99 a month, $5.99 a year or $24.99 once, paid to that app).

Your Wizard stays private: the iPhone must be on the same Tailscale network as the box and posts to the box's own tailnet address. Every delivery carries a private token this app makes and shows on its setup screen with Copy buttons; anything without it is refused. The screen walks you through all four steps and shows "Received data from your iPhone" the moment the first data lands.

The app keeps a local copy (re-sent days merge, never duplicate) and offers it, read-only, to other apps on this box through the `health-data` spot (contract `wizard.health-data/1`, see `docs/health-data-contract.md`). Apple has no readiness score, so none is sent. Rotate token makes a new token; Disconnect deletes the copy and the token.
