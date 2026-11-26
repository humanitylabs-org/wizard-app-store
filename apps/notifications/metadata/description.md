# Notifications

Your Wizard's own notification server: unmodified [ntfy](https://ntfy.sh), running on your box.

- **Your agent** sends you notifications with the `notify` tool: a finished job, something you asked to be told about, or a problem that needs you.
- **You** read them in the ntfy web app on this app's address, or subscribe once in the free ntfy phone app to the topic `wizard` on this server.
- **Scheduled jobs**: set the Hermes cron folder in the app's settings and every scheduled-job result lands in the inbox on its own (silent runs stay quiet, repeated failures alert once a day).
- **Other apps** can post to the same server.

Nothing leaves the box by default. On iPhone, instant delivery needs the optional ntfy.sh relay (it forwards only a wake-up ping, never the text). No login, so keep it on your private network.
