from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.security import create_access_token
from api.user_store import user_store

router = APIRouter(prefix="/api/v1/auth")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    record = user_store.verify(body.username, body.password)
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(
        tenant_id=record["tenant_id"], user_id=record["user_id"], role=record["role"]
    )
    return LoginResponse(access_token=token, tenant_id=record["tenant_id"], role=record["role"])
