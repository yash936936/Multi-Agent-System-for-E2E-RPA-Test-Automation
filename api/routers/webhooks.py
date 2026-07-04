import json
import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request

from config.settings import settings

router = APIRouter(prefix="/api/v1/webhooks")

@router.post("/cicd")
async def cicd_webhook(request: Request):
    # Debug Fix: Safely parse JSON, defaulting to empty dict if body is empty/malformed
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    trigger_id = str(uuid.uuid4())
    trigger_dir = settings.triggers_pending_dir
    trigger_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "trigger_id": trigger_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload
    }

    # Atomic write
    tmp_path = trigger_dir / f"{trigger_id}.tmp"
    final_path = trigger_dir / f"{trigger_id}.json"
    with open(tmp_path, "w") as f:
        json.dump(record, f)
    os.replace(tmp_path, final_path)

    return {"message": "Trigger queued", "trigger_id": trigger_id}