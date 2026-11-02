"use strict";
const $ = (id) => document.getElementById(id);
let loginId = "";
let busy = false;

function say(text, kind) {
  const m = $("message");
  m.textContent = text || "";
  m.className = kind || "";
}

// Browser boundary (draft, default-off): inside Wizard's opaque frame (origin null) this page has no route to its own
// api/. It reads and steps through Wizard's typed operations; Connect and Disconnect are confirmed by the owner in
// Wizard's own dialog, and Wizard alone opens the Claude sign-in page. Same-origin and standalone: unchanged.
const OPAQUE = (() => { try { return parent !== window && globalThis.origin === "null"; } catch (_) { return true; } })();
let signin = null;
const connected = () => new Promise((resolve) => {
  if (window.WizBoundaryClient?.ready) return resolve(true);
  addEventListener("wizard:boundary:connected", () => resolve(true), { once: true });
  setTimeout(() => resolve(!!window.WizBoundaryClient?.ready), 8000);
});
async function boundary(path, body) {
  await connected();
  for (let i = 0; i < 40 && !window.WizardApp?.intent; i++) await new Promise((r) => setTimeout(r, 50));
  if (!window.WizardApp?.intent) return { ok: false, message: "Wizard is not connected to this page. Reopen the app." };
  const key = () => crypto.randomUUID();
  const fail = (e) => ({ ok: false, message: e.code === "cancelled" ? "" : e.code === "rate_limited" ? "Too many requests. Wait a minute." : "That did not go through. Try again." , cancelled: e.code === "cancelled" });
  try {
    if (path === "api/accounts") return await WizardApp.data.call({ operation: "claude_code.status", args: {} });
    if (path === "api/claude/connect") {
      const d = await WizardApp.intent.confirm({ operation: "claude_code.connect", args: {}, operationKey: key() });
      signin = d.signin || null;
      return { ok: d.ok, login_id: d.loginId, url: "#", message: d.message };
    }
    if (path === "api/claude/code") return await WizardApp.data.call({ operation: "claude_code.code", args: { loginId: body.login_id, code: body.code }, operationKey: key() });
    if (path === "api/claude/logout") return await WizardApp.intent.confirm({ operation: "claude_code.logout", args: {}, operationKey: key() });
    if (path === "api/claude/cancel") return await WizardApp.data.call({ operation: "claude_code.cancel", args: {}, operationKey: key() });
    if (path === "api/claude/test") return await WizardApp.data.call({ operation: "claude_code.test", args: {}, operationKey: key() });
  } catch (e) { return fail(e); }
  return { ok: false, message: "Not available here." };
}

async function call(path, body) {
  if (OPAQUE) return boundary(path, body);
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  let data = {};
  try { data = await res.json(); } catch (_) { data = { ok: false, message: "No answer from the app." }; }
  return data;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function button(label, onClick, primary) {
  const b = el("button", primary ? "primary" : "", label);
  b.type = "button";
  b.disabled = busy;
  b.addEventListener("click", onClick);
  return b;
}

function render(accounts) {
  const list = $("accounts");
  list.replaceChildren();
  for (const a of accounts) {
    const li = el("li", a.status === "coming_soon" ? "row soon" : "row");
    li.append(el("div", "name", a.name), el("div", "detail", a.detail || ""));
    if (a.status === "coming_soon") {
      li.append(el("p", "state", "Coming soon"));
    } else if (a.status === "connected") {
      const who = a.account ? ` (${a.account})` : "";
      li.append(el("p", "state ok", `Connected as ${a.plan}${who}`));
      if (a.detail && a.plan === "Not a Claude subscription") li.append(el("p", "state bad", a.detail));
      const row = el("div", "buttons");
      row.append(button("Test", test, true), button("Disconnect", disconnect));
      li.append(row);
    } else if (a.status === "not_connected") {
      li.append(el("p", "state off", "Not connected"));
      const row = el("div", "buttons");
      row.append(button("Connect", connect, true), button("Test", test));
      li.append(row);
    } else {
      li.append(el("p", "state bad", a.detail || "Something is wrong with this app."));
    }
    list.append(li);
  }
}

// ?connect=1 (the Wizard Welcome, or Connect on a fresh Wizard): just the sign-in link and the code box (Miguel, 30 Oct
// 2026: "a link and a place to paste the code; all the steps in between are unnecessary"). It starts by itself.
const FOCUS = new URLSearchParams(location.search).get("connect") === "1";
if (FOCUS) document.body.classList.add("focus");
let started = false;

async function refresh() {
  const data = await call("api/accounts");
  if (data.accounts) render(data.accounts);
  if (FOCUS && !started && !busy && (data.accounts || []).some((a) => a.status === "not_connected")) {
    started = true;
    connect();
  }
}

async function run(text, fn) {
  busy = true;
  say(text);
  await refresh();
  try { await fn(); } finally { busy = false; await refresh(); }
}

function connect() {
  return run("Starting Claude sign-in…", async () => {
    const data = await call("api/claude/connect", {});
    if (data.cancelled) return say("");
    if (!data.ok) return say(data.message, "bad");
    loginId = data.login_id;
    const link = $("login-url");
    link.href = data.url;
    link.textContent = "Open the Claude sign-in page";
    $("code").value = "";
    $("login").hidden = false;
    say("");
    $("login").scrollIntoView({ behavior: "smooth" });
  });
}

function disconnect() {
  // In Wizard's opaque frame the owner confirms in Wizard's own dialog instead (confirm() cannot run there).
  if (!OPAQUE && !confirm("Disconnect Claude? Your agents will stop using your Claude subscription until you connect again.")) return;
  return run("Disconnecting…", async () => {
    const data = await call("api/claude/logout", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

function test() {
  return run("Asking Claude for a one-word answer…", async () => {
    const data = await call("api/claude/test", {});
    if (data.ok) say(`${data.message} (${data.seconds}s${data.model ? ", " + data.model : ""})`, "ok");
    else say(`Test failed: ${data.message}`, "bad");
  });
}

$("code-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const code = $("code").value.trim();
  if (!code) return;
  run("Checking the code with Claude…", async () => {
    const data = await call("api/claude/code", { login_id: loginId, code });
    $("login").hidden = true;
    loginId = "";
    $("code").value = "";
    if (FOCUS && data.ok) return say("Claude is connected.", "ok");
    // A sign-in is single use: a wrong code gets a fresh link, and the reason stays on screen.
    if (FOCUS && !data.ok) { setTimeout(() => connect().then(() => say(data.message, "bad")), 0); return; }
    say(data.ok ? "Connected. Press Test to check it works." : data.message, data.ok ? "ok" : "bad");
  });
});

// Opaque frame: the link has no URL; Wizard opens the reviewed Claude sign-in page after the owner confirms it there.
$("login-url").addEventListener("click", async (ev) => {
  if (!OPAQUE) return;
  ev.preventDefault();
  if (!signin || !loginId) return;
  try { await WizardApp.intent.open({ target: signin, ref: "cc:" + loginId }); }
  catch (e) { if (e.code !== "cancelled") say("Could not open the sign-in page.", "bad"); }
});

$("cancel").addEventListener("click", async () => {
  $("login").hidden = true;
  loginId = "";
  await call("api/claude/cancel", {});
  say("");
});

refresh();
