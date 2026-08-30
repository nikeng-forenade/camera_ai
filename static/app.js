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
