/* Camera AI — test GUI frontend logic */
"use strict";

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const resultsEl = document.getElementById("results");
const statusEl = document.getElementById("status");
const confInput = document.getElementById("conf");
const confValue = document.getElementById("confValue");

confInput.addEventListener("input", () => {
  confValue.textContent = parseFloat(confInput.value).toFixed(2);
});

/* ---- Status ---- */
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const verEl = document.getElementById("ver");
    if (verEl) verEl.textContent = data.version ? "v" + data.version : "";
    statusEl.classList.add("ok");
    const parts = [`YOLO ${data.yolo_model}`];
    if (data.llm_backend === "ollama") {
      const model = data.llm_model ? `LLM: ${data.llm_model}` : "LLM: online";
      parts.push(data.ollama_available ? model : "LLM: offline");
      const llmCb = document.getElementById("useLlm");
      if (!data.ollama_available) {
        llmCb.checked = false;
        llmCb.disabled = true;
        llmCb.title = "Ollama är inte igång — LLM-beskrivning avstängd";
      }
    } else {
      parts.push("LLM: off");
      statusEl.classList.remove("ok");
      statusEl.classList.add("warn");
    }
    statusEl.innerHTML = `<span class="dot"></span> ${parts.join(" · ")}`;
  } catch {
    statusEl.classList.add("err");
    statusEl.innerHTML = `<span class="dot"></span> server unreachable`;
  }
}
checkHealth();

/* ---- HA status ---- */
const haStatusEl = document.getElementById("haStatus");

async function checkHa() {
  try {
    const res = await fetch("/api/ha/status");
    const data = await res.json();
    if (!data.enabled) {
      haStatusEl.classList.add("warn");
      haStatusEl.innerHTML = `<span class="dot"></span> HA off`;
    } else if (data.connected) {
      haStatusEl.classList.add("ok");
      haStatusEl.innerHTML = `<span class="dot"></span> HA · ${data.transport}`;
    } else {
      haStatusEl.classList.add("err");
      haStatusEl.innerHTML = `<span class="dot"></span> HA not connected`;
    }
  } catch {
    haStatusEl.classList.add("err");
    haStatusEl.innerHTML = `<span class="dot"></span> HA unknown`;
  }
}
checkHa();

/* ---- LLM-minne status (keep_alive) ---- */
const llmMemStatusEl = document.getElementById("llmMemStatus");

async function checkConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    llmMemStatusEl.classList.remove("ok", "warn", "err");
    if (!data.ollama_available) {
      llmMemStatusEl.classList.add("warn");
      llmMemStatusEl.innerHTML = `<span class="dot"></span> LLM offline`;
      return;
    }
    const ka = data.keep_alive;
    let label;
    let cls = "warn";
    if (ka === "-1" || ka === -1) {
      label = "LLM i minne (alltid)";
      cls = "ok";
    } else if (ka === "0" || ka === 0) {
      label = "LLM urladdad";
    } else if (ka === null || ka === undefined || ka === "") {
      label = "LLM: default (5 min)";
    } else {
      const secs = parseInt(ka, 10);
      label = `LLM i minne: ${Math.round(secs / 60)} min`;
      cls = "ok";
    }
    llmMemStatusEl.classList.add(cls);
    llmMemStatusEl.innerHTML = `<span class="dot"></span> ${label}`;
  } catch {
    llmMemStatusEl.classList.add("err");
    llmMemStatusEl.innerHTML = `<span class="dot"></span> LLM-minne ?`;
  }
}
checkConfig();

/* Uppdatera statusarna var 15:e sekund */
setInterval(() => { checkHealth(); checkHa(); checkConfig(); }, 15000);

/* ---- Inställningar: ladda sparade värden + spara ---- */
const saveBtn = document.getElementById("saveSettings");
const saveMsg = document.getElementById("saveMsg");

