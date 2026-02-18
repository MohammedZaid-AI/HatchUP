import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
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
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/research")
async def read_research(request: Request):
    return templates.TemplateResponse("research.html", {"request": request})

@app.get("/hatchup_chat")
async def read_hatchup_chat(request: Request):
    return templates.TemplateResponse("hatchup_chat.html", {"request": request})
