# Wisdom

A reader for collections of wisdom texts. Public builds start with an empty library; no reading history, highlights or requests are copied.
Your library lives in Files under `media/Wisdom`; reading progress, highlights and ratings live in
the app's own data folder and survive updates and reinstalls.

Shared library contains approved collections; My library contains personal imports and requests.
Private libraries and reading state remain on the installation through app updates.
Per-collection export is explicit, previewed and never publishes automatically.
Optional in-app request admission remains operator-configured. No microphone is shipped.
The Wizard gateway must serve the approved shared client at `/wizard-os-home/core/app-client.js`.
See README.md for the private install contract.

Private beta. The code's distribution licence needs owner approval before public listing.
API and editable-view metadata follow the open wizard-os PR24 proposal.
