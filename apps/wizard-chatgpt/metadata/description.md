# ChatGPT

Connect your ChatGPT Plus or Pro subscriptions on the ChatGPT page, and your agent uses them. Each sign-in is the agent's own ChatGPT device-code login (`hermes auth add openai-codex`, run by the agent's dashboard), so the agent keeps and renews the tokens and this app never sees them. ChatGPT asks you once to turn on **Settings → Security → Device code sign-in for Codex**; the page says so before it shows the code.

This is a Wizard AI connection app (`wizard.ai-connection/2`): `GET /api/connection` reports the overall status, plan and usage plus one row per subscription, `GET /api/accounts` lists them, and the MCP tool `connection_status` gives agents the same answer. When the app can't reach the agent it says so (with the agent address) instead of showing an empty list. Engine source: `humanitylabs-org/wizard-app-store` `images/wizard-chatgpt`; the page is the same one the Claude app uses.
