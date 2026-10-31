---
name: browser
description: Use for JavaScript pages and for handing the live Wizard Browser to its owner on a phone to sign in, solve a CAPTCHA, enter a code or approve consent. Resume the same CDP session after the owner taps Done.
version: 0.3.0
license: WTFPL
metadata:
  hermes:
    tags: [browser, chromium, screenshot, web, captcha, otp, login, handoff, wizard-app]
---

# Browser

One shared, headful Chromium on a virtual display. Agent CDP, MCP and the owner's phone viewer all use the same tabs, profile and cookies. No Hermes fork or core patch is required.

## Agent tools

- `browser_status`: version and open tabs (id, URL, title).
- `read_page(url, wait_ms?)`: JavaScript-rendered visible text; opens and closes a separate tab. Text is capped at 100,000 characters.
- `screenshot(url, width?, height?, full_page?, wait_ms?)`: PNG; opens and closes a separate tab.
- `start_handoff(tab_id?, url?, purpose?, note?, ttl_s?, base_url?, replace?)`: activate an existing tab (prefer this) or open `url`; return `session_id`, `handoff_url`, expiry and `send_to_owner`. Default lifetime 15 minutes, max 1 hour. Idempotent while active unless `replace=true`.
- `handoff_status()`: `active`, `owner_opened`, `owner_done`, `completed_at`, `engine_active`, expiry and tab summary. This does not read form field values.
- `end_handoff()`: revoke access without closing the tab or browser. Optional after owner Done; Done already revokes access.

These are MCP tools at `/mcp` on the **direct local app port**, not the owner's proxied route. A plain HTTP JSON-RPC caller can POST:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"handoff_status","arguments":{}}}
```

## Stock Hermes / other CDP clients

Configure the **local** address advertised by the installed Browser app:

```yaml
browser:
  cdp_url: http://127.0.0.1:8793
```

Or set `BROWSER_CDP_URL=http://127.0.0.1:8793` in the agent process. The actual port is the installation's Runtipi `APP_PORT`, not necessarily 8793. From another app use `http://browser:9222` on the same Docker network (resolve to IP if Chrome rejects a hostname). Playwright: `chromium.connect_over_cdp(...)`.

CDP has no password. The host bind is loopback-only. The owner route refuses DevTools and MCP with reverse-proxy headers; never set CDP to the owner's HTTPS viewer address or expose 9222, 6080 or 6081 publicly.

## Hand to the owner, then continue

1. Stop at the human step. Do not guess credentials or codes, defeat CAPTCHAs, or submit the owner's consent/payment for them.
2. Use the id of your existing tab: `start_handoff(tab_id=..., purpose="login", note="Sign in to Google, then tap Done, give it back")`.
3. Send `send_to_owner` only to this installation's owner, through the conversation you are already in. The default link is owner-origin-relative `/browser/handoff/#<capability>`. If the channel needs an absolute URL, use the installation's **owner-authenticated** gateway origin and the Browser route, or pass `base_url="https://your-wizard.example/browser"`. The base is the app prefix, not the CDP address. A nonstandard installation must install an owner-authenticated route first (see README); never fall back to publishing the direct app port.
4. **Pause all browser automation, screenshots and page reads while the owner types.** Do not collect their password, code, clipboard or keystrokes. The phone controls are Keyboard, Paste (masked by default), Up, Down and Back (remote page history, never Wizard history).
5. Wait for `handoff_status().owner_done == true` and `active == false`. The owner taps **Done, give it back**; no chat reply is necessary. Check status on the next wake/owner reply or use a bounded, infrequent status check—not a tight polling loop. Expiry alone is **not** successful completion; ask the owner or issue a fresh link if needed.
6. Continue with the same tab via CDP. Verify the human step succeeded before proceeding. Never reopen another browser or replay the sign-in yourself.

The owner route authenticates the owner before serving HTML, controls and WebSocket upgrades. A short-lived fragment capability adds session-specific access; it is removed from the address bar after redemption, held in a scoped SameSite cookie, and invalidated at Done, expiry, replacement or `end_handoff`. A link does not grant remote CDP access.

The profile is ephemeral (tmpfs). Cookies survive handoff and CDP disconnects, but are lost on container replacement/restart. Do not promise persistent Google login.

## Google spike boundary

On native arm64 headful Chromium with CDP attached, the fake address `wizard-spike-test@example.com` reached Google's **“Couldn’t find this account”** response. Both default flags (no `--enable-automation`) and adding `--disable-blink-features=AutomationControlled` passed that limited probe. Signed-out Cloud Console redirected to its normal Google sign-in page. This is **not** proof that a real account, password, 2FA or OAuth app creation succeeds; the owner must test those through the private handoff.
