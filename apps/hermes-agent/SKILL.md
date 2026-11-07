---
name: hermes-agent-store
description: Use when explaining the legacy Hermes Agent store app and its granted Claude app login mount.
---

# Hermes Agent store app

Use Hermes' own dashboard for model selection. Installing or connecting the Claude app must not change the owner's selected default model.

For a Claude subscription, install the Claude app (`wizard-claude`), connect there and grant Hermes Agent access to its `claude-login` share through App Manager. Then explicitly choose Claude Subscription DirectSDK (Experimental) in Hermes. Only the official Claude Code CLI reads the sign-in at `/claude`; never read, copy or print credentials. The whole folder is shared so Claude Code processes coordinate refresh with its lock.

The provider owns the login under its own app-data. Hermes declares `mounts: [{app: wizard-claude, share: claude-login, path: /claude}]` in `wizard.md`; it does not create a named volume or guess another app's host path. Revoking the share removes the mount at restart; connect and disconnect in the Claude app. A missing provider or revoked grant means Claude Code has no usable login, not permission to sign in inside Hermes.

This legacy store recipe requires the App Manager share compiler; stock Runtipi does not process the manifest. Stop the deprecated AI Accounts app before migration and never run a second copy of a rotating login chain. Back up the Claude app-data for Claude login and the Hermes app-data for Hermes state.
