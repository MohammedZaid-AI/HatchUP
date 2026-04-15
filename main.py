import importlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from src.auth import require_user_id

# Load Env
load_dotenv()

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="HatchUp VC AI")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Files & Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

unavailable_routers = []


def include_router_safely(module_name: str) -> None:
    try:
        module = importlib.import_module(module_name)
        app.include_router(module.router)
    except Exception as exc:
        unavailable_routers.append({"module": module_name, "error": str(exc)})
        logger.exception("Failed to include router %s", module_name)


for router_module in (
    "routers.auth",
    "routers.analyze",
    "routers.chat",
    "routers.memo",
):
    include_router_safely(router_module)


def base_template_context(request: Request, mode: str = "vc"):
    return {
        "request": request,
        "mode": mode,
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
    }


def render_template(request: Request, template_name: str, mode: str = "vc"):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_template_context(request, mode=mode),
    )


def require_workspace_user(request: Request):
    try:
        return require_user_id(request)
    except Exception:
        return None


@app.get("/")
async def read_root(request: Request):
    return render_template(request, "home.html", mode="vc")

@app.get("/dashboard")
async def read_dashboard(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return RedirectResponse(url="/vc", status_code=307)

@app.get("/vc")
async def read_vc_root(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return RedirectResponse(url="/vc/deck-analyzer", status_code=307)

@app.get("/vc/deck-analyzer")
async def read_vc_deck_analyzer(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "index.html", mode="vc")

@app.get("/vc/deep-research")
async def read_vc_deep_research(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "research.html", mode="vc")

@app.get("/vc/memo")
async def read_vc_memo(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "vc_memo.html", mode="vc")

@app.get("/founder")
async def read_founder(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "founder_workspace.html", mode="founder")

@app.get("/founder-mode")
async def read_founder_mode(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "founder.html", mode="founder")

@app.get("/talent-scout")
async def read_talent_scout():
    return RedirectResponse(url="/founder-mode", status_code=307)

@app.get("/chat")
async def read_hatchup_chat(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return render_template(request, "hatchup_chat.html", mode="vc")

@app.get("/research")
async def legacy_research():
    return RedirectResponse(url="/vc/deep-research", status_code=307)

@app.get("/hatchup_chat")
async def legacy_hatchup_chat():
    return RedirectResponse(url="/chat", status_code=307)

@app.get("/terms")
async def read_terms(request: Request):
    return render_template(request, "terms.html", mode="vc")

@app.get("/privacy")
async def read_privacy(request: Request):
    return render_template(request, "privacy.html", mode="vc")


@app.get("/healthz")
async def healthz():
    return JSONResponse(
        {
            "status": "ok",
            "unavailable_routers": unavailable_routers,
        }
    )
