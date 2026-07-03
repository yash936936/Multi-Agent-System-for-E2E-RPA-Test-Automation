import threading
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from api.security import verify_api_key
from orchestrator.schemas import TestSpec

router = APIRouter(prefix="/api/v1/test-runs", dependencies=[Depends(verify_api_key)])

# Global lock to serialize Vision Core (pyautogui) executions
run_lock = threading.Lock()
runs_store = {} # In-memory store for Phase 17

@router.post("/")
async def create_run(spec: dict, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    runs_store[run_id] = {
        "id": run_id, 
        "status": "queued", 
        "created_at": datetime.utcnow().isoformat(), 
        "spec": spec
    }
    background_tasks.add_task(execute_run, run_id, spec)
    return {"run_id": run_id, "status": "queued"}

async def execute_run(run_id: str, spec: dict):
    # Debug Fix: Strict lock acquisition with guaranteed release
    acquired = run_lock.acquire(blocking=False)
    if not acquired:
        runs_store[run_id]["status"] = "failed"
        runs_store[run_id]["error"] = "Vision Core busy with another run"
        return
        
    try:
        runs_store[run_id]["status"] = "running"
        
        # TODO: Hook into actual RunEngine here
        # from orchestrator.run_engine import RunEngine
        # engine = RunEngine()
        # engine.execute(TestSpec(**spec))
        
        # Simulating execution time
        import time
        time.sleep(2) 
        
        runs_store[run_id]["status"] = "passed"
    except Exception as e:
        runs_store[run_id]["status"] = "failed"
        runs_store[run_id]["error"] = str(e)
    finally:
        # Debug Fix: Guaranteed release even if RunEngine crashes
        run_lock.release()

@router.get("/")
async def list_runs():
    return list(runs_store.values())

@router.get("/{run_id}")
async def get_run(run_id: str):
    if run_id not in runs_store:
        raise HTTPException(status_code=404, detail="Run not found")
    return runs_store[run_id]