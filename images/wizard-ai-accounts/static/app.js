"use strict";
const $ = (id) => document.getElementById(id);
let loginId = "";
let chatgptId = "";
let chatgptTimer = 0;
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
    } else if (a.id === "chatgpt-subscription") {
      renderChatGPT(li, a);
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

function renderChatGPT(li, a) {
  const row = el("div", "buttons");
  if (a.status === "connected") {
    const model = a.model ? ` (${a.model})` : "";
    li.append(el("p", "state ok", a.in_use ? `Connected. Your agent uses it${model}.` : "Connected. Your agent uses another account right now."));
    if (!a.in_use) row.append(button("Use ChatGPT", useChatGPT, true));
    row.append(button("Disconnect", disconnectChatGPT));
  } else if (a.status === "not_connected") {
    li.append(el("p", "state off", a.signing_in ? "Waiting for you to sign in" : "Not connected"));
    row.append(button("Connect", connectChatGPT, true));
  } else {
    li.append(el("p", "state bad", a.detail || "ChatGPT sign-in is not available here."));
  }
  if (row.childElementCount) li.append(row);
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

function connect() {
  return run("Starting Claude sign-in…", async () => {
    const data = await call("/api/claude/connect", {});
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
  if (!confirm("Disconnect Claude? Your agents will stop using your Claude subscription until you connect again.")) return;
  return run("Disconnecting…", async () => {
    const data = await call("/api/claude/logout", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

function test() {
  return run("Asking Claude for a one-word answer…", async () => {
    const data = await call("/api/claude/test", {});
    if (data.ok) say(`${data.message} (${data.seconds}s${data.model ? ", " + data.model : ""})`, "ok");
    else say(`Test failed: ${data.message}`, "bad");
  });
}

function stopChatGPT() {
  clearTimeout(chatgptTimer);
  chatgptId = "";
  $("chatgpt-login").hidden = true;
}

function connectChatGPT() {
  return run("Starting ChatGPT sign-in…", async () => {
    const data = await call("/api/chatgpt/connect", {});
    if (!data.ok) return say(data.message, "bad");
    chatgptId = data.login_id;
    const link = $("chatgpt-url");
    link.href = data.url;
    $("chatgpt-code").textContent = data.code;
    $("chatgpt-login").hidden = false;
    say("");
    $("chatgpt-login").scrollIntoView({ behavior: "smooth" });
    chatgptTimer = setTimeout(pollChatGPT, 5000);
  });
}

async function pollChatGPT() {
  if (!chatgptId) return;
  const data = await call("/api/chatgpt/poll", { login_id: chatgptId });
  if (data.status === "pending") {
    chatgptTimer = setTimeout(pollChatGPT, 5000);
    return;
  }
  stopChatGPT();
  say(data.message || "ChatGPT sign-in did not finish.", data.ok ? "ok" : "bad");
  await refresh();
}

function useChatGPT() {
  return run("Switching your agent to ChatGPT…", async () => {
    const data = await call("/api/chatgpt/use", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

function disconnectChatGPT() {
  if (!confirm("Disconnect ChatGPT? Your agents will stop using your ChatGPT subscription until you connect again.")) return;
  return run("Disconnecting…", async () => {
    const data = await call("/api/chatgpt/logout", {});
    say(data.message, data.ok ? "ok" : "bad");
  });
}

$("chatgpt-cancel").addEventListener("click", async () => {
  stopChatGPT();
  await call("/api/chatgpt/cancel", {});
  say("");
  await refresh();
});

$("code-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const code = $("code").value.trim();
  if (!code) return;
  run("Checking the code with Claude…", async () => {
    const data = await call("/api/claude/code", { login_id: loginId, code });
    $("login").hidden = true;
    loginId = "";
    $("code").value = "";
    say(data.ok ? "Connected. Press Test to check it works." : data.message, data.ok ? "ok" : "bad");
  });
});

$("cancel").addEventListener("click", async () => {
  $("login").hidden = true;
  loginId = "";
  await call("/api/claude/cancel", {});
  say("");
});

refresh();
