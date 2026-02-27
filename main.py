import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from src.auth import require_user_id

# Load Env
load_dotenv()

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
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Import Routers
from routers import analyze, auth, chat, memo

app.include_router(analyze.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(memo.router)


def base_template_context(request: Request, mode: str = "vc"):
    return {
        "request": request,
        "mode": mode,
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
    }


def require_workspace_user(request: Request):
    try:
        return require_user_id(request)
    except Exception:
        return None


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(
        "home.html",
        base_template_context(request, mode="vc")
    )

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
    return templates.TemplateResponse(
        "index.html",
        base_template_context(request, mode="vc")
    )

@app.get("/vc/deep-research")
async def read_vc_deep_research(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return templates.TemplateResponse(
        "research.html",
        base_template_context(request, mode="vc")
    )

@app.get("/vc/memo")
async def read_vc_memo(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return templates.TemplateResponse(
        "vc_memo.html",
        base_template_context(request, mode="vc")
    )

@app.get("/founder")
async def read_founder(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return templates.TemplateResponse(
        "founder.html",
        base_template_context(request, mode="founder")
    )

@app.get("/chat")
async def read_hatchup_chat(request: Request):
    if not require_workspace_user(request):
        return RedirectResponse(url="/", status_code=307)
    return templates.TemplateResponse(
        "hatchup_chat.html",
        base_template_context(request, mode="vc")
    )

@app.get("/research")
async def legacy_research():
    return RedirectResponse(url="/vc/deep-research", status_code=307)

@app.get("/hatchup_chat")
async def legacy_hatchup_chat():
    return RedirectResponse(url="/chat", status_code=307)

@app.get("/terms")
async def read_terms(request: Request):
    return templates.TemplateResponse(
        "terms.html",
        base_template_context(request, mode="vc")
    )

@app.get("/privacy")
async def read_privacy(request: Request):
    return templates.TemplateResponse(
        "privacy.html",
        base_template_context(request, mode="vc")
    )
