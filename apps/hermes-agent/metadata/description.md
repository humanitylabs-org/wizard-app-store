# Hermes Agent

The self-improving AI agent by [Nous Research](https://github.com/NousResearch/hermes-agent), packaged for Runtipi with its native dashboard.

**Wizard build (v2026.9.24-wizard1).** The official `nousresearch/hermes-agent:v2026.9.24` image, pinned by digest, with two official add-ons and nothing else changed:

- **Claude Code 2.1.263**, Anthropic's official CLI (integrity-checked, auto-update off).
- **Claude Subscription DirectSDK (Experimental)**, NousResearch's official provider plugin (MIT, pinned commit `ef73726`), built into Hermes' provider folder.

Together they let Hermes use the Claude subscription you connect in the **AI Accounts** app. Your current model and provider stay exactly as they are until you choose Claude yourself.

## First use

Choose a dashboard username and strong password during installation. Open the app, sign in with those credentials, and configure your AI provider using Hermes's own setup interface. Model access may require a separate subscription or API key; none is included.

## Use your Claude subscription (optional)

1. Install **AI Accounts**, press **Connect** next to Claude subscription, sign in and paste the code. Press **Test** to check it.
2. In Hermes, open the model picker (or run `hermes model` in the app's terminal) and choose **Claude Subscription DirectSDK (Experimental)**, then **Opus**.

Hermes runs the official Claude Code for each request, using the sign-in in the shared `wizard-ai-accounts-claude` volume (mounted at `/claude`). Hermes itself never reads that sign-in. If you pick Claude before connecting, Hermes says Claude Code "has no usable login": connect in AI Accounts and try again. This is for your own subscription on your own server; products for other people should use API keys.

## Private access

Use a trusted LAN or VPN such as Tailscale. Public domain exposure is disabled in this recipe. That setting does **not** firewall the app's published port: on a public VPS, restrict inbound access at the host/provider firewall and verify the port is unreachable from the public internet. Prefer your private HTTPS URL. Anyone with dashboard access can operate this Hermes instance.

## Data and permissions

All Hermes state is persisted in this app's `data` directory, mounted at `/opt/data`. Updating to the Wizard build does not touch it. Back up that directory before upgrades. There is no Docker socket, privileged mode, host networking, or access to the host's existing Hermes installation. This is a normal agent, not a server caretaker.

The official image starts its initialization as root and then runs Hermes as UID/GID 1000 (the same as AI Accounts, so both can keep the Claude sign-in fresh). Do not override the container user or entrypoint. Provider credentials, plugins, skills, and configuration remain managed by upstream Hermes.

## Updates

Use Runtipi app updates to update the pinned image; do not modify the image in place. Back up app data before updating; reverting an image alone may not undo a data migration.
