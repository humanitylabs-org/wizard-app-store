# Hermes Agent

The self-improving AI agent by [Nous Research](https://github.com/NousResearch/hermes-agent), packaged for Runtipi using the **unmodified official Docker image** and native Hermes dashboard.

## First use

Choose a dashboard username and strong password during installation. Open the app, sign in with those credentials, and configure your AI provider using Hermes's own setup interface. Model access may require a separate subscription or API key; none is included.

## Private access

Use a trusted LAN or VPN such as Tailscale. Public domain exposure is disabled in this recipe. That setting does **not** firewall the app's published port: on a public VPS, restrict inbound access at the host/provider firewall and verify the port is unreachable from the public internet. Prefer your private HTTPS URL. Anyone with dashboard access can operate this Hermes instance.

## Data and permissions

All Hermes state is persisted in this app's `data` directory, mounted at `/opt/data`. Back up that directory before upgrades. There is no Docker socket, privileged mode, host networking, or access to the host's existing Hermes installation. This is a normal agent, not a server caretaker.

The official image starts its initialization as root and then runs Hermes as UID/GID 1000. Do not override the container user or entrypoint. Provider credentials, plugins, skills, and configuration remain managed by upstream Hermes.

## Updates

Use Runtipi app updates to update the pinned image; do not modify the image in place. Back up app data before updating; reverting an image alone may not undo a data migration.
