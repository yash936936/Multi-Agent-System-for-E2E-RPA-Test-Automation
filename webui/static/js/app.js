const API = '/api/v1';

// ---------- Auth guard ----------
const token = localStorage.getItem('aura_token');
if (!token) {
  location.replace('/login');
}

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('aura_token')}` };
}

function decodeJwt(t) {
  try {
    const payload = t.split('.')[1];
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return {};
  }
}

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    localStorage.removeItem('aura_token');
    location.replace('/login');
    throw new Error('Session expired');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

// ---------- Toasts ----------
function toast(message, isError = false) {
  const stack = document.getElementById('toast-stack');
  const el = document.createElement('div');
  el.className = `toast${isError ? ' error' : ''}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// ---------- Icon injection ----------
function paintIcons() {
  const map = {
    dashboard: 'dashboard', runs: 'runs', adapters: 'adapters', analytics: 'trend', commands: 'commands', settings: 'settings',
  };
  document.querySelectorAll('.nav-item[data-view]').forEach(a => {
    const view = a.dataset.view;
    const iconSpan = a.querySelector('.nav-icon');
    if (iconSpan && map[view]) iconSpan.innerHTML = icon(map[view]);
  });
  const put = (sel, name) => { const el = document.querySelector(sel); if (el) el.innerHTML = icon(name); };
  put('#sidebar-toggle', 'chevronLeft');
  put('#logout-btn .nav-icon', 'logout');
  put('.search-wrap span', 'search');
  put('#refresh-btn', 'refresh');
  put('#new-run-btn span', 'plus');
  put('#close-modal-btn', 'close');
  put('#close-detail-btn', 'close');
  put('#add-step-btn span', 'plus');
  put('#wizard-back-btn span', 'arrowLeft');
  const hitl = document.querySelector('[data-mode="human_in_loop"] .mode-choice-icon');
  if (hitl) hitl.innerHTML = icon('hand');
  const auto = document.querySelector('[data-mode="autonomous"] .mode-choice-icon');
  if (auto) auto.innerHTML = icon('robot');
}

// ---------- Sidebar ----------
const shell = document.getElementById('app-shell');
const sidebarToggle = document.getElementById('sidebar-toggle');

function applySidebarState() {
  const collapsed = localStorage.getItem('aura_sidebar_collapsed') === '1';
  shell.classList.toggle('sidebar-collapsed', collapsed);
}
sidebarToggle.addEventListener('click', () => {
  const collapsed = shell.classList.toggle('sidebar-collapsed');
  localStorage.setItem('aura_sidebar_collapsed', collapsed ? '1' : '0');
});

// ---------- Routing ----------
const VIEW_META = {
  dashboard: { title: 'Dashboard', subtitle: "Real-time visibility into every run, adapter, and capability check." },
  runs: { title: 'Test Runs', subtitle: 'Every run this tenant has queued, executed, or healed.' },
  adapters: { title: 'Adapters', subtitle: "The capability adapters this orchestrator can currently route to." },
  analytics: { title: 'Analytics', subtitle: 'Pass-rate trends and flaky-test candidates, built on real run history.' },
  commands: { title: 'Commands', subtitle: 'Everything AURA can do from a terminal, in one place.' },
  settings: { title: 'Settings', subtitle: 'Your account and this workspace, at a glance.' },
};

function setView(view) {
  document.querySelectorAll('.nav-item[data-view]').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  document.querySelectorAll('.view').forEach(s => s.classList.add('hidden'));
  document.getElementById(`view-${view}`).classList.remove('hidden');
  document.getElementById('view-title').textContent = VIEW_META[view].title;
  document.getElementById('view-subtitle').textContent = VIEW_META[view].subtitle;
  document.getElementById('dash-bg').classList.toggle('hidden', view !== 'dashboard');
  location.hash = view;
  if (view === 'runs') loadAllRuns();
  if (view === 'adapters') loadAdapters();
  if (view === 'analytics') loadAnalytics();
  if (view === 'settings') loadSettings();
  if (view === 'commands') loadCommands();
  if (view === 'dashboard') loadDashboard();
}

