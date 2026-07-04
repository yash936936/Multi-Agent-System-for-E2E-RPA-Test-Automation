import os
import jwt
import datetime
from cryptography.fernet import Fernet
from fastapi import Security, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

bearer_scheme = HTTPBearer()

# --- Local Vault ---
class SecretVault:
    def __init__(self):
        os.makedirs("config", exist_ok=True)
        self.key_path = "config/vault.key"
        self.secrets_path = "config/secrets.json"
        self._ensure_key()
        self.cipher = Fernet(self._load_key())

    def _ensure_key(self):
        if not os.path.exists(self.key_path):
            with open(self.key_path, "wb") as f:
                f.write(Fernet.generate_key())

    def _load_key(self):
        with open(self.key_path, "rb") as f:
            return f.read()

    def get_jwt_secret(self) -> bytes:
        return self._load_key()

vault = SecretVault()
JWT_SECRET = vault.get_jwt_secret()
JWT_ALGORITHM = "HS256"

# --- RBAC Models ---
class TokenPayload(BaseModel):
    tenant_id: str
    user_id: str
    role: str  # "admin", "executor", "viewer"

def create_access_token(tenant_id: str, user_id: str, role: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> TokenPayload:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(allowed_roles: list[str]):
    async def role_checker(user: TokenPayload = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' unauthorized. Requires: {allowed_roles}")
        return user
    return role_checker