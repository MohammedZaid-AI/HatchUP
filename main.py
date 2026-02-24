import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

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
from routers import analyze, chat, memo

app.include_router(analyze.router)
app.include_router(chat.router)
app.include_router(memo.router)

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(
        "home.html",
        {"request": request}
    )

@app.get("/dashboard")
async def read_dashboard():
    return RedirectResponse(url="/vc", status_code=307)

@app.get("/vc")
async def read_vc_root():
    return RedirectResponse(url="/vc/deck-analyzer", status_code=307)

@app.get("/vc/deck-analyzer")
async def read_vc_deck_analyzer(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "mode": "vc"}
    )

@app.get("/vc/deep-research")
async def read_vc_deep_research(request: Request):
    return templates.TemplateResponse(
        "research.html",
        {"request": request, "mode": "vc"}
    )

@app.get("/vc/memo")
async def read_vc_memo(request: Request):
    return templates.TemplateResponse(
        "vc_memo.html",
        {"request": request, "mode": "vc"}
    )

@app.get("/founder")
async def read_founder(request: Request):
    return RedirectResponse(url="/vc/deck-analyzer", status_code=307)

@app.get("/chat")
async def read_hatchup_chat(request: Request):
    return templates.TemplateResponse(
        "hatchup_chat.html",
        {"request": request, "mode": "vc"}
    )

@app.get("/research")
async def legacy_research():
    return RedirectResponse(url="/vc/deep-research", status_code=307)

@app.get("/hatchup_chat")
async def legacy_hatchup_chat():
    return RedirectResponse(url="/chat", status_code=307)
