import jwt
import datetime
from typing import Optional
from cryptography.fernet import Fernet
from fastapi import Security, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from config.settings import settings

bearer_scheme = HTTPBearer()

# --- Local Vault ---
# NOTE (2026-07-13, decisions.md D-017): vault.key and the JWT signing
# secret used to be the *same file* -- SecretVault generated one key,
# used it both as the Fernet key AND raw as JWT_SECRET. Anyone who could
# read vault.key could forge an admin token. They are now two
# independently-generated files with no derivation relationship: vault.key
# (Fernet, reserved for future stored-credential encryption -- not
# currently used to encrypt anything in this codebase, but kept as the
# vault primitive other adapters may grow into) and jwt.key (raw HMAC
# secret for JWT signing, used nowhere else). Rotating one has zero effect
# on the other.
class SecretVault:
    def __init__(self):
        config_dir = settings.project_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = config_dir / "vault.key"
        self._ensure_key(self.key_path, generator=Fernet.generate_key)
        self.cipher = Fernet(self._load_key(self.key_path))

    def _ensure_key(self, path, generator):
        if not path.exists():
            path.write_bytes(generator())
        self._restrict_permissions(path)

    def _restrict_permissions(self, path):
        # Default file creation permissions (subject to umask, commonly
        # 0644) leave secret key files group/world-readable on POSIX
        # systems. Restrict to owner read/write only. No-op on platforms
        # without POSIX chmod semantics (e.g. Windows), where NTFS ACLs
        # already default to the owning user.
        try:
            path.chmod(0o600)
        except (NotImplementedError, OSError):
            pass

    def _load_key(self, path):
        return path.read_bytes()


class JWTSecretStore:
    """
    Independent JWT HMAC signing secret, stored in its own file
    (config/jwt.key), generated with os.urandom -- NOT derived from, or
    shared with, the Fernet vault key. See decisions.md D-017.
    """

    def __init__(self):
        import os

        config_dir = settings.project_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = config_dir / "jwt.key"
        if not self.key_path.exists():
            self.key_path.write_bytes(os.urandom(32))
        self._restrict_permissions()

    def _restrict_permissions(self):
        try:
            self.key_path.chmod(0o600)
        except (NotImplementedError, OSError):
            pass

    def get_secret(self) -> bytes:
        return self.key_path.read_bytes()


vault = SecretVault()
_jwt_store = JWTSecretStore()
JWT_SECRET = _jwt_store.get_secret()
JWT_ALGORITHM = "HS256"

# --- RBAC Models ---
class TokenPayload(BaseModel):
    tenant_id: str
    user_id: str
    role: str  # "admin", "executor", "viewer"
    # Phase K (decisions.md D-032): None (the default) means "no
    # restriction" -- every user created before this field existed, and
    # every user created without explicitly setting it, keeps exactly
    # their current access (anything their role already permits within
    # their tenant). Only setting a *non-empty* list actually narrows
    # access, and only for specs that have a matching project_tag set --
    # untagged specs are always accessible regardless of this list.
    allowed_project_tags: Optional[list[str]] = None

def create_access_token(
    tenant_id: str, user_id: str, role: str, allowed_project_tags: Optional[list[str]] = None
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "allowed_project_tags": allowed_project_tags,
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


# --- Phase K (decisions.md D-032): project-tag permission matrix ---
#
# Deliberately a plain function, not a FastAPI Depends() factory like
# require_role above -- require_role's allowed_roles list is known
# statically at route-decoration time, but a spec's project_tag is only
# known after the request body is parsed, so the check has to happen
# inline in the route handler after that parsing, not as a dependency.
def user_can_access_project(user: TokenPayload, project_tag: Optional[str]) -> bool:
    """
    Additive, backward-compatible permission check:
      - admins always pass (existing superuser behavior, unchanged).
      - an untagged spec (project_tag is None) is always accessible to
        any authenticated member of the tenant -- matches this system's
        behavior before project tagging existed at all.
      - a user with allowed_project_tags=None (the default for every
        existing/new user unless explicitly restricted) is unrestricted
        -- also matches pre-existing behavior exactly.
      - only a tagged spec AND a user with a non-empty allowed_project_tags
        list actually narrows anything, and only to that list.
    """
    if user.role == "admin":
        return True
    if project_tag is None:
        return True
    if user.allowed_project_tags is None:
        return True
    return project_tag in user.allowed_project_tags


def require_project_access(user: TokenPayload, project_tag: Optional[str]) -> None:
    """Raises 403 if `user` can't access `project_tag`; returns None (no-op) otherwise."""
    if not user_can_access_project(user, project_tag):
        raise HTTPException(
            status_code=403,
            detail=(
                f"User '{user.user_id}' is not permitted to run/view specs tagged "
                f"'{project_tag}'. Allowed tags: {user.allowed_project_tags}."
            ),
        )