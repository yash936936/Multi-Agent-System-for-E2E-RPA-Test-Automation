import json
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/webhooks")

@router.post("/cicd")
async def cicd_webhook(request: Request):
    # Debug Fix: Safely parse JSON, defaulting to empty dict if body is empty/malformed
    try:
        payload = await request.json()
    except Exception:
        payload = {}
        
    trigger_id = str(uuid.uuid4())
    os.makedirs("triggers/pending", exist_ok=True)
    
    record = {
        "trigger_id": trigger_id, 
        "received_at": datetime.utcnow().isoformat(), 
        "payload": payload
    }
    
    # Atomic write
    tmp_path = f"triggers/pending/{trigger_id}.tmp"
    final_path = f"triggers/pending/{trigger_id}.json"
    with open(tmp_path, "w") as f:
        json.dump(record, f)
    os.replace(tmp_path, final_path)
    
    return {"message": "Trigger queued", "trigger_id": trigger_id}