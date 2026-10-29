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
</style>
</head>
<body>
<header>
  <h1>Nexus</h1>
  <span id="status">connecting…</span>
</header>

<main id="log"></main>

<form id="form">
  <input id="prompt" autocomplete="off" autofocus
         placeholder="Ask anything… prefix !ultra for cloud, /skill name to run a skill">
  <button id="send" type="submit">Send</button>
</form>
<div class="hint">Requests stay local unless a cloud burst is explicitly approved.</div>

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
      s.model.path + (s.local_only ? "\nlocal-only mode" : "\ncloud burst enabled");
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

refreshStatus();
</script>
</body>
</html>
"""