async function loadSettings() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    if (cfg.model) document.getElementById("model").value = cfg.model;
    if (cfg.llm_model) document.getElementById("llmModel").value = cfg.llm_model;
    if (cfg.conf != null) {
      confInput.value = cfg.conf;
      confValue.textContent = parseFloat(cfg.conf).toFixed(2);
    }
    if (cfg.prompt) document.getElementById("prompt").value = cfg.prompt;
    const kaEl = document.getElementById("keepAlive");
    if (kaEl && cfg.keep_alive != null && cfg.keep_alive !== "") kaEl.value = String(cfg.keep_alive);
  } catch { /* server offline - behåll GUI:s standardvärden */ }
}

/* Fyll LLM-rullgardinen med nedladdade Ollama-modeller och välj den aktiva */
async function loadLlmModelOptions() {
  try {
    const [resModels, resCfg] = await Promise.all([
      fetch("/api/ollama/models"),
      fetch("/api/config"),
    ]);
    const data = await resModels.json();
    const cfg = await resCfg.json();
    const sel = document.getElementById("llmModel");
    // Den konfigurerade modellen (från servern) ska alltid visas/varas vald
    const current = String(cfg.llm_model || sel.value || "moondream");
    const models = [...new Set((data.models || []).map((m) => m.replace(/:latest$/, "")))];
    if (!models.includes(current)) models.unshift(current);
    sel.innerHTML = models.map((m) => `<option value="${m}">${m}</option>`).join("");
    sel.value = current;
  } catch { /* behåll fältet tomt om Ollama inte nås */ }
}

async function saveSettings(auto) {
  const body = {
    model: document.getElementById("model").value,
    llm_model: document.getElementById("llmModel").value.trim(),
    conf: parseFloat(confInput.value),
    prompt: document.getElementById("prompt").value,
    keep_alive: document.getElementById("keepAlive").value,
  };
  if (!auto) saveMsg.textContent = "Sparar …";
  saveMsg.classList.remove("ok");
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const cfg = await res.json();
    saveMsg.textContent = auto
      ? "💾 Sparat"
      : `💾 Sparat: ${cfg.model} · conf ${cfg.conf} · sparas i .env`;
    saveMsg.classList.add("ok");
    // Uppdatera toppstatus direkt så LLM i toppen ändras på en gång
    checkHealth();
    checkConfig();
  } catch (e) {
    saveMsg.textContent = "❌ Kunde inte spara: " + e.message;
  }
}

saveBtn.addEventListener("click", () => saveSettings(false));

/* Auto-spara med debounce - så prompten/inställningarna sitter kvar efter F5/omstart */
let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveSettings(true), 800);
}
document.getElementById("prompt").addEventListener("input", scheduleSave);
document.getElementById("model").addEventListener("change", scheduleSave);
document.getElementById("llmModel").addEventListener("change", scheduleSave);
document.getElementById("keepAlive").addEventListener("change", scheduleSave);
confInput.addEventListener("input", scheduleSave);

loadSettings();
loadLlmModelOptions();

/* ---- Ollama-modeller: lista + ladda ner + status ---- */
const RECOMMENDED_MODELS = [
  { name: "moondream", desc: "1.9B — snabb & liten (standard)" },
  { name: "minicpm-v", desc: "~8B — bra kvalitet för storleken" },
  { name: "llava", desc: "~7B — klassisk visionmodell" },
  { name: "llama3.2-vision", desc: "~11B — bästa kvalitet" },
];
const modelListEl = document.getElementById("modelList");
const pullStatusEl = document.getElementById("pullStatus");
const pullTextEl = document.getElementById("pullText");
const pullBarEl = document.getElementById("pullBar");
let pullTimer = null;

