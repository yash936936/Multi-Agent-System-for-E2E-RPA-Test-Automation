const API_URL = "/api/v1/test-runs/";
const API_KEY = "aura-dev-key-change-me"; // Matches the default in security.py

async function fetchRuns() {
  try {
    const response = await fetch(API_URL, {
      headers: { "X-AURA-API-Key": API_KEY }
    });
    if (!response.ok) throw new Error("API unreachable");
    return await response.json();
  } catch (error) {
    console.warn("Falling back to mock data:", error);
    return [
      { id: "run-001", status: "passed", spec: "ERP - SAP PO Creation", created_at: "2024-05-20T10:00:00Z" },
      { id: "run-002", status: "failed", spec: "CRM - Salesforce Lead Sync", created_at: "2024-05-20T09:45:00Z" },
      { id: "run-003", status: "running", spec: "Finance - Reconciliation Report", created_at: "2024-05-20T10:05:00Z" }
    ];
  }
}

async function renderRuns() {
  const grid = document.getElementById('runs-grid');
  const runs = await fetchRuns();
  
  if (runs.length === 0) {
    grid.innerHTML = `<p style="color: var(--text-subdued); grid-column: 1/-1; text-align: center; padding: 40px;">No test runs executed yet. Trigger a new run to begin.</p>`;
    return;
  }

  grid.innerHTML = runs.map(run => `
    <div class="card">
      <div class="card-title">${run.spec || 'Unnamed Test Spec'}</div>
      <div class="card-meta">ID: ${run.id.substring(0, 8)}... • ${new Date(run.created_at).toLocaleTimeString()}</div>
      <span class="badge badge-${run.status}">${run.status}</span>
    </div>
  `).join('');
}

async function triggerNewRun() {
  const specName = prompt("Enter Test Spec Name (e.g., 'SAP PO Creation'):");
  if (!specName) return;

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "X-AURA-API-Key": API_KEY 
      },
      body: JSON.stringify({ 
        test_name: specName, 
        steps: [{ action: "VISION_CLICK", target: "Submit Button" }] 
      })
    });
    
    if (response.ok) {
      alert(`Run queued successfully!`);
      renderRuns(); // Refresh the grid
    } else {
      alert("Failed to trigger run. Check API logs.");
    }
  } catch (error) {
    alert("Error connecting to AURA API.");
  }
}

document.addEventListener('DOMContentLoaded', renderRuns);