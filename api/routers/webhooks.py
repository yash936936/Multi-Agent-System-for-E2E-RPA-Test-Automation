import json

from fastapi import APIRouter, HTTPException, Request

from orchestrator.webhook_listener import queue_trigger

router = APIRouter(prefix="/api/v1/webhooks")

@router.post("/cicd")
async def cicd_webhook(request: Request):
    # Bug fix: this previously silently treated any unparseable body as an
    # empty payload ({}) rather than rejecting it -- inconsistent with the
    # CLI-mode listener (orchestrator/webhook_listener.py's WebhookHandler),
    # which correctly returns 400 for malformed JSON. A CI system that
    # sends a broken payload deserves a clear error back, not a silently
    # queued trigger with no useful content.
    raw_body = await request.body()
    if raw_body:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    else:
        payload = {}

    trigger_id = queue_trigger(payload)
    return {"message": "Trigger queued", "trigger_id": trigger_id}