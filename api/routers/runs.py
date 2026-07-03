import threading
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Body
from api.security import TokenPayload, require_role, get_current_user
from orchestrator.audit_logger import audit_logger

router = APIRouter(prefix="/api/v1/test-runs")

# Multi-tenant isolated store
runs_store: dict[str, dict[str, dict]] = {} 
run_lock = threading.Lock()

@router.post("/", dependencies=[Depends(require_role(["admin", "executor"]))])
async def create_run(
    spec: dict = Body(...),  # Debug Fix: Explicitly tell FastAPI to parse the body as JSON
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: TokenPayload = Depends(require_role(["admin", "executor"]))
):
    run_id = str(uuid.uuid4())
    tenant_id = user.tenant_id
    
    if tenant_id not in runs_store:
        runs_store[tenant_id] = {}
        
    runs_store[tenant_id][run_id] = {
        "id": run_id, "status": "queued", "created_at": datetime.utcnow().isoformat(), "spec": spec
    }
    
    audit_logger.log(tenant_id, user.user_id, "CREATE_RUN", run_id, {"spec_name": spec.get("test_name", "unknown")})
    background_tasks.add_task(execute_run, tenant_id, run_id, spec)
    
    return {"run_id": run_id, "status": "queued"}

async def execute_run(tenant_id: str, run_id: str, spec: dict):
    acquired = run_lock.acquire(blocking=False)
    if not acquired:
        runs_store[tenant_id][run_id]["status"] = "failed"
        runs_store[tenant_id][run_id]["error"] = "Vision Core busy"
        return
        
    try:
        runs_store[tenant_id][run_id]["status"] = "running"
        # Hook into RunEngine here...
        runs_store[tenant_id][run_id]["status"] = "passed"
    except Exception as e:
        runs_store[tenant_id][run_id]["status"] = "failed"
        runs_store[tenant_id][run_id]["error"] = str(e)
    finally:
        run_lock.release()

@router.get("/", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def list_runs(user: TokenPayload = Depends(get_current_user)): # Debug Fix: Added missing import
    tenant_runs = runs_store.get(user.tenant_id, {})
    return list(tenant_runs.values())

@router.get("/{run_id}", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])
async def get_run(run_id: str, user: TokenPayload = Depends(get_current_user)): # Debug Fix: Added missing import
    tenant_runs = runs_store.get(user.tenant_id, {})
    if run_id not in tenant_runs:
        raise HTTPException(status_code=404, detail="Run not found or access denied")
    return tenant_runs[run_id]