import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.security import create_access_token
from api.user_store import user_store
from config.settings import settings

router = APIRouter(prefix="/api/v1/auth")

# In-memory CSRF state store for the OAuth redirect dance: state -> issued_at.
# A single-process dev/self-hosted deployment is the target here (see
# TRD.md offline-first posture) -- if AURA is ever run multi-process behind
# a load balancer this should move to shared storage (e.g. the same sqlite
# memory.db). Entries expire after _OAUTH_STATE_TTL_SECONDS so an abandoned
# login attempt (browser closed mid-flow) doesn't leak memory forever.
_oauth_state: dict[str, float] = {}
_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes -- generous for a login redirect


def _prune_oauth_state() -> None:
    cutoff = time.monotonic() - _OAUTH_STATE_TTL_SECONDS
    expired = [s for s, issued_at in _oauth_state.items() if issued_at < cutoff]
    for s in expired:
        _oauth_state.pop(s, None)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    role: str


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    record = user_store.verify(body.username, body.password)
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(
        tenant_id=record["tenant_id"], user_id=record["user_id"], role=record["role"]
    )
    return LoginResponse(access_token=token, tenant_id=record["tenant_id"], role=record["role"])


@router.post("/signup", response_model=LoginResponse)
async def signup(body: SignupRequest):
    if user_store.user_exists(body.username):
        raise HTTPException(status_code=409, detail="That username is already taken")

    user_store.create_user(username=body.username, password=body.password)
    token = create_access_token(tenant_id="default", user_id=body.username, role="executor")
    return LoginResponse(access_token=token, tenant_id="default", role="executor")


# --- OAuth (Google / GitHub) ---
# Authorization Code flow: /oauth/{provider}/login redirects the browser to
# the provider, the provider redirects back to /oauth/{provider}/callback
# with a `code`, which we exchange server-side for a profile, then mint the
# same JWT a password login would produce.

_PROVIDERS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


def _provider_credentials(provider: str) -> tuple[str, str]:
    if provider == "google":
        return settings.google_client_id, settings.google_client_secret
    if provider == "github":
        return settings.github_client_id, settings.github_client_secret
    raise HTTPException(status_code=404, detail=f"Unknown OAuth provider '{provider}'")


@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider '{provider}'")
    client_id, client_secret = _provider_credentials(provider)
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{provider.title()} sign-in isn't configured on this server yet. "
                f"Set AURA_{provider.upper()}_CLIENT_ID / AURA_{provider.upper()}_CLIENT_SECRET "
                "(e.g. in a .env file) to enable it."
            ),
        )

    state = secrets.token_urlsafe(24)
    _prune_oauth_state()
    _oauth_state[state] = time.monotonic()
    cfg = _PROVIDERS[provider]
    redirect_uri = f"{settings.oauth_redirect_base}/api/v1/auth/oauth/{provider}/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
        "state": state,
        "response_type": "code",
    }
    return RedirectResponse(f"{cfg['authorize_url']}?{urllib.parse.urlencode(params)}")


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str | None = None, state: str | None = None):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider '{provider}'")
    if not code or not state or state not in _oauth_state:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    _oauth_state.pop(state, None)

    client_id, client_secret = _provider_credentials(provider)
    cfg = _PROVIDERS[provider]
    redirect_uri = f"{settings.oauth_redirect_base}/api/v1/auth/oauth/{provider}/callback"

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        try:
            token_resp = await http_client.post(
                cfg["token_url"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"Couldn't reach {provider.title()} to exchange the login code: {e}"
            )

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail=f"{provider.title()} did not return an access token")

        try:
            profile_resp = await http_client.get(
                cfg["userinfo_url"], headers={"Authorization": f"Bearer {access_token}"}
            )
            profile_resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"Couldn't fetch your {provider.title()} profile: {e}"
            )
        profile = profile_resp.json()

    if provider == "google":
        username = profile.get("email") or profile.get("sub")
    else:  # github
        username = profile.get("login") or str(profile.get("id"))

    if not username:
        raise HTTPException(status_code=502, detail=f"Could not read a profile identity from {provider.title()}")

    record = user_store.find_or_create_oauth_user(username=username, provider=provider)
    jwt_token = create_access_token(
        tenant_id=record["tenant_id"], user_id=record["user_id"], role=record["role"]
    )
    # Hand the token back to the SPA via a URL fragment (never sent to the
    # server in subsequent requests, unlike a query param) for the frontend
    # to pick up and store.
    return RedirectResponse(f"/login#token={jwt_token}")
