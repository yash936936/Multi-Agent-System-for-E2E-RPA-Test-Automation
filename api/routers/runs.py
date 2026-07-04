import threading
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
    try:
        test_spec = build_test_spec(spec)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    run_id = str(uuid.uuid4())
    run_store.create(run_id, user.tenant_id, user.user_id, spec)

    audit_logger.log(
        user.tenant_id, user.user_id, "CREATE_RUN", run_id,
        {"spec_name": spec.get("test_name", test_spec.test_id)},
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


@router.get("/", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def list_runs(user: TokenPayload = Depends(get_current_user)):
    return run_store.list(user.tenant_id)


@router.get("/{run_id}", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def get_run(run_id: str, user: TokenPayload = Depends(get_current_user)):
    run = run_store.get(user.tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied")
    return run
