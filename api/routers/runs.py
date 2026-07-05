import threading
import time
import uuid

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Body

from api.security import TokenPayload, require_role, get_current_user
from api.run_store import run_store
from api.spec_builder import build_test_spec
from orchestrator.audit_logger import audit_logger
from orchestrator.run_engine import RunEngine

router = APIRouter(prefix="/api/v1/test-runs")

_engine: RunEngine | None = None
_run_lock = threading.Lock()


def _make_api_screenshot_provider():
    from runtime.hooks.capture import capture_screenshot

    def provider(run_id: str, step_id: int) -> str:
        return str(capture_screenshot(run_id, step_id))

    return provider


def _get_engine() -> RunEngine:
    global _engine
    if _engine is None:
        _engine = RunEngine(screenshot_provider=_make_api_screenshot_provider())
    return _engine


@router.post("/")
async def create_run(
    spec: dict = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: TokenPayload = Depends(require_role(["admin", "executor"])),
):
    mode = spec.get("mode", "guided")

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
            background_tasks.add_task(
                execute_full_exploration_run, user.tenant_id, run_id, target, prompt, max_elements
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
    acquired = _run_lock.acquire(blocking=False)
    if not acquired:
        run_store.update(run_id, status="failed", error="Vision Core busy -- another run is in flight")
        return

    try:
        run_store.update(run_id, status="running")
        engine = _get_engine()
        result = engine.run_spec(test_spec, run_id=run_id)
        report = result.report
        run_store.update(run_id, status=report.status.value, report=report.model_dump(mode="json"))
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))
    finally:
        _run_lock.release()


def execute_autonomous_run(tenant_id: str, run_id: str, requirement_text: str) -> None:
    """
    Same execution path as execute_run, but lets the Planner derive the
    TestSpec from free-text (RunEngine.run) instead of accepting
    hand-assembled steps (RunEngine.run_spec).
    """
    acquired = _run_lock.acquire(blocking=False)
    if not acquired:
        run_store.update(run_id, status="failed", error="Vision Core busy -- another run is in flight")
        return

    try:
        run_store.update(run_id, status="running")
        engine = _get_engine()
        result = engine.run(requirement_text, run_id=run_id)
        report = result.report
        run_store.update(run_id, status=report.status.value, report=report.model_dump(mode="json"))
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))
    finally:
        _run_lock.release()


def execute_full_exploration_run(tenant_id: str, run_id: str, target: str, prompt: str, max_elements: int) -> None:
    """
    API-surface entry point for the same click-every-nav/hero/footer/body
    -element engine `aura explore <url>` already uses
    (orchestrator/ui_audit_runner.run_exploration). This was previously
    only reachable via the CLI; `create_run` routes here when an
    autonomous request sets `"full_exploration": true`.

    Produces a report dict (stored as-is via run_store, which accepts any
    JSON-serializable report) rather than a spec-driven RunReport --
    there's no TestSpec/step list here by definition, just "navigate and
    click-test everything," so the report shape mirrors what
    `aura/cli/explore_cmd.py` already writes to reports/explore_<id>/report.json.
    """
    acquired = _run_lock.acquire(blocking=False)
    if not acquired:
        run_store.update(run_id, status="failed", error="Vision Core busy -- another run is in flight")
        return

    started = time.time()
    try:
        run_store.update(run_id, status="running")

        from orchestrator.ui_audit_runner import run_exploration
        from runtime.hooks import browser
        from runtime.hooks.browser import NoDisplayError
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

        audit = run_exploration(provider, run_id=run_id, max_elements=max_elements, requirement_prompt=prompt or None)

        broken = [c.__dict__ for c in audit.possibly_broken]
        unreachable = [c.__dict__ for c in audit.unreachable]
        status = "failed" if (broken or audit.page_issues) else "passed"

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
            "duration_seconds": round(time.time() - started, 2),
        }
        run_store.update(run_id, status=status, report=report)
    except Exception as e:
        run_store.update(run_id, status="failed", error=str(e))
    finally:
        _run_lock.release()


@router.get("/", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def list_runs(user: TokenPayload = Depends(get_current_user)):
    return run_store.list(user.tenant_id)


@router.get("/{run_id}", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def get_run(run_id: str, user: TokenPayload = Depends(get_current_user)):
    run = run_store.get(user.tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied")
    return run