async function loadModels() {
  try {
    const res = await fetch("/api/ollama/models");
    const data = await res.json();
    if (data.ollama_error) {
      modelListEl.innerHTML = `<p class="empty" style="color: var(--red)">⚠️ Ollama nås inte: ${escapeHtml(data.ollama_error)}</p>`;
      return;
    }
    const installed = new Set(data.models || []);
    const rows = RECOMMENDED_MODELS.map((m) => {
      const isIn = installed.has(m.name) || installed.has(m.name + ":latest");
      if (isIn) {
        return `<div class="model-row installed"><span>✅ <strong>${m.name}</strong></span><small>${m.desc} · installerad</small></div>`;
      }
      return `<div class="model-row"><span><strong>${m.name}</strong></span><small>${m.desc}</small><button class="btn" data-model="${m.name}">⬇️ Ladda ner</button></div>`;
    }).join("");
    modelListEl.innerHTML = rows || `<p class="empty">Inga modeller listade.</p>`;
    modelListEl.querySelectorAll("button[data-model]").forEach((b) =>
      b.addEventListener("click", () => startPull(b.dataset.model))
    );
  } catch {
    modelListEl.innerHTML = `<p class="empty">Kunde inte nå servern/Ollama.</p>`;
  }
}

async function startPull(model) {
  try {
    const res = await fetch("/api/ollama/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    const data = await res.json();
    pullStatusEl.hidden = false;
    if (data.started === false) {
      pullTextEl.textContent = "⚠️ " + (data.reason || "Kunde inte starta nedladdning.");
      pullBarEl.style.width = "0%";
      return;
    }
    pollPull();
  } catch (e) {
    pullTextEl.textContent = "❌ Kunde inte starta nedladdning: " + e.message;
    pullStatusEl.hidden = false;
  }
}

async function pollPull() {
  clearTimeout(pullTimer);
  try {
    const res = await fetch("/api/ollama/pull/status");
    const st = await res.json();
    pullStatusEl.hidden = false;
    if (st.state === "running") {
      pullTextEl.textContent = `⏳ Laddar ner ${st.model} … ${st.percent}%`;
      pullBarEl.style.width = (st.percent || 0) + "%";
      pullTimer = setTimeout(pollPull, 2000);
    } else if (st.state === "completed") {
      pullTextEl.textContent = `✅ ${st.model} klar!`;
      pullBarEl.style.width = "100%";
      setTimeout(() => { pullStatusEl.hidden = true; }, 5000);
      loadModels();
      loadLlmModelOptions();
    } else if (st.state === "failed") {
      pullTextEl.textContent = `❌ ${st.model}: ${st.error || "misslyckades"}`;
      pullBarEl.style.width = "0%";
    } else {
      pullTextEl.textContent = "Ingen nedladdning pågår. Kontrollera att Ollama körs.";
      pullBarEl.style.width = "0%";
    }
  } catch {
    pullTextEl.textContent = "Kunde inte hämta status (serverprocessen kan vara gammal - starta om via install.ps1).";
  }
}

document.getElementById("refreshModels").addEventListener("click", loadModels);
loadModels();

/* ---- Upload handling ---- */
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => handleFiles(fileInput.files));

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); })
);
dropzone.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));

/* ---- Analysis ---- */
async function handleFiles(files) {
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    const card = createPendingCard(file.name);
    try {
      const data = await analyzeFile(file);
      renderResult(card, data);
    } catch (err) {
      renderError(card, err.message || "Analysis failed");
    }
  }
}

function analyzeFile(file) {
  const form = new FormData();
  form.append("file", file);
  form.append("model", document.getElementById("model").value);
  form.append("conf", parseFloat(confInput.value));
  form.append("use_llm", document.getElementById("useLlm").checked ? "true" : "false");
  form.append("prompt", document.getElementById("prompt").value);
  form.append("use_ha", document.getElementById("useHa").checked ? "true" : "false");

  return fetch("/api/analyze", { method: "POST", body: form }).then(async (res) => {
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  });
}

/* ---- Rendering ---- */
function createPendingCard(name) {
  const card = document.createElement("div");
  card.className = "result";
  card.innerHTML = `
    <div class="analyzing"><span class="spinner"></span> Analyzing <strong>${escapeHtml(name)}</strong>…</div>
  `;
  resultsEl.prepend(card);
  return card;
}

