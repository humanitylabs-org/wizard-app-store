# Hermes Agent

The self-improving AI agent by [Nous Research](https://github.com/NousResearch/hermes-agent), packaged for Runtipi using the **unmodified official Docker image** and native Hermes dashboard.

## First use

Choose a dashboard username and strong password during installation. Open the app, sign in with those credentials, and configure your AI provider using Hermes's own setup interface. Model access may require a separate subscription or API key; none is included.

## Wizard apps connect automatically

This is the one store-specific addition to vanilla Hermes. A small second service, **wizard-apps**, runs the same official image and leaves the Hermes service itself unchanged. Install any Wizard app (for example DeFleur Video) and within about a minute Hermes can use it. You don't need `hermes mcp add`, SSH or extra instructions, so your first message can simply be "use the DeFleur video editor to edit this video".

- It finds running Wizard apps on the Runtipi network. The app list comes from the public Wizard App Store, so new apps work without updating Hermes Agent.
- It adds an MCP entry (named after the app id) for apps that offer MCP tools, using the Hermes CLI.
- It keeps one skill current, `skills/wizard-apps`, which says which apps are installed and how to use the apps that have no tools (Transcriber, Secret Drop, Browser).
- It removes its own entry when an app has been gone for 10 minutes.

**It never edits your own settings.** MCP entries and skills you add or change are left alone. To turn it off, set **Connect Wizard apps** to off in this app's settings. It then removes only what it added. [Design and contract](https://github.com/humanitylabs-org/wizard-app-store/tree/main/sidecars/wizard-apps).

## Private access

Use a trusted LAN or VPN such as Tailscale. Public domain exposure is disabled in this recipe. That setting does **not** firewall the app's published port: on a public VPS, restrict inbound access at the host/provider firewall and verify the port is unreachable from the public internet. Prefer your private HTTPS URL. Anyone with dashboard access can operate this Hermes instance.

## Data and permissions

All Hermes state is persisted in this app's `data` directory, mounted at `/opt/data`. Back up that directory before upgrades. There is no Docker socket, privileged mode, host networking, or access to the host's existing Hermes installation. This is a normal agent, not a server caretaker.

The official image starts its initialization as root and then runs Hermes as UID/GID 1000. Do not override the container user or entrypoint. Provider credentials, plugins, skills, and configuration remain managed by upstream Hermes; the wizard-apps service only adds the entries and skill described above.

## Updates

Use Runtipi app updates to update the pinned image; do not modify the image in place. Back up app data before updating; reverting an image alone may not undo a data migration.
