/**
 * AURA dashboard -- static/js/app.js
 *
 * Phase 17 rewrite. Everything here talks to the real, Phase-15-wired
 * API (JWT login, RunEngine-backed test-runs, live adapter registry) --
 * no mock/fallback data. If the API is unreachable the UI says so
 * instead of quietly showing fake runs.
 */

const API_BASE = "/api/v1";

const state = {
  token: localStorage.getItem("aura_token") || null,
  tenantId: localStorage.getItem("aura_tenant") || null,
  role: localStorage.getItem("aura_role") || null,
  username: localStorage.getItem("aura_username") || null,
  runs: [],
  adapters: [],
  pollHandle: null,
  currentView: "dashboard",
};

const ACTIONS = [
  "visual_click", "type_text", "navigate_url", "scroll", "assert",
  "capability_check", "wait_for_human_action",
];

// -------------------- API helpers --------------------

async function apiFetch(path, options = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    options.headers || {},
    state.token ? { Authorization: `Bearer ${state.token}` } : {}
  );
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    logout();
    throw new Error("Session expired -- please sign in again.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

// -------------------- Auth --------------------

function isLoggedIn() {
  return Boolean(state.token);
}

function logout() {
  state.token = null;
  state.tenantId = null;
  state.role = null;
  state.username = null;
  localStorage.removeItem("aura_token");
  localStorage.removeItem("aura_tenant");
  localStorage.removeItem("aura_role");
  localStorage.removeItem("aura_username");
  stopPolling();
  showLogin();
}

async function login(username, password) {
  const data = await apiFetchUnauthenticated("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  state.token = data.access_token;
  state.tenantId = data.tenant_id;
  state.role = data.role;
  state.username = username;
  localStorage.setItem("aura_token", state.token);
  localStorage.setItem("aura_tenant", state.tenantId);
  localStorage.setItem("aura_role", state.role);
  localStorage.setItem("aura_username", username);
}

async function apiFetchUnauthenticated(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: Object.assign({ "Content-Type": "application/json" }, options.headers || {}),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  return response.json();
}

// -------------------- Screen toggling --------------------

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app-shell").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");
  document.getElementById("current-user").textContent = state.username || "-";
  document.getElementById("settings-user").textContent = state.username || "-";
  document.getElementById("settings-tenant").textContent = state.tenantId || "-";
  document.getElementById("settings-role").textContent = state.role || "-";
}

function switchView(view) {
  state.currentView = view;
  document.querySelectorAll(".nav-item[data-view]").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`view-${view}`).classList.remove("hidden");

  const titles = {
    dashboard: ["Dashboard", "Real-time visibility into every run, adapter, and capability check."],
    runs: ["Test Runs", "Every run executed through this AURA instance, newest first."],
    adapters: ["Adapters", "Live capability adapters registered with the orchestrator."],
    settings: ["Settings", "Your session and API details."],
  };
  const [title, subtitle] = titles[view] || ["AURA", ""];
  document.getElementById("view-title").textContent = title;
  document.getElementById("view-subtitle").textContent = subtitle;

  if (view === "adapters") loadAdapters();
}

