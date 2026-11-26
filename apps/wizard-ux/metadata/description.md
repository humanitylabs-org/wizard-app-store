# Wizard Shell
The existing phone/desktop UX, native bridge and permanent in-app Back behavior are preserved.
Serves its own static files and streams all same-origin API requests to the independently installed
Wizard Agent Service. Holds no Hermes credentials or durable agent state. No headless-browser
replacement is introduced: Chromium remains the Browser system app, as in the approved slots.
Android/Mac native wrappers continue to load the same HTTPS surface and bridge.