document.querySelectorAll('.nav-item[data-view]').forEach(a => {
  a.addEventListener('click', (e) => { e.preventDefault(); setView(a.dataset.view); });
});

// ---------- Logout ----------
document.getElementById('logout-btn').addEventListener('click', () => {
  localStorage.removeItem('aura_token');
  location.replace('/login');
});

// ---------- User chip ----------
function paintUser() {
  const claims = decodeJwt(localStorage.getItem('aura_token') || '');
  const name = claims.user_id || claims.sub || 'user';
  document.getElementById('current-user').textContent = name;
  document.getElementById('current-role').textContent = claims.role || '—';
  document.getElementById('user-avatar').textContent = name.slice(0, 1).toUpperCase();
  document.getElementById('settings-user').textContent = name;
  document.getElementById('settings-tenant').textContent = claims.tenant_id || '—';
  document.getElementById('settings-role').textContent = claims.role || '—';
}

// ---------- Dashboard ----------
function statusBadge(status) {
  const s = (status || 'queued').toLowerCase();
  const cls = s === 'passed' ? 'badge-passed' : s === 'failed' ? 'badge-failed' : s === 'running' ? 'badge-running' : 'badge-queued';
  return `<div class="badge ${cls}"><span class="dot"></span>${s}</div>`;
}

