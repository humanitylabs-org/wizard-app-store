"use strict";
const $ = (id) => document.getElementById(id);
let loginId = "";
let busy = false;

function say(text, kind) {
  const m = $("message");
  m.textContent = text || "";
  m.className = kind || "";
}

async function call(path, body) {
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
      // The sign-in ends on a fixed date (about four weeks after Connect); warn 5 days ahead with Reconnect.
      // A one-year sign-in (claude-connection#27) says until when and warns from 14 days.
      const soon = signinSoon(a);
      if (a.signin_expires_at) li.append(el("p", soon ? "state bad signin" : "state signin", signinText(a.signin_expires_at, a.signin_kind, soon) + (soon ? ": reconnect before then or your agent stops answering with it." : "")));
      const swap = !soon && a.one_year_signin === true && a.signin_kind !== "one_year";
      if (swap) li.append(el("p", "state signin", "One-year sign-in is on: press Reconnect to sign in for a year instead of about four weeks."));
      const row = el("div", "buttons");
      if (soon || swap) row.append(button("Reconnect", connect, true));
      row.append(button("Test", test, !soon && !swap), button("Disconnect", disconnect));
      li.append(row);
    } else if (a.status === "expired") {
      li.append(el("p", "state bad", a.message || "The Claude sign-in has ended. Press Reconnect to sign in again."));
      const row = el("div", "buttons");
      row.append(button("Reconnect", connect, true), button("Disconnect", disconnect));
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

function signinSoon(a) {
  return Boolean(a.signin_expires_at) && a.signin_days_left <= (a.signin_warn_days ?? 5);
}

function signinText(at, kind, soon) {
  const left = Date.parse(at) - Date.now(), day = 864e5;
  if (!(left > 0)) return "Sign-in has ended";
  const when = left >= 2 * day ? `in ${Math.floor(left / day)} days` : left >= day ? "in 1 day" : left < 1.5 * 36e5 ? "in 1 hour" : `in ${Math.round(left / 36e5)} hours`;
  if (kind === "one_year") return soon ? `One-year sign-in ends ${when}` : `Signed in until ${new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;
  return `Sign-in renews ${when}`;
}

// ?connect=1 (the Wizard Welcome, or Connect on a fresh Wizard): just the sign-in link and the code box (Miguel, 30 Oct
// 2026: "a link and a place to paste the code; all the steps in between are unnecessary"). It starts by itself.
const FOCUS = new URLSearchParams(location.search).get("connect") === "1";
// ?connect=1&year=1 (the main page's "Sign in for a year"): also starts for a working four-week sign-in.
const YEAR = new URLSearchParams(location.search).get("year") === "1";
if (FOCUS) document.body.classList.add("focus");
let started = false;

async function refresh() {
  const data = await call("api/accounts");
  if (data.accounts) render(data.accounts);
  if (FOCUS && !started && !busy && (data.accounts || []).some((a) => a.status === "not_connected" || a.status === "expired" || (a.status === "connected" && signinSoon(a)) ||
      (YEAR && a.status === "connected" && a.one_year_signin === true && a.signin_kind !== "one_year"))) {
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
    if (!data.ok) return say(data.message, "bad");
    loginId = data.login_id;
    const link = $("login-url");
    link.href = data.url;
    link.textContent = data.year ? "Open the Claude sign-in page (one-year sign-in)" : "Open the Claude sign-in page";
    $("code").value = "";
    $("login").hidden = false;
    say("");
    $("login").scrollIntoView({ behavior: "smooth" });
  });
}

function disconnect() {
  if (!confirm("Disconnect Claude? Your agents will stop using your Claude subscription until you connect again.")) return;
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

$("cancel").addEventListener("click", async () => {
  $("login").hidden = true;
  loginId = "";
  await call("api/claude/cancel", {});
  say("");
});

refresh();
