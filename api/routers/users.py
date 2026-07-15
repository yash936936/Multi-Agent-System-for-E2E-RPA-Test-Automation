"""
User management — api/routers/users.py (Phase K, decisions.md D-032)

Admin-only endpoints for managing the project-tag permission matrix
introduced alongside TestSpec.project_tag / TokenPayload.allowed_project_tags
(see api/security.py::user_can_access_project). Deliberately does not let a
user set their own tags via /auth/signup -- only an admin can restrict
(or clear the restriction on) another user, so self-service signup can
never be used for privilege narrowing *or* escalation of someone else's
access.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from api.security import TokenPayload, require_role
from api.user_store import user_store

router = APIRouter(prefix="/api/v1/users")


class SetProjectTagsRequest(BaseModel):
    allowed_project_tags: list[str] | None = None  # None clears the restriction (fully unrestricted)


class SetProjectTagsResponse(BaseModel):
    username: str
    allowed_project_tags: list[str] | None


@router.put("/{username}/project-tags", response_model=SetProjectTagsResponse)
async def set_project_tags(
    username: str,
    body: SetProjectTagsRequest = Body(...),
    admin: TokenPayload = Depends(require_role(["admin"])),
):
    """
    Sets (or, with an empty/omitted list -> None, clears) the target
    user's project-tag restriction. Admin-only -- see this module's
    docstring for why this isn't exposed via self-service signup.

    Note on scope: this intentionally does not attempt cross-tenant
    lookup/validation of `username` beyond "does a record exist in the
    local user store" -- api/user_store.py's UserStore has no separate
    per-tenant username namespace today (see its own module docstring),
    matching the existing create_user/verify behavior this endpoint
    builds on rather than inventing a new isolation model here.
    """
    tags = body.allowed_project_tags or None  # normalize [] to None, same "unrestricted" meaning
    try:
        user_store.set_allowed_project_tags(username, tags)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SetProjectTagsResponse(username=username, allowed_project_tags=tags)
