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
      const model = data.llm_model
        ? `LLM: ${String(data.llm_model).replace(/:latest$/, "")}`
        : "LLM: online";
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
let _llmSizes = {};
let _llmVision = new Set(); // namn som servern klassat som vision-kapabla
function llmSizeGb(name) {
  const s = _llmSizes[name] != null ? _llmSizes[name] : _llmSizes[name + ":latest"];
  return s != null ? s : null;
}
function isVisionModel(name) {
  return _llmVision.has(name) || _llmVision.has(name + ":latest");
}
function updateLlmModelHint() {
  const hint = document.getElementById("llmModelHint");
  if (!hint) return;
  const value = document.getElementById("llmModel").value;
  const size = llmSizeGb(value);
  const warnBig = size != null && size > 10;
  const notVision = value !== "" && !isVisionModel(value);
  if (!warnBig && !notVision) { hint.textContent = ""; hint.classList.remove("warn"); return; }
  hint.textContent = [
    notVision ? "⚠️ Ej vision-stöd — bildanalys kan misslyckas." : "",
    warnBig ? `⚠️ ${size} GB — väldigt stor modell, laddas troligen inte på GPU:n.` : "",
  ].filter(Boolean).join(" ");
  hint.classList.add("warn");
}
async function loadLlmModelOptions() {
  try {
    const [resModels, resCfg] = await Promise.all([
      fetch("/api/ollama/models"),
      fetch("/api/config"),
    ]);
    const data = await resModels.json();
    const cfg = await resCfg.json();
    const sel = document.getElementById("llmModel");
    _llmSizes = data.sizes || {};
    _llmVision = new Set((data.models || []).map((m) => m.replace(/:latest$/, "")));
    // Den konfigurerade modellen (från servern) ska alltid visas/varas vald
    const current = String(cfg.llm_model || sel.value || "moondream");
    const models = [..._llmVision];
    if (!models.includes(current)) models.unshift(current);
    sel.innerHTML = models
      .map((m) => {
        const size = llmSizeGb(m);
        const sizeTxt = size != null ? ` (${size} GB)` : "";
        const mark = isVisionModel(m) ? "" : " ⚠️ ej vision";
        return `<option value="${m}">${m}${sizeTxt}${mark}</option>`;
      })
      .join("");
    sel.value = current;
    updateLlmModelHint();
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
    pollYoloDownload();
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
document.getElementById("llmModel").addEventListener("change", () => {
  updateLlmModelHint();
  scheduleSave();
});
document.getElementById("keepAlive").addEventListener("change", scheduleSave);
confInput.addEventListener("input", scheduleSave);

loadSettings();
loadLlmModelOptions();

/* ---- YOLO-modell: visa när viktfilen laddas ner ---- */
const yoloDlEl = document.getElementById("yoloDlStatus");
let yoloDlTimer = null;

async function pollYoloDownload() {
  clearTimeout(yoloDlTimer);
  let st;
  try {
    const res = await fetch("/api/yolo/download/status");
    st = await res.json();
  } catch {
    yoloDlTimer = setTimeout(pollYoloDownload, 5000);
    return;
  }
  const sel = document.getElementById("model");
  const selected = sel ? sel.value : "";
  yoloDlEl.classList.remove("ok", "err", "warn");

  if (st.state === "running") {
    const p = Math.round(st.percent || 0);
    yoloDlEl.hidden = false;
    yoloDlEl.innerHTML =
      `⬇️ Laddar ner <strong>${escapeHtml(st.model || "")}</strong> … ${p}%` +
      `<span class="yolo-dl-bar"><span style="width:${p}%"></span></span>`;
    yoloDlTimer = setTimeout(pollYoloDownload, 1200);
  } else if (st.state === "completed") {
    yoloDlEl.hidden = false;
    yoloDlEl.classList.add("ok");
    yoloDlEl.innerHTML = `✅ <strong>${escapeHtml(st.model || "")}</strong> nedladdad`;
    yoloDlTimer = setTimeout(pollYoloDownload, 20000);
  } else if (st.state === "failed") {
    yoloDlEl.hidden = false;
    yoloDlEl.classList.add("err");
    yoloDlEl.innerHTML =
      `❌ <strong>${escapeHtml(st.model || "")}</strong>: ${escapeHtml(st.error || "nedladdningen misslyckades")}`;
    yoloDlTimer = setTimeout(pollYoloDownload, 6000);
  } else {
    // idle - visa bara om den valda modellen saknas lokalt
    if (st.installed === false) {
      yoloDlEl.hidden = false;
      yoloDlEl.classList.add("warn");
      yoloDlEl.innerHTML =
        `⬇️ <strong>${escapeHtml(selected)}</strong> är inte nedladdad — hämtas automatiskt vid första användning`;
    } else {
      yoloDlEl.hidden = true;
      yoloDlEl.innerHTML = "";
    }
    yoloDlTimer = setTimeout(pollYoloDownload, 4000);
  }
}
pollYoloDownload();

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

/* ---- System-knappar ---- */
async function systemAction(url, label, ask) {
  if (ask && !confirm(ask)) return;
  const msg = document.getElementById("sysMsg");
  if (msg) msg.textContent = label + " …";
  try {
    const res = await fetch(url, { method: "POST" });
    let data = {};
    try { data = await res.json(); } catch { data = { raw: (await res.text().catch(() => "")) }; }
    if (msg) msg.textContent = `${label} → ${res.ok ? "OK" : "fel " + res.status}: ` + JSON.stringify(data);
  } catch (e) {
    if (msg) msg.textContent = label + " → kunde inte nå servern: " + e.message;
  }
}
const btnUnload = document.getElementById("btnUnload");
const btnRestartServer = document.getElementById("btnRestartServer");
const btnRestartOllama = document.getElementById("btnRestartOllama");
if (btnUnload) btnUnload.addEventListener("click", () => systemAction("/api/system/unload-models", "Laddar ur modeller"));
if (btnRestartServer) btnRestartServer.addEventListener("click", () => systemAction("/api/system/restart-server", "Startar om servern", "Starta om servern? Anslutningen bryts i några sekunder."));
if (btnRestartOllama) btnRestartOllama.addEventListener("click", () => systemAction("/api/system/restart-ollama", "Startar om Ollama", "Starta om Ollama? Alla modeller töms ur GPU-minnet."));
loadStats();

/* ============================================================
   Tabs & Dashboard (live-kamera) - tillägg
   ============================================================ */
(function () {
  "use strict";
  const $id = (id) => document.getElementById(id);

  /* ---- Tabs ---- */
  function showView(name) {
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    if (name === "historik") loadStats();
    window.scrollTo({ top: 0 });
  }
  document.querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => showView(b.dataset.view))
  );
  window.__showView = showView;

  /* ---- Referenser ---- */
  const liveImg = $id("liveImg");
  const liveDot = $id("liveDot");
  const liveBadgeText = $id("liveBadgeText");
  const liveSub = $id("liveSub");
  const statusTable = $id("statusTable");
  const detNowList = $id("detNowList");
  const detNowAge = $id("detNowAge");
  const gpuWarnCard = $id("gpuWarnCard");
  const gpuWarnConfigured = $id("gpuWarnConfigured");
  const gpuWarnActual = $id("gpuWarnActual");
  const btnStreamToggle = $id("btnStreamToggle");
  const streamHint = $id("streamHint");

  const CAMERA_LABELS = { disabled: "Inaktiv", connecting: "Ansluter…", online: "Online", reconnecting: "Återansluter…", offline: "Offline", error: "Fel" };
  const YOLO_LABELS = { stopped: "Stoppad", loading: "Laddar modell…", running: "Kör", error: "Fel" };

  async function fetchJson(url, opts) {
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch (e) { /* tom */ }
    if (!res.ok) {
      const why = (data && data.errors && data.errors.join(" · ")) || (data && data.detail) || ("HTTP " + res.status);
      throw new Error(why);
    }
    return data;
  }

  function setMsg(el, text, ok) {
    if (!el) return;
    el.classList.toggle("ok", !!ok);
    el.textContent = text;
  }

  /* ---- Dashboard status ---- */
  async function pollStatus() {
    let s;
    try {
      s = await fetchJson("/api/cameras/status");
    } catch (e) {
      if (statusTable) statusTable.innerHTML = `<tr><td colspan="2" class="metric-err">Backend nås inte – försöker igen…</td></tr>`;
      return;
    }
    renderStatus(s);
  }

  function stateClass(state) {
    return state || "disabled";
  }

  function renderStatus(s) {
    // Live-bild: sätt MJPEG-källan en gång per kamera
    const name = (s.camera_name || "default").trim() || "default";
    if (liveImg && (!liveImg.dataset.src || liveImg.dataset.src !== name)) {
      liveImg.dataset.src = name;
      liveImg.src = "/api/live/" + encodeURIComponent(name);
    }

    // Badge + subtext
    let badgeText = "LIVE";
    let stCls = "online";
    if (!s.camera_enabled) { badgeText = "INAKTIV"; stCls = "disabled"; }
    else if (s.camera_state === "online") { badgeText = "LIVE " + name; stCls = "online"; }
    else if (s.camera_state === "reconnecting") { badgeText = "ÅTERANSLUTER"; stCls = "reconnecting"; }
    else if (s.camera_state === "connecting") { badgeText = "ANSLUTER"; stCls = "connecting"; }
    else { badgeText = "OFFLINE"; stCls = "offline"; }
    if (liveBadgeText) liveBadgeText.textContent = badgeText;
    if (liveDot && liveDot.parentElement) {
      liveDot.parentElement.classList.remove("online", "reconnecting", "connecting", "disabled", "offline", "error");
      liveDot.parentElement.classList.add(stCls);
    }
    if (liveSub) {
      liveSub.textContent = s.camera_state === "online"
        ? (s.resolution ? s.resolution + " · " : "") + (s.codec || "") + (s.source_fps ? " · " + s.source_fps.toFixed(1) + " FPS" : "")
        : (s.camera_detail || "");
    }

    // Start/Stopp-knapp
    if (btnStreamToggle) {
      btnStreamToggle.disabled = false;
      if (!s.camera_enabled) { btnStreamToggle.textContent = "⚙️ Konfigurera kamera"; btnStreamToggle.dataset.action = "settings"; }
      else if (s.camera_state === "online" || s.camera_state === "connecting" || s.camera_state === "reconnecting") {
        btnStreamToggle.textContent = "⏹ Stoppa ström"; btnStreamToggle.dataset.action = "stop";
      } else { btnStreamToggle.textContent = "▶ Starta ström"; btnStreamToggle.dataset.action = "start"; }
    }
    if (streamHint) {
      streamHint.textContent = !s.camera_enabled ? "Kameran är inte aktiverad ännu." : "";
    }

    // Status-/metrictabell
    if (statusTable) {
      const camCls = s.camera_state === "online" ? "metric-ok"
        : (s.camera_state === "reconnecting" || s.camera_state === "connecting") ? "metric-warn"
        : "metric-err";
      const yoloCls = s.yolo_state === "running" ? "metric-ok"
        : s.yolo_state === "error" ? "metric-err" : "metric-warn";
      const rows = [
        ["Kamera", CAMERA_LABELS[s.camera_state] || s.camera_state, camCls],
        ["YOLO", (YOLO_LABELS[s.yolo_state] || s.yolo_state), yoloCls],
        ["Modell", s.model || "—"],
        ["Konfigurerad enhet", s.configured_device || "—"],
        ["Enhet (faktisk)", (s.actual_device || "—") + (s.gpu_fallback ? " ⚠ fallback" : ""), s.gpu_fallback ? "metric-warn" : "metric-ok"],
        ["Inferens", (s.inference_ms || 0).toFixed(1) + " ms"],
        ["AI FPS", (s.ai_fps || 0).toFixed(1) + " (mål " + s.target_ai_fps + ")"],
        ["Video FPS (in)", (s.source_fps || 0).toFixed(1)],
        ["Display FPS", (s.display_fps || 0).toFixed(1) + " (mål " + s.target_display_fps + ")"],
        ["Upplösning", s.resolution || "—"],
        ["JPEG-kvalitet", String(s.jpeg_quality)],
        ["Upptid", (s.uptime || 0) + " s"],
      ];
      if (s.events_enabled) {
        const evTxt = s.last_event
          ? (s.last_event + (s.last_event_ts ? " · " + new Date(s.last_event_ts * 1000).toLocaleTimeString("sv-SE") : ""))
          : "Aktivt – väntar på ny detektion";
        rows.push(["HA-event", evTxt, s.last_event ? "metric-ok" : "metric-warn"]);
      } else {
        rows.push(["HA-event", "Av"]);
      }
      if (s.yolo_error) rows.push(["YOLO-fel", s.yolo_error.slice(0, 80), "metric-err"]);
      if (s.camera_error && s.camera_state !== "online") rows.push(["Kameras fel", s.camera_error.slice(0, 80), "metric-err"]);
      statusTable.innerHTML = rows.map((r) => `<tr><td>${escapeHtml(r[0])}</td><td class="${r[2] || ""}">${escapeHtml(String(r[1]))}</td></tr>`).join("");
    }

    // Detected now (unik per klass)
    if (detNowList) {
      const dets = s.detections || [];
      const counts = s.detection_counts || {};
      const byClass = {};
      dets.forEach((d) => {
        if (!(d.class in byClass) || d.confidence > byClass[d.class].confidence) byClass[d.class] = d;
      });
      const uniq = Object.values(byClass);
      if (!uniq.length) {
        detNowList.innerHTML = `<li class="empty-li"><span class="empty">${s.yolo_state === "error" ? "YOLO-fel" : "Inga objekt detekterade"}</span></li>`;
        if (detNowAge) detNowAge.textContent = "";
      } else {
        detNowList.innerHTML = uniq.map((d) =>
          `<li><span>${escapeHtml(d.class)}${counts[d.class] > 1 ? " ×" + counts[d.class] : ""}</span><span class="conf">${Math.round((d.confidence || 0) * 100)}%</span></li>`
        ).join("");
        if (detNowAge) detNowAge.textContent = s.last_detection_ts ? "Senaste: " + new Date(s.last_detection_ts * 1000).toLocaleTimeString("sv-SE") : "";
      }
    }

    // GPU-fallback-varning
    if (gpuWarnCard) {
      if (s.gpu_fallback) {
        gpuWarnCard.hidden = false;
        if (gpuWarnConfigured) gpuWarnConfigured.textContent = s.configured_device || "?";
        if (gpuWarnActual) gpuWarnActual.textContent = s.actual_device || "?";
      } else {
        gpuWarnCard.hidden = true;
      }
    }

    // Synka överlagrings-toggles (Dashboard + Inställningar)
    if ($id("dashBoxes")) $id("dashBoxes").checked = s.show_boxes !== false;
    if ($id("dashLabels")) $id("dashLabels").checked = s.show_labels !== false;
    if ($id("dashConf")) $id("dashConf").checked = s.show_conf !== false;
    if ($id("liveBoxes")) $id("liveBoxes").checked = s.show_boxes !== false;
    if ($id("liveLabels")) $id("liveLabels").checked = s.show_labels !== false;
    if ($id("liveConf")) $id("liveConf").checked = s.show_conf !== false;
  }

  async function saveSettingsJson(payload) {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data.errors && data.errors.join(" · ")) || ("HTTP " + res.status));
    return data;
  }

  /* ---- Stream start/stopp ---- */
  if (btnStreamToggle) {
    btnStreamToggle.addEventListener("click", async () => {
      const action = btnStreamToggle.dataset.action || "start";
      if (action === "settings") { showView("settings"); return; }
      btnStreamToggle.disabled = true;
      try {
        await fetchJson("/api/cameras/" + action, { method: "POST" });
        if (streamHint) streamHint.textContent = "";
      } catch (e) {
        if (streamHint) streamHint.textContent = "Fel: " + e.message;
      }
      pollStatus();
    });
  }

  /* ---- Överlagring: live-apply direkt från Dashboard ---- */
  function bindOverlayToggle(chkId, key, syncedId) {
    const chk = $id(chkId);
    if (!chk) return;
    chk.addEventListener("change", async () => {
      try {
        await saveSettingsJson({ live: { [key]: chk.checked } });
      } catch (e) {
        chk.checked = !chk.checked;
      }
      pollStatus();
      if (syncedId && $id(syncedId)) $id(syncedId).checked = chk.checked;
    });
  }
  bindOverlayToggle("dashBoxes", "show_boxes", "liveBoxes");
  bindOverlayToggle("dashLabels", "show_labels", "liveLabels");
  bindOverlayToggle("dashConf", "show_conf", "liveConf");

  /* ---- Inställningar: ladda ---- */
  function setChecked(id, val) { const el = $id(id); if (el) el.checked = !!val; }
  function ensureOption(sel, val) {
    if (!sel || !val) return;
    const has = Array.from(sel.options).some((o) => o.value === val);
    if (!has) {
      const o = document.createElement("option");
      o.value = val; o.textContent = val;
      sel.appendChild(o);
    }
  }

  async function loadSettingsPage() {
    let s;
    try {
      s = await fetchJson("/api/settings");
    } catch (e) { return; } // backend offline – behåll standardvärden
    const cam = s.camera, det = s.detect, liv = s.live;
    if (cam) {
      setChecked("camEnabled", cam.enabled);
      if ($id("camName")) $id("camName").value = cam.name || "";
      if ($id("camHost")) $id("camHost").value = cam.host || "";
      if ($id("camUser")) $id("camUser").value = cam.user || "";
      if ($id("camPass")) { $id("camPass").value = ""; }
      if ($id("camPassHint")) {
        $id("camPassHint").textContent = cam.password_configured
          ? "🔒 Lösenord är konfigurerat (tomt fält = behåll)."
          : (cam.full_url_configured ? "Full RTSP-URL används." : "");
      }
      if ($id("camPath")) $id("camPath").value = cam.path || "/Preview_01_sub";
      setChecked("camReconnect", cam.reconnect);
      if ($id("camReconnectDelay")) $id("camReconnectDelay").value = (cam.reconnect_delay != null) ? cam.reconnect_delay : 5;
      setChecked("camAutostart", cam.autostart);
    }
    if (det) {
      setChecked("detYolo", det.yolo_enabled !== false);
      if ($id("detAiFps")) { const v = Math.round(det.ai_fps || 4); $id("detAiFps").value = v; if ($id("detAiFpsVal")) $id("detAiFpsVal").textContent = v; }
      if ($id("detImgsz")) $id("detImgsz").value = String(det.imgsz || 640);
      if ($id("detDevice")) { ensureOption($id("detDevice"), det.device); $id("detDevice").value = det.device || "openvino:GPU"; }
    }
    if (liv) {
      setChecked("liveEnabled", liv.enabled);
      if ($id("liveFps")) { const v = liv.display_fps || 10; $id("liveFps").value = v; if ($id("liveFpsVal")) $id("liveFpsVal").textContent = v; }
      if ($id("liveQuality")) { const v = liv.jpeg_quality || 80; $id("liveQuality").value = v; if ($id("liveQualityVal")) $id("liveQualityVal").textContent = v; }
      setChecked("liveBoxes", liv.show_boxes !== false);
      setChecked("liveLabels", liv.show_labels !== false);
      setChecked("liveConf", liv.show_conf !== false);
    }
    const ev = s.events;
    if (ev) {
      setChecked("evEnabled", ev.enabled);
      if ($id("evClasses")) $id("evClasses").value = ev.classes || "";
      if ($id("evClearAfter")) $id("evClearAfter").value = (ev.clear_after != null) ? ev.clear_after : 5;
      if ($id("evHold")) $id("evHold").value = (ev.hold != null) ? ev.hold : 10;
      if ($id("evMinInterval")) $id("evMinInterval").value = (ev.min_interval != null) ? ev.min_interval : 5;
      if ($id("evStartupGrace")) $id("evStartupGrace").value = (ev.startup_grace != null) ? ev.startup_grace : 5;
    }
    renderStatus(s.runtime || {});
  }

  // Slider-textvärden
  ["detAiFps", "liveFps", "liveQuality"].forEach((id) => {
    const el = $id(id), val = $id(id + "Val");
    if (el && val) el.addEventListener("input", () => { val.textContent = el.value; });
  });

  /* ---- Inställningar: spara kamera ---- */
  if ($id("btnSaveCamera")) {
    $id("btnSaveCamera").addEventListener("click", async () => {
      const out = $id("camSaveMsg");
      setMsg(out, "Sparar…", false);
      const body = {
        camera: {
          enabled: $id("camEnabled").checked,
          name: ($id("camName").value || "").trim(),
          host: ($id("camHost").value || "").trim(),
          user: $id("camUser").value || "",
          password: $id("camPass").value || "",   // tom = behåll befintligt
          path: ($id("camPath").value || "").trim(),
          reconnect: $id("camReconnect").checked,
          reconnect_delay: parseInt($id("camReconnectDelay").value, 10) || 5,
          autostart: $id("camAutostart").checked,
        },
      };
      try {
        const res = await saveSettingsJson(body);
        setMsg(out, "✓ Sparat – strömmen startas om…", true);
        loadSettingsPage();
        pollStatus();
        if (res.requires && res.requires.length) console.info("[settings] requires:", res.requires);
      } catch (e) {
        setMsg(out, "❌ " + e.message, false);
      }
    });
  }

  /* ---- Inställningar: testa kamera ---- */
  if ($id("btnTestCam")) {
    $id("btnTestCam").addEventListener("click", async () => {
      const btn = $id("btnTestCam"), out = $id("camTestResult");
      btn.disabled = true;
      setMsg(out, "Testar anslutning…", false);
      const body = {};
      if (($id("camHost").value || "").trim()) body.host = $id("camHost").value.trim();
      if ($id("camUser").value) body.user = $id("camUser").value;
      if ($id("camPass").value) body.password = $id("camPass").value;
      if (($id("camPath").value || "").trim()) body.path = $id("camPath").value.trim();
      try {
        const r = await fetchJson("/api/camera/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (r.ok) {
          if (r.using_live) {
            out.innerHTML = "● Ansluten (live-status). Upplösning: " + escapeHtml(r.resolution || "?") + ", FPS: " + escapeHtml(String(r.fps != null ? r.fps : "?"));
          } else {
            out.innerHTML = "● Ansluten. Upplösning: " + escapeHtml((r.width || "?") + "x" + (r.height || "?")) +
              ", FPS: " + escapeHtml(String(r.fps != null ? r.fps : "?")) +
              ", Kod: " + escapeHtml(r.codec || "?") +
              ", Latens: " + escapeHtml(String(r.latency_ms != null ? r.latency_ms + " ms" : "?"));
          }
          out.classList.add("ok");
        } else {
          out.innerHTML = "❌ Anslutning misslyckades. Orsak: " + escapeHtml(r.error || "okänt");
          out.classList.remove("ok");
        }
      } catch (e) {
        setMsg(out, "❌ " + e.message, false);
      }
      btn.disabled = false;
    });
  }

  /* ---- Inställningar: spara detektering ---- */
  if ($id("btnSaveDetect")) {
    $id("btnSaveDetect").addEventListener("click", async () => {
      const out = $id("detSaveMsg");
      setMsg(out, "Sparar…", false);
      const body = {
        detect: {
          yolo_enabled: $id("detYolo").checked,
          ai_fps: parseInt($id("detAiFps").value, 10) || 4,
          imgsz: parseInt($id("detImgsz").value, 10) || 640,
          device: $id("detDevice").value,
        },
      };
      try {
        const res = await saveSettingsJson(body);
        const reload = (res.requires || []).includes("yolo_reload");
        setMsg(out, reload ? "✓ Sparat – YOLO laddas om (kan ta några sekunder)…" : "✓ Sparat (live)", true);
        loadSettingsPage();
        pollStatus();
      } catch (e) {
        setMsg(out, "❌ " + e.message, false);
      }
    });
  }

  /* ---- Inställningar: spara live-ström ---- */
  if ($id("btnSaveLive")) {
    $id("btnSaveLive").addEventListener("click", async () => {
      const out = $id("liveSaveMsg");
      setMsg(out, "Sparar…", false);
      const body = {
        live: {
          enabled: $id("liveEnabled").checked,
          display_fps: parseInt($id("liveFps").value, 10) || 10,
          jpeg_quality: parseInt($id("liveQuality").value, 10) || 80,
          show_boxes: $id("liveBoxes").checked,
          show_labels: $id("liveLabels").checked,
          show_conf: $id("liveConf").checked,
        },
      };
      try {
        await saveSettingsJson(body);
        setMsg(out, "✓ Sparat – gäller direkt", true);
        loadSettingsPage();
        pollStatus();
      } catch (e) {
        setMsg(out, "❌ " + e.message, false);
      }
    });
  }

  /* ---- Inställningar: HA-event ---- */
  if ($id("btnSaveEvents")) {
    $id("btnSaveEvents").addEventListener("click", async () => {
      const out = $id("evSaveMsg");
      setMsg(out, "Sparar…", false);
      const body = {
        events: {
          enabled: $id("evEnabled").checked,
          classes: ($id("evClasses").value || "").trim(),
          clear_after: parseFloat($id("evClearAfter").value) || 5,
          hold: parseFloat($id("evHold").value) || 10,
          min_interval: parseFloat($id("evMinInterval").value) || 5,
          startup_grace: parseFloat($id("evStartupGrace").value) || 5,
        },
      };
      try {
        const res = await saveSettingsJson(body);
        const on = res.runtime && res.runtime.events_enabled;
        setMsg(out, on ? "✓ Sparat – aktivt: nya detektioner skickas till HA" : "✓ Sparat (av)", true);
        loadSettingsPage();
        pollStatus();
      } catch (e) {
        setMsg(out, "❌ " + e.message, false);
      }
    });
  }

  // Start
  loadSettingsPage();
  pollStatus();
  setInterval(pollStatus, 1000);
})();