function runCard(run, i) {
  const name = run.spec?.test_name || run.spec?.target || run.id;
  const when = run.created_at ? new Date(run.created_at).toLocaleString() : '';
  return `
    <div class="card reveal reveal-${(i % 4) + 1}" data-run-id="${run.id}">
      ${statusBadge(run.status)}
      <div class="card-title">${escapeHtml(name)}</div>
      <div class="card-meta">ID: ${run.id.slice(0, 8)}... • ${when}</div>
    </div>`;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

function emptyState(label, hint) {
  return `<div class="empty-state">${icon('inbox')}<div class="empty-state-title">${label}</div><div>${hint}</div></div>`;
}

async function loadDashboard() {
  try {
    const runs = await api('/test-runs/');
    const total = runs.length;
    const passed = runs.filter(r => r.status === 'passed').length;
    const failed = runs.filter(r => r.status === 'failed').length;
    const inFlight = runs.filter(r => r.status === 'running' || r.status === 'queued').length;

    document.getElementById('stat-grid').innerHTML = `
      <div class="stat-card reveal reveal-1"><div class="stat-value">${total}</div><div class="stat-label">Total runs</div></div>
      <div class="stat-card reveal reveal-2"><div class="stat-value accent">${passed}</div><div class="stat-label">Passed</div></div>
      <div class="stat-card reveal reveal-3"><div class="stat-value" style="color:#d99494">${failed}</div><div class="stat-label">Failed</div></div>
      <div class="stat-card reveal reveal-4"><div class="stat-value warn">${inFlight}</div><div class="stat-label">In flight</div></div>
    `;

    const recent = runs.slice(0, 6);
    document.getElementById('runs-grid').innerHTML = recent.length
      ? recent.map(runCard).join('')
      : emptyState('No runs yet', 'Start your first test run to see it here.');
    bindRunCardClicks('#runs-grid');
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadAllRuns() {
  try {
    const runs = await api('/test-runs/');
    document.getElementById('runs-count-meta').textContent = `${runs.length} total`;
    document.getElementById('all-runs-grid').innerHTML = runs.length
      ? runs.map(runCard).join('')
      : emptyState('No runs yet', 'New runs you queue will show up here.');
    bindRunCardClicks('#all-runs-grid');
  } catch (e) {
    toast(e.message, true);
  }
}

function bindRunCardClicks(containerSel) {
  document.querySelectorAll(`${containerSel} .card`).forEach(card => {
    card.addEventListener('click', () => openRunDetail(card.dataset.runId));
  });
}

async function openRunDetail(runId) {
  try {
    const run = await api(`/test-runs/${runId}`);
    document.getElementById('run-detail-title').textContent = run.spec?.test_name || runId;

    let stepsHtml = '';
    try {
      const steps = await api(`/test-runs/${runId}/steps`);
      const results = steps.step_results || [];
      if (results.length) {
        const rows = results.map(r => {
          const method = r.verification_method === 'dual-method-confirmed'
            ? '<span class="badge badge-passed"><span class="dot"></span>DOM + OCR confirmed</span>'
            : r.verification_method === 'single-method'
              ? '<span class="badge">single method</span>'
              : '<span class="card-meta">n/a</span>';
          return `<tr>
            <td>${r.step_id}</td>
            <td>${escapeHtml(r.action_taken)}</td>
            <td>${method}</td>
            <td>${(r.confidence ?? 0).toFixed(2)}</td>
            <td>${r.escalate ? '⚠️ escalated' : '—'}</td>
          </tr>`;
        }).join('');
        const traceLink = steps.trace_path
          ? `<div class="card-meta" style="margin-top:8px;">Playwright trace: <code>${escapeHtml(steps.trace_path)}</code> (open with <code>playwright show-trace</code>)</div>`
          : '';
        stepsHtml = `
          <div class="card" style="margin-bottom:16px;">
            <div class="card-title">Element resolution per step</div>
            <div class="card-meta">DOM/accessibility-tree locate is the primary path for browser targets; OCR/vision is the fallback for native-desktop targets with no accessibility tree.</div>
            <table style="width:100%; margin-top:8px; font-size:13px;">
              <thead><tr><th>Step</th><th>Action</th><th>Locate method</th><th>Confidence</th><th>Status</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
            ${traceLink}
          </div>`;
      }
    } catch (_) {
      // Non-fatal: older runs predating this endpoint just show the raw JSON below.
    }

    document.getElementById('run-detail-body').innerHTML = stepsHtml
      + `<pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre>`;
    document.getElementById('run-detail-modal').classList.remove('hidden');
  } catch (e) {
    toast(e.message, true);
  }
}
document.getElementById('close-detail-btn').addEventListener('click', () => {
  document.getElementById('run-detail-modal').classList.add('hidden');
});
document.getElementById('run-detail-modal').addEventListener('click', (e) => {
  if (e.target.id === 'run-detail-modal') e.target.classList.add('hidden');
});

// ---------- Adapters ----------
async function loadAdapters() {
  try {
    const data = await api('/adapters/status');
    const items = data.adapters || [];
    document.getElementById('adapters-grid').innerHTML = items.length
      ? items.map((a, i) => `
        <div class="card reveal reveal-${(i % 4) + 1}" style="cursor:default;">
          <div class="badge badge-passed"><span class="dot"></span>${a.status}</div>
          <div class="card-title">${escapeHtml(a.capability_type)}</div>
          <div class="card-meta">Registered capability adapter</div>
        </div>`).join('')
      : emptyState('No adapters registered', 'Register a capability adapter in the orchestrator to see it here.');
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------- Settings ----------
function loadSettings() { paintUser(); }

// ---------- Analytics (Phase H1/H2) ----------
async function loadAnalytics() {
  try {
    const [flakyData, testsData] = await Promise.all([
      api('/test-runs/analytics/flaky'),
      api('/test-runs/analytics/tests'),
    ]);

    const flaky = flakyData.candidates || [];
    document.getElementById('flaky-grid').innerHTML = flaky.length
      ? flaky.map((c, i) => `
        <div class="card reveal reveal-${(i % 4) + 1}" style="cursor:default;">
          <div class="badge badge-failed"><span class="dot"></span>flaky</div>
          <div class="card-title">${escapeHtml(c.test_key)}</div>
          <div class="card-meta">${c.transitions} pass/fail flips across ${c.total_runs} runs • ${(c.pass_rate * 100).toFixed(0)}% pass rate</div>
        </div>`).join('')
      : emptyState('No flaky candidates', 'Tests need a few runs with alternating outcomes before they show up here.');

    const tests = testsData.tests || [];
    if (!tests.length) {
      document.getElementById('trend-grid').innerHTML = emptyState('No tracked tests yet', 'Runs submitted with a stable test_id/test_name will show their trend here.');
      return;
    }
    const trends = await Promise.all(tests.map(t => api(`/test-runs/analytics/tests/${encodeURIComponent(t)}`).catch(() => null)));
    document.getElementById('trend-grid').innerHTML = trends.filter(Boolean).map((t, i) => `
      <div class="card reveal reveal-${(i % 4) + 1}" style="cursor:default;">
        <div class="badge ${t.overall_pass_rate === 1 ? 'badge-passed' : t.overall_pass_rate === 0 ? 'badge-failed' : 'badge-running'}"><span class="dot"></span>${(t.overall_pass_rate * 100).toFixed(0)}% pass rate</div>
        <div class="card-title">${escapeHtml(t.test_key)}</div>
        <div class="card-meta">${t.total_runs} run${t.total_runs === 1 ? '' : 's'} tracked</div>
      </div>`).join('');
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------- Commands reference ----------
const CLI_COMMANDS = [
  {
    name: 'aura init',
    desc: 'Run the first-time setup wizard: target app type, scheduling, and compression policy.',
    flags: ['--yes / -y  Skip interactive prompts, write defaults'],
  },
  {
    name: 'aura execute [test_id]',
    desc: 'Execute a test: approval checkpoint → live vision-execution loop → report. Pass a spec/requirement file, or use --url / --prompt / --all instead of a test_id.',
    flags: [
      '--all  Execute every requirement doc in requirements_input/',
      '--yes / -y  Auto-approve spec, low-confidence actions, and healed steps (unattended)',
      '--autonomous  Same as --yes — explicit name for zero-human-input mode',
      '--refresh-data  Force-regenerate synthetic data instead of reusing the cache',
      '--pdf  Also export the report as PDF (requires the "report" extra)',
      '--url <url>  Live website URL to test',
      '--prompt <text>  Plain-English instruction for what to test (runs unattended)',
      '--scroll-test  After the main steps, scroll top-to-bottom checking for broken/error content',
      '--ui-audit  Check nav/hero/footer are present and test-click nav/footer links',
      '--interactive  Human-in-the-loop: AURA waits for you to perform the --prompt action yourself',
      '--timeout <seconds>  Only with --interactive — give up after N seconds (0 = wait forever)',
    ],
  },
  {
    name: 'aura explore <url>',
    desc: 'Fully autonomous exploration: give it a URL, nothing else. Navigates, scrolls, finds every clickable element via OCR, clicks each one, checks nothing broke, and reports back.',
    flags: [
      '--max-elements <n>  Cap on detected clickable elements to test-click (default 25)',
      '--prompt <text>  Optional thing to keep an eye out for while exploring',
      '--no-scroll-scan  Skip the full-page scroll/error scan before clicking elements',
      '--check-links  Also run a real HTTP-level link check (actual status codes, not just click-and-diff) — off by default, opt in explicitly',
      '--link-scope <all|footer|nav>  Only used with --check-links — which links get checked (default "all")',
    ],
  },
  {
    name: 'aura debug <path>',
    desc: 'Scan Python file(s) for common bug patterns and report them — detection only, never modifies code.',
    flags: [
      '--out <file>  Also write the full findings list to a Markdown file',
      '--no-ruff  Skip the supplementary ruff lint pass',
    ],
  },
  {
    name: 'aura schedule <action> [cron] [test_id]',
    desc: 'Manage unattended scheduled runs. action is one of: add, remove, list.',
    flags: [
      'add "<cron>" <test_id>  e.g. aura schedule add "0 2 * * *" TC-LOGIN-001',
      'remove <job_id>',
      'list',
    ],
  },
  {
    name: 'aura skills <action>',
    desc: 'Inspect, export, import, or diff the local self-healing skill library. action is one of: list, export, import, diff.',
    flags: [
      '--app <name>  App identifier filter/tag',
      '--out <file>  Output file for export, or input file for import',
      '--before <file>  Earlier skill-pack export (required for diff)',
      '--after <file>  Later skill-pack export (required for diff)',
    ],
  },
  {
    name: 'aura trigger listen',
    desc: 'Start the inbound webhook listener so CI/CD systems can trigger runs directly.',
    flags: ['--host <ip>  Default 0.0.0.0', '--port <port>  Default 8099'],
  },
  {
    name: 'aura trigger process',
    desc: 'Process any pending webhook triggers and queue them for execution.',
    flags: [],
  },
];

function loadCommands() {
  document.getElementById('commands-list').innerHTML = CLI_COMMANDS.map(c => `
    <div class="command-item">
      <div class="command-name">${escapeHtml(c.name)}</div>
      <div class="command-desc">${escapeHtml(c.desc)}</div>
      ${c.flags.length ? `<ul class="command-flags">${c.flags.map(f => `<li class="command-flag">${escapeHtml(f)}</li>`).join('')}</ul>` : ''}
    </div>`).join('');
}

// ---------- Refresh / search ----------
document.getElementById('refresh-btn').addEventListener('click', async (e) => {
  e.currentTarget.classList.add('spinning');
  const active = document.querySelector('.nav-item.active')?.dataset.view || 'dashboard';
  await { dashboard: loadDashboard, runs: loadAllRuns, adapters: loadAdapters, settings: loadSettings, commands: async () => loadCommands() }[active]();
  setTimeout(() => e.currentTarget.classList.remove('spinning'), 300);
  toast('Refreshed');
});

document.getElementById('search-input').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('.grid .card').forEach(card => {
    const text = card.textContent.toLowerCase();
    card.style.display = !q || text.includes(q) ? '' : 'none';
  });
});

// Touch devices have no :hover, so tapping the collapsed pill expands it
// and focuses the input; tapping elsewhere collapses it again.
const searchWrap = document.getElementById('search-wrap');
const searchInput = document.getElementById('search-input');
searchWrap.addEventListener('click', () => {
  if (!searchWrap.classList.contains('expanded')) {
    searchWrap.classList.add('expanded');
    searchInput.focus();
  }
});
document.addEventListener('click', (e) => {
  if (!searchWrap.contains(e.target) && !searchInput.value) {
    searchWrap.classList.remove('expanded');
  }
});

// =====================================================================
// New Test Run wizard
// =====================================================================
const wizard = {
  mode: null,        // 'human_in_loop' | 'autonomous'
  step: 1,           // 1 = mode, 2 = target, 3 = details
  steps: [],         // human-in-the-loop step rows
};

const STEP_TYPES = [
  { value: 'visual_click', label: 'Click something', fields: ['target'] },
  { value: 'type_text', label: 'Type into a field', fields: ['target', 'value'] },
  { value: 'navigate_url', label: 'Go to a URL', fields: ['url'] },
  { value: 'scroll', label: 'Scroll the page', fields: ['target'] },
  { value: 'assert', label: 'Check that…', fields: ['target'] },
  { value: 'wait_for_human_action', label: 'Pause for me', fields: ['target'] },
  { value: 'capability_check', label: 'Run a system check', fields: ['target', 'value'] },
];

const FIELD_PLACEHOLDERS = {
  target: {
    visual_click: 'e.g. the "Submit" button',
    type_text: 'e.g. the email field',
    scroll: 'e.g. down to the footer (optional)',
    assert: 'e.g. a success message appears',
    wait_for_human_action: 'e.g. solve the CAPTCHA, then continue',
    capability_check: 'e.g. api, database, file_system',
  },
  value: {
    type_text: 'e.g. someone@example.com',
    capability_check: 'e.g. the orders table, or leave blank',
  },
  url: { navigate_url: 'https://app.example.com/login' },
};

function openWizard() {
  wizard.mode = null;
  wizard.step = 1;
  wizard.steps = [{ action: 'visual_click', target: '', value: '', url: '' }];
  document.getElementById('run-name-input').value = '';
  document.getElementById('run-target-input').value = '';
  document.getElementById('run-prompt-hitl').value = '';
  document.getElementById('run-prompt-auto').value = '';
  document.getElementById('run-error').classList.remove('visible');
  document.querySelectorAll('.mode-choice').forEach(b => b.classList.remove('selected'));
  renderWizardStep();
  document.getElementById('new-run-modal').classList.remove('hidden');
}

function closeWizard() {
  document.getElementById('new-run-modal').classList.add('hidden');
}

function renderWizardStep() {
  const dots = document.querySelectorAll('#wizard-dots .modal-step-dot');
  dots.forEach((d, i) => {
    d.classList.toggle('active', i === wizard.step - 1);
    d.classList.toggle('done', i < wizard.step - 1);
  });

  document.getElementById('wizard-step-1').classList.toggle('hidden', wizard.step !== 1);
  document.getElementById('wizard-step-2').classList.toggle('hidden', wizard.step !== 2);
  document.getElementById('wizard-step-3-hitl').classList.toggle('hidden', !(wizard.step === 3 && wizard.mode === 'human_in_loop'));
  document.getElementById('wizard-step-3-auto').classList.toggle('hidden', !(wizard.step === 3 && wizard.mode === 'autonomous'));

  document.getElementById('wizard-back-btn').classList.toggle('hidden', wizard.step === 1);
  const nextBtn = document.getElementById('wizard-next-btn');
  nextBtn.textContent = wizard.step === 3 ? 'Queue run' : 'Continue';

  document.getElementById('wizard-title').textContent =
    wizard.step === 1 ? 'New Test Run' : wizard.mode === 'autonomous' ? 'Autonomous run' : 'Human-in-the-loop run';

  if (wizard.step === 3 && wizard.mode === 'human_in_loop') renderSteps();
}

document.querySelectorAll('.mode-choice').forEach(btn => {
  btn.addEventListener('click', () => {
    wizard.mode = btn.dataset.mode;
    document.querySelectorAll('.mode-choice').forEach(b => b.classList.toggle('selected', b === btn));
  });
});

function renderSteps() {
  const list = document.getElementById('steps-list');
  list.innerHTML = wizard.steps.map((s, i) => {
    const type = STEP_TYPES.find(t => t.value === s.action) || STEP_TYPES[0];
    const showTarget = type.fields.includes('target');
    const showValue = type.fields.includes('value');
    const showUrl = type.fields.includes('url');
    return `
      <div class="step-row" data-idx="${i}">
        <span class="step-index">${i + 1}</span>
        <select class="step-select" data-role="action">
          ${STEP_TYPES.map(t => `<option value="${t.value}" ${t.value === s.action ? 'selected' : ''}>${t.label}</option>`).join('')}
        </select>
        ${showUrl ? `<input class="step-input" data-role="url" placeholder="${FIELD_PLACEHOLDERS.url.navigate_url}" value="${escapeHtml(s.url)}">` : ''}
        ${showTarget ? `<input class="step-input" data-role="target" placeholder="${FIELD_PLACEHOLDERS.target[s.action] || 'Describe it in plain words'}" value="${escapeHtml(s.target)}">` : ''}
        ${showValue ? `<input class="step-input" data-role="value" placeholder="${FIELD_PLACEHOLDERS.value[s.action] || ''}" value="${escapeHtml(s.value)}">` : ''}
        <button class="step-remove" data-role="remove" title="Remove step">${icon('trash')}</button>
      </div>`;
  }).join('');

  list.querySelectorAll('.step-row').forEach(row => {
    const idx = Number(row.dataset.idx);
    row.querySelector('[data-role="action"]').addEventListener('change', (e) => {
      wizard.steps[idx].action = e.target.value;
      renderSteps();
    });
    row.querySelectorAll('input').forEach(inp => {
      inp.addEventListener('input', (e) => { wizard.steps[idx][e.target.dataset.role] = e.target.value; });
    });
    const rm = row.querySelector('[data-role="remove"]');
    rm.addEventListener('click', () => {
      if (wizard.steps.length === 1) return;
      wizard.steps.splice(idx, 1);
      renderSteps();
    });
  });
}

document.getElementById('add-step-btn').addEventListener('click', () => {
  wizard.steps.push({ action: 'visual_click', target: '', value: '', url: '' });
  renderSteps();
});

document.getElementById('new-run-btn').addEventListener('click', openWizard);
document.getElementById('close-modal-btn').addEventListener('click', closeWizard);
document.getElementById('cancel-run-btn').addEventListener('click', closeWizard);
document.getElementById('new-run-modal').addEventListener('click', (e) => {
  if (e.target.id === 'new-run-modal') closeWizard();
});

document.getElementById('wizard-back-btn').addEventListener('click', () => {
  wizard.step = Math.max(1, wizard.step - 1);
  renderWizardStep();
});

function showWizardError(msg) {
  const box = document.getElementById('run-error');
  box.textContent = msg;
  box.classList.add('visible');
}

document.getElementById('wizard-next-btn').addEventListener('click', async () => {
  document.getElementById('run-error').classList.remove('visible');

  if (wizard.step === 1) {
    if (!wizard.mode) { showWizardError('Pick an approach to continue.'); return; }
    wizard.step = 2;
    return renderWizardStep();
  }

  if (wizard.step === 2) {
    const target = document.getElementById('run-target-input').value.trim();
    if (!target) { showWizardError('Add a URL or file to test.'); return; }
    wizard.step = 3;
    return renderWizardStep();
  }

  // step 3 -> submit
  await submitRun();
});

async function submitRun() {
  const name = document.getElementById('run-name-input').value.trim() || 'Untitled run';
  const target = document.getElementById('run-target-input').value.trim();
  const btn = document.getElementById('wizard-next-btn');
  btn.disabled = true;
  btn.textContent = 'Queuing…';

  try {
    let body;
    if (wizard.mode === 'autonomous') {
      body = {
        mode: 'autonomous',
        test_name: name,
        target,
        prompt: document.getElementById('run-prompt-auto').value.trim(),
      };
    } else {
      const steps = wizard.steps.map(s => {
        const type = STEP_TYPES.find(t => t.value === s.action);
        const step = { action: s.action };
        if (s.action === 'capability_check') {
          // The first field holds the adapter key (api/database/file_system/...),
          // which the backend requires as `capability_type` -- it is NOT the
          // same as a generic `target` description, so it must be mapped
          // explicitly or the run fails later with an opaque validation error.
          step.capability_type = s.target;
          step.target = s.value || '';
        } else {
          if (type.fields.includes('target')) step.target = s.target;
          if (type.fields.includes('value')) step.value = s.value;
        }
        if (type.fields.includes('url')) step.url = s.url || target;
        return step;
      });
      // Always make sure the target itself is reachable first.
      if (!steps.some(s => s.action === 'navigate_url')) {
        steps.unshift({ action: 'navigate_url', url: target });
      }
      const prompt = document.getElementById('run-prompt-hitl').value.trim();
      body = { mode: 'guided', test_name: name, steps, ...(prompt ? { notes: prompt } : {}) };
    }

    const result = await api('/test-runs/', { method: 'POST', body: JSON.stringify(body) });
    toast(`Run queued — ${result.run_id.slice(0, 8)}…`);
    closeWizard();
    const active = document.querySelector('.nav-item.active')?.dataset.view || 'dashboard';
    if (active === 'dashboard') loadDashboard(); else if (active === 'runs') loadAllRuns();
  } catch (e) {
    showWizardError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Queue run';
  }
}

// ---------- Boot ----------
(function init() {
  applySidebarState();
  paintIcons();
  paintUser();
  document.getElementById('app-shell').classList.remove('hidden');
  const initial = (location.hash || '#dashboard').slice(1);
  setView(VIEW_META[initial] ? initial : 'dashboard');
})();
