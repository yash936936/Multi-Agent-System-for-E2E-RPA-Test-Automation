# Optional external integrations — design doc (proposed D-046)

**Status:** Composio implemented (agents/capability/composio_adapter.py,
config/settings.py, tests/test_composio_adapter.py — 11 passing tests,
mocked against the composio package since it isn't installed by
default). crabbox/CubeSandbox, browser-harness, and open-webui remain
design-only, per the sequencing/priority section below.
**Context:** docs/external_repos.md established that Composio, crabbox,
CubeSandbox, open-webui, and browser-use/browser-harness were reviewed
but never integrated, because AURA is offline-by-construction (D-018
removed the only vendor SDK dependency AURA ever had) and none of the
five run fully local. This doc proposes how to integrate them anyway,
as strictly optional, off-by-default dependencies — without compromising
that offline default for anyone who doesn't opt in.

---

## The governing pattern (already in this codebase, not new)

AURA already has three precedents for "capability that requires leaving
the local machine, gated behind an explicit opt-in":

| Precedent | Setting | Default | What it gates |
|---|---|---|---|
| D-036 | `allow_db_seeding` | `False` | AURA's first DB *write* path |
| Phase N/D-018 area | `capability_adapters_enabled` + `allowed_capability_hosts` | conservative | any outbound capability adapter call |
| This session | `enable_dom_extractor` | `False` | JS-injection DOM scan (local, but still a new default-off surface) |

Every one of these follows the same shape: a `Settings` field, checked
at the single call site that would otherwise import/use the dependency,
with the import itself deferred inside the `if` so a stock install never
even attempts to import a package that isn't installed. That's the
template for all four integrations below — nothing new to invent
architecturally, just apply the existing template four times, correctly
scoped.

## Why these four don't belong in one integration

They sit at four different layers of AURA's architecture, so treating
"integrate the optional repos" as one task would produce four shallow,
loosely-related changes instead of four well-scoped ones:

```
┌─────────────────────────────────────────────────────────┐
│ open-webui        →  a *replacement* UI, not a backend   │
│                       dependency at all — separate app,   │
│                       talks to AURA's existing REST API   │
│                       (webui/ already does this job)      │
├─────────────────────────────────────────────────────────┤
│ Composio          →  outbound CAPABILITY ADAPTER          │
│                       (agents/capability/*.py's own layer)│
├─────────────────────────────────────────────────────────┤
│ browser-harness   →  overlaps runtime/hooks/browser.py's  │
│                       existing job — a second implementation │
│                       of "launch and drive a browser",    │
│                       not a new capability                │
├─────────────────────────────────────────────────────────┤
│ crabbox/CubeSandbox → changes WHERE AURA's own process    │
│                       runs, not something AURA calls out  │
│                       to — a deploy/runtime concern        │
└─────────────────────────────────────────────────────────┘
```

---

## 1. Composio — outbound capability adapter (IMPLEMENTED)

**Correction from this doc's first draft:** the original pitch here was
"post results to Slack/Jira" — checking the actual codebase found that's
already covered natively (agents/capability/chatops_adapter.py for
Slack/Teams, agents/capability/defect_tracker_adapter.py for
Jira/TestRail/Zephyr/Xray-style tools), both via plain REST with a
static credential, no new SDK dependency. Building Composio for that
would have been a redundant, heavier second path to a place AURA can
already reach.

**What it actually does now:** appends run-result rows to a Google
Sheet — the concrete case where Composio earns its place, because real
usage needs an OAuth2 access token refreshed against a refresh token on
an expiry clock, which neither of the generic adapters' static-header
model can do at all. Composio's own hosted OAuth connection management
is what's being reused; AURA never handles the OAuth consent screen
itself, only a `connected_account_id` for an already-granted connection
created out-of-band via Composio's dashboard/Connect Link flow.

**Where it fits:** `agents/capability/composio_adapter.py`,
`CapabilityType.COMPOSIO_SHEETS`, registered in
`orchestrator/capability_adapter.py`'s `default_registry()` alongside
every other adapter.

**Gating:** two independent opt-ins, same shape as
`db_seed_adapter.py`'s `allow_db_seeding` — `settings.enable_composio`
(default `False`, `AURA_ENABLE_COMPOSIO=true`) checked inside the
adapter itself, on top of the router's general
`capability_adapters_enabled` kill switch. `settings.composio_api_key`
(`AURA_COMPOSIO_API_KEY`) is AURA's own key for calling Composio's API,
separate from the end user's Google OAuth grant.

**Not hardcoded:** the exact Composio tool slug for the append action
(`GOOGLESHEETS_BATCH_UPDATE` by default) is overridable per-call via
`params["tool_slug"]`, since Composio's own tool registry can rename or
version action slugs independently of this file — same "caller supplies
the exact identifier, adapter doesn't guess" posture
`defect_tracker_adapter.py` already takes for field-mapping.

**Verified:** 11 tests (`tests/test_composio_adapter.py`) cover the gate,
missing-param validation, a mocked successful call (the `composio`
package is injected via `sys.modules`, not actually pip-installed — this
sandbox can't reach Composio's real API any more than it can reach
`cdn.playwright.dev`), tool-slug override, error handling, and audit
logging. **Not verified:** an actual live call against Composio's real
API or a real Google Sheet — that requires a real `COMPOSIO_API_KEY`
and a real OAuth-connected account, neither of which exist in this
sandbox.

## 2. crabbox / CubeSandbox — remote sandboxed execution

**What it would actually do:** run AURA's own process (or a generated
test suite) inside a disposable remote container instead of the local
machine — useful for CI-triggered runs (`aura trigger`) where you don't
want the runner box itself polluted, or for running many parallel
explorations without N local browser processes.

