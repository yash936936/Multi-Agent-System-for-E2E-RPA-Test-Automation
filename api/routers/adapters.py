from fastapi import APIRouter, Depends

from api.security import require_role
from orchestrator.capability_adapter import default_registry

router = APIRouter(prefix="/api/v1/adapters", dependencies=[Depends(require_role(["admin", "executor", "viewer"]))])

# Built once per process -- mirrors capability_router.py's own lazy /
# cached registry, so this endpoint reports the adapters that are
# actually registered and importable rather than a hardcoded list that
# silently drifts from orchestrator/capability_adapter.py.
_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        _registry = default_registry()
    return _registry


@router.get("/status")
async def adapter_status():
    registry = _get_registry()
    return {
        "adapters": [
            {"capability_type": t.value, "status": "registered"}
            for t in registry.registered_types()
        ]
    }
