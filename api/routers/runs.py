import time
import uuid

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Body

from api.security import TokenPayload, require_role, get_current_user, require_project_access, user_can_access_project
from api.run_store import run_store
from api.spec_builder import build_test_spec
from orchestrator.audit_logger import audit_logger
from orchestrator.run_engine import RunEngine

router = APIRouter(prefix="/api/v1/test-runs")


def _make_api_screenshot_provider():
    from runtime.hooks.capture import capture_screenshot

    def provider(run_id: str, step_id: int) -> str:
        return str(capture_screenshot(run_id, step_id))

    return provider


def _new_engine() -> RunEngine:
    """
    Phase J (decisions.md D-031): every background task gets its own
    RunEngine instance instead of a shared process-wide singleton.

    Previously a single module-level `_engine` was built once and reused,
    guarded by a global `_run_lock` that made every run wait for the
    previous one to finish end to end (each caller was told "Vision Core
    busy" if a run was already in flight) -- full serialization dressed
    up as a lock, not real concurrency. RunEngine itself holds no
    run-scoped mutable state on `self` (its LoopGuardrail is a fresh local
    variable created inside `run_spec()` per call, and its
    SkillStore/RunMemoryStore open a new sqlite3 connection per operation
    rather than holding one open across calls -- see
    orchestrator/guardrails.py and orchestrator/skill_store.py /
    orchestrator/memory.py), so instantiating one engine per run is both
    correct and cheap. Concurrent runs now genuinely execute in parallel.

    Honest scope note: this removes *artificial* serialization at the
    Python-object level. It does not make two concurrent real-browser
    vision runs safe to point at the same physical display/screenshot
    surface on one machine -- that's a hardware/OS constraint, unchanged
    by this pass.
    """
    return RunEngine(screenshot_provider=_make_api_screenshot_provider())


@router.post("/")
async def create_run(
    spec: dict = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: TokenPayload = Depends(require_role(["admin", "executor"])),
):
    mode = spec.get("mode", "guided")
    # Phase K (decisions.md D-032): checked once, up front, for both
    # branches below -- both the autonomous (raw-dict) and guided
    # (build_test_spec-parsed) paths read project_tag from the same
    # incoming JSON body key, so there's no need to duplicate this check
    # per branch.
    require_project_access(user, spec.get("project_tag"))

    if mode == "autonomous":
        target = (spec.get("target") or "").strip()
        if not target:
            raise HTTPException(status_code=422, detail="Autonomous runs need a target URL or file")
        prompt = (spec.get("prompt") or "").strip()

        run_id = str(uuid.uuid4())
        run_store.create(run_id, user.tenant_id, user.user_id, spec)
        audit_logger.log(
            user.tenant_id, user.user_id, "CREATE_RUN", run_id,
            {"spec_name": spec.get("test_name", run_id), "mode": "autonomous"},
        )

        # `full_exploration` opts an autonomous run into the same
        # click-every-nav/hero/footer/body-element engine as `aura explore`
        # (orchestrator/ui_audit_runner.run_exploration), instead of the
        # default heuristic Planner path. Previously this engine was only
        # reachable from the CLI -- the web API's autonomous mode always
        # went through Planner.generate_spec, which (by design, per
        # decisions.md) only recognizes literal click/type/navigate/link-
        # check phrasing and has no notion of "click-test everything."
        # This flag closes that gap without changing default behavior for
        # existing prompt-driven autonomous runs.
        if bool(spec.get("full_exploration")):
            max_elements = int(spec.get("max_elements", 25))
            check_links = bool(spec.get("check_links"))
            link_scope = (spec.get("link_scope") or "all").strip()
            background_tasks.add_task(
                execute_full_exploration_run, user.tenant_id, run_id, target, prompt, max_elements, check_links, link_scope
            )
            return {"run_id": run_id, "status": "queued"}

        requirement_text = f"Target: {target}\n\n{prompt}" if prompt else f"Target: {target}"
        background_tasks.add_task(execute_autonomous_run, user.tenant_id, run_id, requirement_text)
        return {"run_id": run_id, "status": "queued"}

    try:
        test_spec = build_test_spec(spec)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    run_id = str(uuid.uuid4())
    run_store.create(run_id, user.tenant_id, user.user_id, spec)

    audit_logger.log(
        user.tenant_id, user.user_id, "CREATE_RUN", run_id,
        {"spec_name": spec.get("test_name", test_spec.test_id), "mode": "guided"},
    )
    background_tasks.add_task(execute_run, user.tenant_id, run_id, test_spec)

    return {"run_id": run_id, "status": "queued"}


def execute_run(tenant_id: str, run_id: str, test_spec) -> None:
    try:
        run_store.update(run_id, status="running")
        engine = _new_engine()
        result = engine.run_spec(test_spec, run_id=run_id)
        report = result.report
        run_store.update(run_id, status=report.status.value, report=report.model_dump(mode="json"))
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))


def execute_autonomous_run(tenant_id: str, run_id: str, requirement_text: str) -> None:
    """
    Same execution path as execute_run, but lets the Planner derive the
    TestSpec from free-text (RunEngine.run) instead of accepting
    hand-assembled steps (RunEngine.run_spec).
    """
    try:
        run_store.update(run_id, status="running")
        engine = _new_engine()
        result = engine.run(requirement_text, run_id=run_id)
        report = result.report
        run_store.update(run_id, status=report.status.value, report=report.model_dump(mode="json"))
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))