**Where it fits:** this is NOT a capability adapter — it's an
alternative *execution environment* for AURA itself. Closer to
`orchestrator/run_engine.py`'s own `screenshot_provider`/dependency-
injection pattern than to the capability-adapter layer. A cleaner
mental model: a new `runtime/sandboxes/` module implementing "spin up a
remote environment, ship the run spec + capability adapters over,
retrieve report + artifacts back" — genuinely new plumbing, not a small
adapter.

**Proposed shape (sketch only, this is the least precedented of the
four):**
```python
# config/settings.py
enable_remote_sandbox: bool = False
sandbox_provider: str = "none"   # "none" | "crabbox" | "cubesandbox"

# runtime/sandboxes/crabbox_runner.py (new)
def run_in_sandbox(spec: TestSpec, run_id: str) -> RunReport:
    """Ships spec + config to a crabbox instance, polls for completion,
    pulls back the RunReport + screenshots/video/trace artifacts."""
```
**Real work involved:** meaningfully larger than #1 — needs its own
retry/timeout/artifact-transfer logic, and a decision about whether
`orchestrator/run_engine.py` calls this transparently (same interface,
different execution location) or whether it's a separate CLI subcommand
(`aura execute --sandbox crabbox`). Recommend the CLI-subcommand route
first — smaller surface, doesn't risk `run_engine.py`'s existing local
path.
**Risk:** medium. A remote sandbox failing mid-run needs a clean
"sandbox unreachable" failure mode, not a silent partial report —
same NoDisplayError-style fail-closed philosophy this codebase already
applies everywhere else (`runtime/errors.py`) would need to extend here.

## 3. browser-harness — overlaps existing browser.py

**Honest assessment: probably not worth integrating separately.**
`runtime/hooks/browser.py` already does session lifecycle, video/trace
recording (D-030/Q), and multi-engine support (I1). browser-harness
solves the same problem AURA already solved for itself. The one thing
worth taking from it (if anything) is a specific technique, evaluated on
its own merits — same as how this session took `buildDomTree.js`'s
*detection strategy* from browser-use without adopting browser-use
itself. Recommend: skip a formal integration; revisit only if a
specific browser-harness capability (not yet identified) turns out to
solve something `browser.py` genuinely can't.

## 4. open-webui — not a backend dependency at all (IMPLEMENTED as docs — no code needed)

**Confirmed by reading the actual router files** (`api/routers/*.py`,
mounted in `api/main.py`): AURA already exposes everything an
alternative frontend needs, all under `/api/v1`, all bearer-JWT
authenticated (`Authorization: Bearer <token>` from `/api/v1/auth/login`).
No AURA-side code change is needed for open-webui or any other
third-party frontend to talk to AURA — it's a deployment/configuration
choice, not an integration:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/auth/login` | POST | `{username, password}` → `{access_token, tenant_id, role}` |
| `/api/v1/auth/signup` | POST | Same response shape, creates a new user |
| `/api/v1/auth/oauth/{provider}/login` | GET | Google/GitHub OAuth redirect start (`google_client_id`/`github_client_id` in `config/settings.py`) |
| `/api/v1/auth/oauth/{provider}/callback` | GET | OAuth callback completion |
| `/api/v1/test-runs/` | POST | Create a run (`{mode: "guided"\|"autonomous", ...}` body) — role-gated to `admin`/`executor` |
| `/api/v1/test-runs/` | GET | List runs — `admin`/`executor`/`viewer` |
| `/api/v1/test-runs/{run_id}` | GET | Single run detail |
| `/api/v1/test-runs/{run_id}/steps` | GET | Per-step results for a run |
| `/api/v1/test-runs/analytics/tests` | GET | Aggregate test analytics |
| `/api/v1/test-runs/analytics/flaky` | GET | Flaky-test analytics (Phase H2 quarantine data) |
| `/api/v1/test-runs/analytics/tests/{test_key}` | GET | Per-test analytics |
| `/api/v1/adapters/status` | GET | Capability adapter registry status (now includes Composio, see §1 above) |
| `/api/v1/webhooks/cicd` | POST | CI/CD trigger webhook |
| `/api/v1/users/{username}/project-tags` | PUT | Project-tag/access management |

**To point open-webui (or any OpenAPI-aware tool) at AURA:** the FastAPI
app auto-generates a schema at `/openapi.json` (default FastAPI
behavior, not something this codebase disabled) — open-webui's generic
"connect a REST API" tooling can consume that directly, or a thin
per-endpoint config can be built by hand from the table above.

**Nothing to implement.** This confirms the design doc's original
assessment was correct: open-webui was never a "does AURA need new
code" question, only a "here's what's already there" one.

---

## Recommended sequencing, if/when this moves to code

1. ~~**Composio**~~ — done (§1). Smallest, cleanest fit into an existing
   pattern.
2. ~~**open-webui**~~ — done (§4). Turned out to need zero code, just
   the API surface table above.
3. **crabbox/CubeSandbox** — real, valuable, but meaningfully larger;
   do only when there's an actual driving use case (e.g. "CI runs are
   polluting the runner box"), not speculatively. Next real candidate
   if this continues.
4. **browser-harness** — recommend not integrating unless a specific
   gap in `browser.py` is identified first.

## What this doc deliberately does NOT do

No settings fields, adapter files, or tests have been added by this
doc. Per the request that produced it, this is scoping and sequencing
only — implementation is a separate, later step, one integration at a
time, each with its own real test coverage (mocked externally, same
constraint every other external-API-touching feature in this codebase
already has, since this sandbox can't reach any of these services'
real endpoints any more than it can reach `cdn.playwright.dev`).
