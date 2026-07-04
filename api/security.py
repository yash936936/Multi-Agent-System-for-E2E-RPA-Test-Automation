import jwt
import datetime
from cryptography.fernet import Fernet
from fastapi import Security, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from config.settings import settings

bearer_scheme = HTTPBearer()

# --- Local Vault ---
class SecretVault:
    def __init__(self):
        config_dir = settings.project_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = config_dir / "vault.key"
        self._ensure_key()
        self.cipher = Fernet(self._load_key())

    def _ensure_key(self):
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())

    def _load_key(self):
        return self.key_path.read_bytes()

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
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
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