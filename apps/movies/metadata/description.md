# Movies

A private watch queue for films and series. Add titles, reorder or bump them, open a detail card,
mark them watched (history keeps every watch and its date), and queue a rewatch. A new install
starts with exactly one public example, Batman Begins (2005); nothing about any owner ships with the app.
Your queue, history, notes and request log live in the app's own data folder and survive updates
and reinstalls.

Optional, off unless configured at install:
- **Where to watch** (`CINEQUEUE_WATCH_REGION`, e.g. `TH` or `US`): streaming availability from
  JustWatch for that country. Unset hides the panel; no third-party lookups are made.
- **Agent requests** (`CINEQUEUE_ADMIT=live` plus `CINEQUEUE_WIZARD_ORIGIN`): "find and add" requests
  are handed to your Wizard, which resolves the exact title and fills in the card through this app's
  MCP tools. Without it, the add sheet adds simple cards directly and nothing is sent anywhere.

Private beta. The code's distribution licence needs owner approval before public listing.
