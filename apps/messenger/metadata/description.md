# Messenger

Chats can be put in your own labels (a label is a named group of chats, e.g. WizardOS) from any chat's info sheet; the Inbox filters show a label's chats from every network.

The Inbox shows each chat with its last message (Settings > Inbox view: Chats, the default, or Compact for denser rows).

Open a busy chat and tap Catch me up (the sparkle beside the chat menu, or Summarize these under the new-messages line) for a private summary of everything you missed, written by Tinfoil. It asks once per chat (just this once, 24 hours, or always); turn it off in the chat's info or Settings.

Messenger runs entirely in its own isolated container. Its web view uses only its documented HTTP API; the UI source is shipped separately so a Wizard can customize it. Marmot MDK supplies encrypted conversation and relay synchronization.

This candidate implements text DMs with dedicated messaging identities, invitations, local encrypted history and explicit passphrase unlock after restart. The protected root Wizard ID is never imported. Public contact codes are shareable; secret keys are not exposed.

The API requires a generated capability for trusted integrations; browser access uses a scoped HttpOnly session, exact-origin checks and CSRF. Initial owner setup uses a single-use install capability. Without a key the MCP exposes public identity/status only. Each agent can get its own Messenger key with an owner-chosen level (Draft-only recommended) that adds chat listing, thread reading and draft tools; only the owner sends.

For the current public Store installation, see README.md. The recipe uses public digest-pinned GHCR images; no developer computer is required. PRIVATE-BETA.md preserves historical 0.1.2-beta.1 instructions only. Recipient contact and access grants are separate actions.
