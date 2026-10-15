"use strict";
const $ = (id) => document.getElementById(id);
let loginId = "";
let busy = false;
let timer = null;

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
    const li = el("li", "row");
    li.append(el("div", "name", a.name), el("div", "detail", a.detail || ""));
    const row = el("div", "buttons");
    if (a.status === "connected") {
      const who = a.account ? ` (${a.account})` : "";
      li.append(el("p", "state ok", `Connected${who}`));
      li.append(el("p", "state", a.in_use ? `Your agent uses ChatGPT${a.model ? " (" + a.model + ")" : ""}.`
        : "Your agent uses another account right now."));
      if (!a.in_use) row.append(button("Use ChatGPT", useIt, true));
      row.append(button("Disconnect", disconnect));
    } else if (a.status === "not_connected") {
      li.append(el("p", "state off", "Not connected"));
      row.append(button("Connect", connect, true));
    } else {
      li.append(el("p", "state bad", a.problem || "Something is wrong with this app."));
    }
    if (row.childElementCount) li.append(row);
    list.append(li);
  }
}

async function refresh() {
  const data = await call("/api/accounts");
  if (data.accounts) render(data.accounts);
}

async function run(text, fn) {
  busy = true;
  say(text);
  await refresh();
  try { await fn(); } finally { busy = false; await refresh(); }
}

function stopPolling() {
  if (timer) clearTimeout(timer);
  timer = null;
}

async function pollOnce() {
  if (!loginId) return;
  const data = await call("/api/chatgpt/poll", { login_id: loginId });
  if (data.status === "pending") { timer = setTimeout(pollOnce, 3000); return; }
  stopPolling();
  loginId = "";
  $("login").hidden = true;
  say(data.message, data.ok ? "ok" : "bad");
  await refresh();
}

function connect() {
  return run("Asking ChatGPT for a sign-in code…", async () => {
    const data = await call("/api/chatgpt/connect", {});
    if (!data.ok) return say(data.message, "bad");
    loginId = data.login_id;
    $("login-url").href = data.url;
    $("code").textContent = data.code;
    $("login").hidden = false;
    say("Waiting for you to approve the code on ChatGPT…");
    stopPolling();
    timer = setTimeout(pollOnce, 3000);
  });
}

function useIt() {
  if (!confirm("Switch your agent to ChatGPT for new chats?")) return;
  return run("Switching…", async () => {
    const data = await call("/api/chatgpt/use", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

function disconnect() {
  if (!confirm("Disconnect ChatGPT? Your agent stops using your ChatGPT subscription until you connect again.")) return;
  return run("Disconnecting…", async () => {
    const data = await call("/api/chatgpt/logout", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

$("cancel").addEventListener("click", async () => {
  stopPolling();
  $("login").hidden = true;
  loginId = "";
  await call("/api/chatgpt/cancel", {});
  say("");
});

refresh();
