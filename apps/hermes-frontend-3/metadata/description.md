# Hermes Frontend 3

A separately installed **Desktop-style browser frontend** for your existing Hermes Agent. This packages [przbadu/hermes-ui](https://github.com/przbadu/hermes-ui), a community extraction of the official Hermes Desktop renderer—not an official Nous browser release. Its UI is unchanged.

## Connect it

Install **Hermes Agent** from the Wizard App Store first and leave it running. When installing this frontend, enter the backend's private HTTP(S) origin reachable from the frontend container.

For one Hermes installation on Runtipi's shared main Docker network, the service address is normally `http://hermes-agent:9119`. If you have multiple Hermes installations, use the exact backend container name instead: `http://<container-name>:9119`. Your server administrator can find it with `docker ps --filter label=runtipi.managed=true --format '{{.Names}}'` and verify both containers share the Runtipi main network. Do not use `localhost`—that means the frontend container itself. No trailing slash, path, or credentials are accepted.

Open this frontend and sign in with the **existing Hermes dashboard username and password**. Configure providers in Hermes itself. There is no second agent, separate session database, shared data mount, or Docker-admin access in this frontend. Removing this frontend leaves Hermes and its conversations intact.

## Private access

Keep both services behind your private network, such as Tailscale. `exposable: false` disables Runtipi public-domain exposure; it is not a firewall for published ports. Never expose an unauthenticated backend publicly. This frontend preserves native backend authentication and proxies API and WebSocket traffic to the configured origin.

## Proof-of-concept scope

The pinned renderer is `1af684e2d6ce05e6d1da82d67bc671e15d2d2d96`; compatibility is tested against the store's Hermes `v2026.9.24` image. Login, session listing and live WebSocket traffic are exercised in disposable containers. No paid model turn is included in packaging tests, and not every Desktop feature is certified. Desktop is the primary target; the upstream welcome heading clips on narrow phones. This is not a promise of compatibility with every future Hermes release.

The image supports amd64 and arm64; runtime smoke testing is on amd64. The upstream MIT license is included in the image. The logo is the same Nous Research logo used by the vanilla Hermes listing.
