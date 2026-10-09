# AI Accounts

The one place to connect your AI subscriptions for this Wizard server. Your agents use them from here, so you sign in once.

**Phase 1: Claude subscription (Pro or Max).** ChatGPT sign-in and API keys (OpenRouter, Tinfoil, OpenAI, Anthropic) are shown as "coming soon".

## Connect Claude

1. Open AI Accounts. Next to **Claude subscription**, press **Connect**.
2. Press the link it shows. It opens Claude's own sign-in page; use your phone or computer.
3. Sign in. Claude shows you a code. Copy it, paste it into AI Accounts, and press **Finish connecting**.
4. Press **Test**. It asks Claude for a one-word answer with the smallest model and shows OK or the error.

**Disconnect** signs this server out of Claude. Every agent using it stops until you connect again.

## How it works

- The sign-in is done by **Anthropic's official Claude Code** app (pinned version, auto-update off), running inside this app. AI Accounts only starts its login and passes it the code you paste.
- The sign-in is saved in a private Docker volume named `wizard-ai-accounts-claude`. It is not in your shared media folder, so the Files app can't see it. This page shows only your plan and account name, never the sign-in itself.
- **Hermes Agent** (Wizard build, v2026.9.24-wizard1 or newer) mounts the same volume. Its built-in **Claude Subscription DirectSDK (Experimental)** plugin by Nous Research runs the same official Claude Code to talk to Claude. Pick it in Hermes' model picker to use your subscription.

## Privacy and access

Keep this app on your private network (Tailscale). Public domain exposure is off. On a server with a public IP, block port 8795 at the provider firewall. You can also set an optional page password at install.

## Personal use only

This is for using **your own** Claude subscription on **your own** server, through Anthropic's official app. Anthropic does not allow offering Claude sign-in to other people through a product. If you build something for customers, use API keys instead.

## Uninstalling

Uninstalling AI Accounts while Hermes Agent is still installed keeps the sign-in (Docker won't remove a volume another app uses). To remove it completely, press **Disconnect** first.
