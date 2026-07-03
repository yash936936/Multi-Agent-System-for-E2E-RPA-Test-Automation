import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from api.routers import runs, webhooks, adapters

# Debug Fix: Ensure directories exist before FastAPI tries to mount them
os.makedirs("webui/static/css", exist_ok=True)
os.makedirs("webui/static/js", exist_ok=True)
os.makedirs("webui/templates", exist_ok=True)

app = FastAPI(title="AURA Universal QA Platform", version="0.17.0")

app.include_router(runs.router)
app.include_router(webhooks.router)
app.include_router(adapters.router)

app.mount("/static", StaticFiles(directory="webui/static"), name="static")
templates = Jinja2Templates(directory="webui/templates")

@app.get("/")
async def serve_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})