// -------------------- Rendering --------------------

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status.replace(/_/g, " ")}</span>`;
}

function renderStats() {
  const counts = { total: state.runs.length, passed: 0, failed: 0, running: 0 };
  state.runs.forEach((r) => {
    if (r.status === "passed" || r.status === "passed_with_healing") counts.passed++;
    else if (r.status === "failed") counts.failed++;
    else if (r.status === "running" || r.status === "queued") counts.running++;
  });

  const cards = [
    { label: "Total runs", value: counts.total, cls: "" },
    { label: "Passed", value: counts.passed, cls: "accent-passed" },
    { label: "Failed", value: counts.failed, cls: "accent-failed" },
    { label: "In flight", value: counts.running, cls: "accent-running" },
  ];

  document.getElementById("stat-grid").innerHTML = cards
    .map((c) => `
      <div class="stat-card ${c.cls}">
        <div class="stat-value">${c.value}</div>
        <div class="stat-label">${c.label}</div>
      </div>`)
    .join("");
}

function runCard(run) {
  const specName = (run.spec && (run.spec.test_name || run.spec.requirement_ref)) || "Unnamed run";
  const when = run.created_at ? new Date(run.created_at).toLocaleString() : "";
  return `
    <div class="card" data-run-id="${run.id}">
      <div class="card-header">
        ${statusBadge(run.status)}
      </div>
      <div class="card-title">${escapeHtml(specName)}</div>
      <div class="card-meta">ID: ${run.id.substring(0, 8)}... &bull; ${when}</div>
      ${run.error ? `<div class="card-meta" style="color: var(--text-negative);">${escapeHtml(run.error)}</div>` : ""}
    </div>`;
}

function renderRunsGrid(elementId, runs) {
  const grid = document.getElementById(elementId);
  if (!runs.length) {
    grid.innerHTML = `<div class="empty-state">No test runs yet. Click "New Run" to queue your first execution.</div>`;
    return;
  }
  grid.innerHTML = runs.map(runCard).join("");
  grid.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", () => openRunDetail(card.dataset.runId));
  });
}

function renderAdapters() {
  const grid = document.getElementById("adapters-grid");
  if (!state.adapters.length) {
    grid.innerHTML = `<div class="empty-state">No adapters registered.</div>`;
    return;
  }
  grid.innerHTML = state.adapters
    .map((a) => `
      <div class="adapter-card">
        <div class="adapter-name">${a.capability_type.replace(/_/g, " ")}</div>
        <div><span class="status-dot"></span>${a.status}</div>
      </div>`)
    .join("");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// -------------------- Data loading --------------------

async function loadRuns() {
  try {
    const runs = await apiFetch("/test-runs/");
    state.runs = runs;
    renderStats();
    renderRunsGrid("runs-grid", runs.slice(0, 12));
    renderRunsGrid("all-runs-grid", runs);
  } catch (e) {
    document.getElementById("runs-grid").innerHTML =
      `<div class="empty-state">Couldn't reach AURA's API: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadAdapters() {
  try {
    const data = await apiFetch("/adapters/status");
    state.adapters = data.adapters || [];
    renderAdapters();
  } catch (e) {
    document.getElementById("adapters-grid").innerHTML =
      `<div class="empty-state">Couldn't reach AURA's API: ${escapeHtml(e.message)}</div>`;
  }
}

async function openRunDetail(runId) {
  try {
    const run = await apiFetch(`/test-runs/${runId}`);
    document.getElementById("run-detail-title").textContent = `Run ${runId.substring(0, 8)}...`;
    document.getElementById("run-detail-body").textContent = JSON.stringify(run, null, 2);
    document.getElementById("run-detail-modal").classList.remove("hidden");
  } catch (e) {
    alert(`Couldn't load run: ${e.message}`);
  }
}

// -------------------- Polling --------------------

function startPolling() {
  stopPolling();
  loadRuns();
  state.pollHandle = setInterval(loadRuns, 4000);
}

function stopPolling() {
  if (state.pollHandle) clearInterval(state.pollHandle);
  state.pollHandle = null;
}

// -------------------- New Run modal --------------------

let stepCounter = 0;

function addStepRow(prefill = {}) {
  stepCounter += 1;
  const id = `step-${stepCounter}`;
  const container = document.createElement("div");
  container.className = "step-row";
  container.id = id;
  container.innerHTML = `
    <div class="step-row-top">
      <select class="step-action">
        ${ACTIONS.map((a) => `<option value="${a}" ${a === prefill.action ? "selected" : ""}>${a}</option>`).join("")}
      </select>
      <input type="text" class="step-target" placeholder="Target / value (e.g. Submit Button, URL, capability target)" value="${escapeHtml(prefill.target || "")}">
      <button type="button" class="step-remove-btn">${icon("close")}</button>
    </div>
  `;
  container.querySelector(".step-remove-btn").addEventListener("click", () => container.remove());
  document.getElementById("steps-list").appendChild(container);
}

function collectSteps() {
  return Array.from(document.querySelectorAll(".step-row")).map((row) => ({
    action: row.querySelector(".step-action").value,
    target: row.querySelector(".step-target").value,
  }));
}

