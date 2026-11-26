---
wizard: 0.2
id: notifications
name: Notifications
type: service
category: system
kind: agent-app
tags: [productivity]
version: 2.29.0-wizard29
summary: Your Wizard's own notification server. The agent tells you when something is done or needs you.
icon: icon.png
license: Apache-2.0
source: https://github.com/oscarhenrycollins/notifications
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 8080
  transport: streamable-http
skill: SKILL.md
system: true
provides:
- notifications
health: /v1/health
view:
  path: /notifications/
  port: 8080
---

# Notifications

Your Wizard's own notification server: unmodified [ntfy](https://ntfy.sh), running on your box.

- **Your agent** sends you notifications with the `notify` tool: a finished job, something you asked to be told about, or a problem that needs you.
- **You** read them in the ntfy web app on this app's address, or subscribe once in the free ntfy phone app to the topic `wizard` on this server.
- **Scheduled jobs**: set the Hermes cron folder in the app's settings and every scheduled-job result lands in the inbox on its own (silent runs stay quiet, repeated failures alert once a day).
- **Other apps** can post to the same server.

Nothing leaves the box by default. On iPhone, instant delivery needs the optional ntfy.sh relay (it forwards only a wake-up ping, never the text). No login, so keep it on your private network.
