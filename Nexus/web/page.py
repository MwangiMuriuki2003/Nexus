"""Single-page HTML shell for the headless Nexus UI.

Kept as a Python string (rather than a template file) so the package needs no
extra build/packaging configuration. Everything dynamic arrives via the JSON API,
so the page has no placeholders to fill in.
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/jpeg" href="/favicon.png">
<title>Nexus — Private Desktop Brain</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; height: 100vh; display: flex; flex-direction: column;
    background: #0f1115; color: #e6e6e6;
    font: 15px/1.5 ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
  }
  header {
    display: flex; align-items: center; gap: .75rem;
    padding: .7rem 1rem; background: #141821; border-bottom: 1px solid #262b36;
  }
  h1 { margin: 0; font-size: 1rem; font-weight: 600; }
  #status {
    font-size: .78rem; padding: .15rem .55rem; border-radius: 999px;
    background: #2a2f3a; color: #aab;
  }
  #status.ready { background: #12351f; color: #6ee7a0; }
  #status.warn  { background: #3a2a12; color: #f0b060; }
  main {
    flex: 1; overflow-y: auto; padding: 1rem;
    display: flex; flex-direction: column; gap: .7rem;
  }
  .msg {
    max-width: 72ch; padding: .6rem .8rem; border-radius: 10px;
    white-space: pre-wrap; overflow-wrap: anywhere;
  }
  .user { align-self: flex-end; background: #1d4ed8; color: #fff; }
  .bot  { align-self: flex-start; background: #1a1f29; border: 1px solid #262b36; }
  .error { align-self: flex-start; background: #2b1518; border: 1px solid #5b2228; color: #ffb4b4; }
  .meta {
    font-size: .68rem; letter-spacing: .08em; text-transform: uppercase;
    opacity: .55; margin-bottom: .2rem;
  }
  form {
    display: flex; gap: .5rem; padding: .75rem 1rem;
    background: #141821; border-top: 1px solid #262b36;
  }
  input {
    flex: 1; padding: .6rem .75rem; border-radius: 8px;
    border: 1px solid #2c3341; background: #0f1115; color: inherit; font: inherit;
  }
  input:focus { outline: 2px solid #1d4ed8; outline-offset: 1px; }
  button {
    padding: .6rem 1.1rem; border: 0; border-radius: 8px;
    background: #1d4ed8; color: #fff; font: inherit; cursor: pointer;
  }
  button:disabled { opacity: .5; cursor: default; }
  .hint { padding: 0 1rem .6rem; font-size: .75rem; opacity: .45; }
  .ghost {
    background: transparent; border: 1px solid #2c3341; color: #aab;
    padding: .35rem .7rem; font-size: .78rem;
  }
  .ghost:hover:not(:disabled) { border-color: #1d4ed8; color: #fff; }
  .danger { background: #5b2228; color: #ffd7d7; }
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 10;
    display: flex; align-items: center; justify-content: center; padding: 1rem;
  }
  .overlay[hidden] { display: none; }  /* beats the flex rule above */
  .panel {
    background: #141821; border: 1px solid #2c3341; border-radius: 12px;
    padding: 1.1rem 1.2rem; width: min(460px, 100%);
    display: flex; flex-direction: column; gap: .7rem;
  }
  .panel h2 { margin: 0; font-size: 1rem; }
  .panel label { display: flex; flex-direction: column; gap: .3rem; font-size: .78rem; color: #aab; }
  .panel select {
    padding: .55rem .6rem; border-radius: 8px; border: 1px solid #2c3341;
    background: #0f1115; color: inherit; font: inherit;
  }
  .panel .row { display: flex; gap: .5rem; align-items: center; }
  .panel .note { margin: 0; font-size: .72rem; opacity: .55; }
  #setFeedback { margin: 0; font-size: .78rem; min-height: 1em; color: #ff9b9b; }
</style>
</head>
<body>
<header>
  <h1>Nexus</h1>
  <span id="status">connecting…</span>
  <span style="flex:1"></span>
  <button id="settingsBtn" class="ghost" type="button">Settings</button>
</header>

<main id="log"></main>

<form id="form">
  <input id="prompt" autocomplete="off" autofocus
         placeholder="Ask anything… prefix !ultra for cloud, /skill name to run a skill">
  <button id="send" type="submit">Send</button>
</form>
<div class="hint">Requests stay local unless a cloud burst is explicitly approved.</div>

<div class="overlay" id="settingsOverlay" hidden>
  <div class="panel" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
    <h2 id="settingsTitle">Settings</h2>
    <label>Provider
      <select id="setProvider">
        <option value="nebius">Nebius Token Factory (default)</option>
        <option value="custom">Custom — any OpenAI-compatible endpoint</option>
      </select>
    </label>
    <label>Base URL
      <input id="setBaseUrl" autocomplete="off" placeholder="https://api.studio.nebius.com/v1/">
    </label>
    <label>Model
      <input id="setModel" autocomplete="off" placeholder="nvidia/Nemotron-3-Ultra-550B">
    </label>
    <label>API key (bring your own)
      <input id="setKey" type="password" autocomplete="new-password" placeholder="paste a key to store it">
    </label>
    <p class="note" id="setKeyStatus">…</p>
    <div class="row">
      <button id="setRemove" class="ghost danger" type="button">Remove key</button>
      <span style="flex:1"></span>
      <button id="setCancel" class="ghost" type="button">Cancel</button>
      <button id="setSave" type="button">Save</button>
    </div>
    <p id="setFeedback"></p>
    <p class="note">The key is kept in this device's credential store and only leaves it
       when you explicitly approve a cloud request.</p>
  </div>
</div>

<script>
const log = document.getElementById("log");
const statusEl = document.getElementById("status");
const form = document.getElementById("form");
const input = document.getElementById("prompt");
const sendBtn = document.getElementById("send");

// Friendly intent labels; plain chat gets no label at all.
const INTENT_LABELS = {
  chat: "",
  memory_query: "memory",
  cloud_burst: "cloud",
  skill_exec: "skill",
};

function intentLabel(intent) {
  return Object.prototype.hasOwnProperty.call(INTENT_LABELS, intent)
    ? INTENT_LABELS[intent]
    : intent;
}

function addMessage(kind, text, meta) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + kind;
  if (meta) {
    const label = document.createElement("div");
    label.className = "meta";
    label.textContent = meta;
    wrap.appendChild(label);
  }
  const body = document.createElement("div");
  body.textContent = text;  // textContent: model output is never treated as HTML
  wrap.appendChild(body);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return wrap;
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const s = await res.json();
    if (s.model.loaded) {
      statusEl.textContent = "local model loaded";
      statusEl.className = "ready";
    } else if (s.model.present) {
      statusEl.textContent = "model present — loads on first message";
      statusEl.className = "";
    } else {
      statusEl.textContent = "no local model";
      statusEl.className = "warn";
    }
    statusEl.title =
      s.model.path + (s.local_only ? "\\nlocal-only mode" : "\\ncloud burst enabled");
  } catch (err) {
    statusEl.textContent = "server unreachable";
    statusEl.className = "warn";
  }
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  input.value = "";
  addMessage("user", message, "you");
  sendBtn.disabled = true;
  const pending = addMessage("bot", "…", "nexus");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    pending.remove();
    if (res.ok) {
      addMessage("bot", data.response, intentLabel(data.intent));
      refreshStatus();
    } else {
      addMessage("error", data.error || ("request failed (" + res.status + ")"), "error");
    }
  } catch (err) {
    pending.remove();
    addMessage("error", String(err), "error");
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});

// --- Settings: bring your own key + endpoint preferences -------------------
const overlay = document.getElementById("settingsOverlay");
const setProvider = document.getElementById("setProvider");
const setBaseUrl = document.getElementById("setBaseUrl");
const setModel = document.getElementById("setModel");
const setKey = document.getElementById("setKey");
const setKeyStatus = document.getElementById("setKeyStatus");
const setRemove = document.getElementById("setRemove");
const setSave = document.getElementById("setSave");
const setFeedback = document.getElementById("setFeedback");
const NEBIUS = {
  base_url: "https://api.studio.nebius.com/v1/",
  model: "nvidia/Nemotron-3-Ultra-550B",
};

function keyStatusText(s) {
  return s.key_configured
    ? "Key stored (" + (s.key_source || "unknown") + "): " + s.key_masked
    : "No key stored — cloud bursts stay disabled.";
}

function settingsFeedback(text) {
  setFeedback.textContent = text || "";
}

function closeSettings() {
  overlay.hidden = true;
}

async function openSettings() {
  settingsFeedback("");
  setKey.value = "";
  overlay.hidden = false;
  try {
    const res = await fetch("/api/settings");
    const s = await res.json();
    setProvider.value = s.provider === "custom" ? "custom" : "nebius";
    setBaseUrl.value = s.base_url || "";
    setModel.value = s.model || "";
    setKeyStatus.textContent = keyStatusText(s);
    setKey.placeholder = s.key_configured
      ? "stored key — paste a new one to replace it"
      : "paste your API key";
    setRemove.disabled = !s.key_configured;
  } catch (err) {
    settingsFeedback("Could not load settings: " + err);
  }
  setKey.focus();
}

async function postSettings(body) {
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    settingsFeedback(data.error || "save failed (" + res.status + ")");
    return null;
  }
  setKey.value = "";
  setKeyStatus.textContent = keyStatusText(data);
  setKey.placeholder = data.key_configured
    ? "stored key — paste a new one to replace it"
    : "paste your API key";
  setRemove.disabled = !data.key_configured;
  closeSettings();
  refreshStatus();
  return data;
}

document.getElementById("settingsBtn").addEventListener("click", openSettings);
document.getElementById("setCancel").addEventListener("click", closeSettings);
overlay.addEventListener("click", (ev) => { if (ev.target === overlay) closeSettings(); });
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !overlay.hidden) closeSettings();
});
setProvider.addEventListener("change", () => {
  if (setProvider.value === "nebius") {
    setBaseUrl.value = NEBIUS.base_url;
    setModel.value = NEBIUS.model;
  } else {
    setBaseUrl.value = "";
    setModel.value = "";
  }
});
setSave.addEventListener("click", async () => {
  setSave.disabled = true;
  try {
    const body = {
      provider: setProvider.value,
      base_url: setBaseUrl.value.trim(),
      model: setModel.value.trim(),
    };
    const key = setKey.value.trim();
    if (key) body.api_key = key;  // an empty field leaves the stored key alone
    await postSettings(body);
  } finally {
    setSave.disabled = false;
  }
});
setRemove.addEventListener("click", async () => {
  setRemove.disabled = true;
  try {
    await postSettings({ remove_key: true });
  } finally {
    setRemove.disabled = false;
  }
});

refreshStatus();
</script>
</body>
</html>
"""