function renderResult(card, data) {
  if (data.error) {
    card.innerHTML = `<div class="error-banner">❌ ${escapeHtml(data.error)}</div>`;
    return;
  }

  const dets = data.detections || [];
  const detHtml = dets.length
    ? `<ul class="detection-list">${dets
        .map(
          (d) =>
            `<li><span>${escapeHtml(d.class)}${d.color ? ` · ${escapeHtml(d.color)}` : ""}</span><span class="conf">${(d.confidence * 100).toFixed(0)}%</span></li>`
        )
        .join("")}</ul>`
    : `<p class="empty">No objects detected at this confidence.</p>`;

  const llmHtml = data.description && data.description !== data.summary
    ? `<div class="llm-box"><span class="tag">LLM</span><p>${escapeHtml(data.description)}</p></div>`
    : data.llm_error
    ? `<div class="llm-err">⚠️ ${escapeHtml(data.llm_error)}</div>`
    : "";

  const summaryHtml = data.summary
    ? `<div class="llm-box summary"><span class="tag">Sammanfattning</span><p>${escapeHtml(data.summary)}</p></div>`
    : "";

  const haHtml = data.ha_error
    ? `<div class="llm-err">🏠 ${escapeHtml(data.ha_error)}</div>`
    : "";

  card.innerHTML = `
    <div class="meta">
      <span>${data.detections.length} object(s)</span>
      <span>${data.model} · ${data.inference_ms} ms</span>
    </div>
    <img src="${data.annotated_url}" alt="annotated" />
    <div class="body">
      <h3>Detections</h3>
      ${summaryHtml}
      ${detHtml}
      ${llmHtml}
      ${haHtml}
    </div>
  `;
}

function renderError(card, message) {
  card.innerHTML = `<div class="error-banner">❌ ${escapeHtml(message)}</div>`;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---- Stats & history ---- */
function statCard(label, value) {
  return `<div class="stat-card"><span class="stat-label">${escapeHtml(label)}</span><span class="stat-value">${escapeHtml(String(value))}</span></div>`;
}

async function loadStats() {
  const box = document.getElementById("statsBox");
  try {
    const [s, h] = await Promise.all([
      fetch("/api/stats").then((r) => r.json()),
      fetch("/api/history?limit=15").then((r) => r.json()),
    ]);

    let html = `<div class="stat-grid">`;
    html += statCard("Analyser", s.total_analyses);
    html += statCard("Detektioner", s.total_detections);
    html += statCard("Personer", s.people);
    html += statCard("Djur", s.animals);
    html += statCard("Bilar", s.vehicles);
    html += statCard("Färger", s.colors && s.colors.length ? s.colors.join(", ") : "—");
    html += statCard("Snitt-tid", `${s.avg_inference_ms} ms`);
    html += `</div>`;

    html += `<div class="stat-cameras">`;
    for (const [cam, n] of Object.entries(s.per_camera || {})) {
      html += `<span class="chip">📷 ${escapeHtml(cam)}: ${n}</span>`;
    }
    html += `<span class="chip">${escapeHtml(s.model)} · conf ${s.conf} · ${escapeHtml(s.device)}</span>`;
    html += `</div>`;

    html += `<table class="hist-table"><thead><tr><th>Tid</th><th>Kamera</th><th>Sammanfattning</th><th>ms</th></tr></thead><tbody>`;
    for (const item of h) {
      const t = new Date(item.ts * 1000).toLocaleTimeString("sv-SE");
      html += `<tr><td>${t}</td><td>${escapeHtml(item.camera)}</td><td>${escapeHtml(item.summary)}</td><td>${item.inference_ms}</td></tr>`;
    }
    html += `</tbody></table>`;
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = `<p class="empty">Kunde inte hämta statistik.</p>`;
  }
}

document.getElementById("statsBtn").addEventListener("click", loadStats);
loadStats();