def execute_full_exploration_run(
    tenant_id: str,
    run_id: str,
    target: str,
    prompt: str,
    max_elements: int,
    check_links: bool = False,
    link_scope: str = "all",
) -> None:
    """
    API-surface entry point for the same click-every-nav/hero/footer/body
    -element engine `aura explore <url>` already uses
    (orchestrator/ui_audit_runner.run_exploration). This was previously
    only reachable via the CLI; `create_run` routes here when an
    autonomous request sets `"full_exploration": true`.

    check_links / link_scope: the real HTTP-level link check only runs
    when check_links is True (spec: {"check_links": true, "link_scope":
    "footer"|"nav"|"all"}). Previously this ran unconditionally on every
    full_exploration request with scope hardcoded to "footer" -- it's
    opt-in now, mirroring the CLI's --check-links flag.

    Produces a report dict (stored as-is via run_store, which accepts any
    JSON-serializable report) rather than a spec-driven RunReport --
    there's no TestSpec/step list here by definition, just "navigate and
    click-test everything," so the report shape mirrors what
    `aura/cli/explore_cmd.py` already writes to reports/explore_<id>/report.json.
    """
    started = time.time()
    try:
        run_store.update(run_id, status="running")

        from orchestrator.ui_audit_runner import run_exploration
        from runtime.hooks import browser
        from runtime.errors import NoDisplayError
        from runtime.hooks.capture import capture_screenshot

        try:
            browser.open_url(browser.normalize_url(target))
        except NoDisplayError:
            # No live display/browser in this environment -- run_exploration
            # itself will report each element as clicked=False rather than
            # silently faking success (same honesty fix as executor.py's
            # NAVIGATE_URL handling).
            pass

        def provider(rid: str, index: int) -> str:
            return str(capture_screenshot(rid, index))

        audit = run_exploration(
            provider,
            run_id=run_id,
            max_elements=max_elements,
            requirement_prompt=prompt or None,
            page_url=target if check_links else None,
            link_check_scope=link_scope,
        )

        broken = [c.__dict__ for c in audit.possibly_broken]
        unreachable = [c.__dict__ for c in audit.unreachable]
        link_check_broken = bool(audit.link_check_result and audit.link_check_result.get("broken_links"))
        status = "failed" if (broken or audit.page_issues or link_check_broken) else "passed"

        report = {
            "run_id": run_id,
            "mode": "full_exploration",
            "target": target,
            "status": status,
            "total_elements_checked": len(audit.checked),
            "possibly_broken": broken,
            "unreachable": unreachable,
            "page_issues": audit.page_issues,
            "has_nav": audit.has_nav,
            "has_hero": audit.has_hero,
            "has_footer": audit.has_footer,
            "requirement_prompt": audit.requirement_prompt,
            "requirement_match": audit.requirement_match,
            "requirement_notes": audit.requirement_notes,
            "link_check_requested": check_links,
            "link_check_scope": link_scope if check_links else None,
            "link_check_result": audit.link_check_result,
            "duration_seconds": round(time.time() - started, 2),
        }
        run_store.update(run_id, status=status, report=report)
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))


@router.get("/", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def list_runs(user: TokenPayload = Depends(get_current_user)):
    runs = run_store.list(user.tenant_id)
    # Phase K (decisions.md D-032): filter, don't error -- a list where
    # one item is inaccessible should just omit that item, not fail the
    # whole request. Untagged runs (spec.project_tag is None/spec is None
    # entirely for a malformed/legacy row) always pass, matching
    # user_can_access_project's own "untagged is always accessible" rule.
    return [r for r in runs if user_can_access_project(user, (r.get("spec") or {}).get("project_tag"))]


# --- Phase H1/H2: trend analytics + flaky-test detection --------------------
# Registered ahead of the /{run_id} catch-all below -- FastAPI matches routes
# in registration order, so "/analytics/..." would otherwise be swallowed as
# a run_id lookup and always 404.

@router.get("/analytics/tests", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def list_tracked_tests(user: TokenPayload = Depends(get_current_user)):
    """Every test_key with at least one completed run, for this tenant."""
    return {"tests": run_store.list_tracked_tests(user.tenant_id)}


@router.get("/analytics/flaky", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def flaky_candidates(
    min_runs: int = 3,
    min_transitions: int = 2,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Flaky-test *candidates* (Phase H2) -- surfaced for a human to review,
    never auto-quarantined. Pair with `aura skills quarantine <test_id>`
    to act on one.
    """
    return {"candidates": run_store.get_flaky_candidates(user.tenant_id, min_runs=min_runs, min_transitions=min_transitions)}


@router.get("/analytics/tests/{test_key}", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def test_trend(test_key: str, limit: int = 100, user: TokenPayload = Depends(get_current_user)):
    """Pass-rate-over-time + per-run history for one test_key (Phase H1)."""
    result = run_store.pass_rate_series(user.tenant_id, test_key, limit=limit)
    if result["total_runs"] == 0:
        raise HTTPException(status_code=404, detail=f"No completed runs found for test_key '{test_key}'")
    return result


@router.get("/{run_id}", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def get_run(run_id: str, user: TokenPayload = Depends(get_current_user)):
    run = run_store.get(user.tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied")
    # Phase K (decisions.md D-032): same 404 (not 403) as the "doesn't
    # exist" case above, deliberately -- telling an unauthorized user
    # "this exists but you can't see it" (403) leaks more than telling
    # them "not found," matching the existing phrasing's own privacy
    # posture rather than introducing an inconsistent status code here.
    if not user_can_access_project(user, (run.get("spec") or {}).get("project_tag")):
        raise HTTPException(status_code=404, detail="Run not found or access denied")
    return run
