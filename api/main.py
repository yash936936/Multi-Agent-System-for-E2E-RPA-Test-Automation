from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from api.routers import runs, webhooks, adapters, auth
from config.settings import settings

# webui/ is a static repo asset (like config/tool_registry.yaml), so it must
# resolve relative to the project root, not the process's current working
# directory -- otherwise this breaks when the API is launched from anywhere
# other than the repo root (e.g. as an installed package or a service).
_webui_dir = settings.project_root / "webui"

# Debug Fix: Ensure directories exist before FastAPI tries to mount them
(_webui_dir / "static" / "css").mkdir(parents=True, exist_ok=True)
(_webui_dir / "static" / "js").mkdir(parents=True, exist_ok=True)
(_webui_dir / "templates").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AURA Universal QA Platform", version="0.17.0")

app.include_router(auth.router)
app.include_router(runs.router)
app.include_router(webhooks.router)
app.include_router(adapters.router)

app.mount("/static", StaticFiles(directory=str(_webui_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_webui_dir / "templates"))

@app.get("/")
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/login")
async def serve_login(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/signup")
async def serve_signup(request: Request):
    return templates.TemplateResponse(request, "signup.html", {})