function openNewRunModal() {
  document.getElementById("run-name-input").value = "";
  document.getElementById("run-error").textContent = "";
  document.getElementById("steps-list").innerHTML = "";
  addStepRow({ action: "capability_check", target: "smoke" });
  document.getElementById("new-run-modal").classList.remove("hidden");
}

async function submitNewRun() {
  const testName = document.getElementById("run-name-input").value.trim();
  const steps = collectSteps();
  const errorEl = document.getElementById("run-error");
  errorEl.textContent = "";

  if (!testName) {
    errorEl.textContent = "Test name is required.";
    return;
  }
  if (!steps.length) {
    errorEl.textContent = "At least one step is required.";
    return;
  }

  try {
    await apiFetch("/test-runs/", {
      method: "POST",
      body: JSON.stringify({ test_name: testName, steps }),
    });
    document.getElementById("new-run-modal").classList.add("hidden");
    switchView("dashboard");
    loadRuns();
  } catch (e) {
    errorEl.textContent = e.message;
  }
}

// -------------------- Wiring --------------------

function wireStaticIcons() {
  document.querySelector('[data-view="dashboard"]').innerHTML = `${icon("home")} Dashboard`;
  document.querySelector('[data-view="runs"]').innerHTML = `${icon("rocket")} Test Runs`;
  document.querySelector('[data-view="adapters"]').innerHTML = `${icon("plug")} Adapters`;
  document.querySelector('[data-view="settings"]').innerHTML = `${icon("setting")} Settings`;
  document.getElementById("logout-btn").innerHTML = `${icon("logout")} Log out`;
  document.getElementById("user-icon").innerHTML = ICONS.user;
  document.getElementById("refresh-btn").innerHTML = icon("refresh");
  document.getElementById("new-run-btn").innerHTML = `${icon("add")} New Run`;
  document.getElementById("add-step-btn").innerHTML = `${icon("add")} Add step`;
  document.querySelector(".search-wrap .icon-inline").innerHTML = ICONS.search;
  document.getElementById("close-modal-btn").innerHTML = icon("close");
  document.getElementById("close-detail-btn").innerHTML = icon("close");
}

function wireEvents() {
  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    const errorEl = document.getElementById("login-error");
    errorEl.textContent = "";
    try {
      await login(username, password);
      showApp();
      switchView("dashboard");
      startPolling();
    } catch (err) {
      errorEl.textContent = err.message || "Login failed.";
    }
  });

  document.getElementById("logout-btn").addEventListener("click", logout);

  document.querySelectorAll(".nav-item[data-view]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      switchView(el.dataset.view);
    });
  });

  document.getElementById("refresh-btn").addEventListener("click", () => {
    loadRuns();
    if (state.currentView === "adapters") loadAdapters();
  });

  document.getElementById("new-run-btn").addEventListener("click", openNewRunModal);
  document.getElementById("cancel-run-btn").addEventListener("click", () =>
    document.getElementById("new-run-modal").classList.add("hidden")
  );
  document.getElementById("close-modal-btn").addEventListener("click", () =>
    document.getElementById("new-run-modal").classList.add("hidden")
  );
  document.getElementById("submit-run-btn").addEventListener("click", submitNewRun);
  document.getElementById("add-step-btn").addEventListener("click", () => addStepRow());

  document.getElementById("close-detail-btn").addEventListener("click", () =>
    document.getElementById("run-detail-modal").classList.add("hidden")
  );

  document.getElementById("search-input").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = state.runs.filter((r) => {
      const name = (r.spec && (r.spec.test_name || r.spec.requirement_ref)) || "";
      return name.toLowerCase().includes(q) || r.id.toLowerCase().includes(q) || r.status.toLowerCase().includes(q);
    });
    renderRunsGrid("runs-grid", filtered.slice(0, 12));
    renderRunsGrid("all-runs-grid", filtered);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireStaticIcons();
  wireEvents();
  if (isLoggedIn()) {
    showApp();
    switchView("dashboard");
    startPolling();
  } else {
    showLogin();
  }
});
