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
            `<li><span>${escapeHtml(d.class)}</span><span class="conf">${(d.confidence * 100).toFixed(0)}%</span></li>`
        )
        .join("")}</ul>`
    : `<p class="empty">No objects detected at this confidence.</p>`;

  const llmHtml = data.description
    ? `<div class="llm-box"><span class="tag">LLM</span><p>${escapeHtml(data.description)}</p></div>`
    : data.llm_error
    ? `<div class="llm-err">⚠️ ${escapeHtml(data.llm_error)}</div>`
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
