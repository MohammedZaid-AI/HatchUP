from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Any, Dict, List
from src.document_parser import DocumentParser
from src.analyzer import PitchDeckAnalyzer
from src.analysis_store import (
    ensure_session_id,
    upsert_data,
    get_active_analysis,
    list_analyses,
    create_new_analysis,
    set_active_analysis,
    load_workspace,
    upsert_research,
)
import os
import shutil
import tempfile

router = APIRouter()


class ActivateAnalysisPayload(BaseModel):
    analysis_id: str


class ResearchStatePayload(BaseModel):
    messages: List[Dict[str, Any]]

@router.post("/api/analyze")
async def analyze_deck(request: Request, response: Response, file: UploadFile = File(...)):
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    try:
        # Save uploaded file temporarily because DocumentParser and libraries might expect a file on disk
        # (PyPDF2, pptx, PIL can work with file-like objects but sometimes need seekable, which UploadFile provides via .file)
        # However, looking at src/document_parser.py, it uses uploaded_file.name for extension logic.
        # We need to simulate that or save to temp file with correct extension.
        
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            # We need to adapt DocumentParser to use file path or open file object with name attribute
            with open(tmp_path, "rb") as f:
                # Mock streamlit uploaded_file object which has .name attribute
                class MockFile:
                    def __init__(self, f_obj, name):
                        self.f = f_obj
                        self.name = name
                    def read(self, *args): return self.f.read(*args)
                    def seek(self, *args): return self.f.seek(*args)
                    def tell(self): return self.f.tell()
                    # Forward other methods if needed
                    def __getattr__(self, name): return getattr(self.f, name)

                mock_file = MockFile(f, file.filename)
                
                # Parse
                raw_text = DocumentParser.parse_file(mock_file)
            
            # Extract Data
            analyzer = PitchDeckAnalyzer(api_key=os.environ["GROQ_API_KEY"])
            deck_data = analyzer.analyze_pitch_deck(raw_text)
            session_id = ensure_session_id(request, response)
            updated = upsert_data(session_id, deck_data.dict())
            
            return {
                "analysis_id": updated["analysis_id"],
                "deck": deck_data.dict(),
            }

        finally:
            # Cleanup temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/session/analysis")
async def get_session_analysis(request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    active = get_active_analysis(session_id)
    analysis = active["analysis"]
    deck = analysis.get("deck")
    return {
        "has_analysis": bool(deck),
        "analysis_id": active["analysis_id"],
        "analysis": {
            "data": deck,
            "memo": analysis.get("memo") or {},
            "summary": analysis.get("insights") or {},
            "research": analysis.get("research") or [],
            "created_at": analysis.get("created_at"),
        },
        "session_id": session_id,
    }


@router.get("/api/session/analyses")
async def get_session_analyses(request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    workspace = load_workspace(session_id)
    active = get_active_analysis(session_id)
    return {
        "active_analysis_id": workspace.get("active_analysis_id"),
        "analyses": list_analyses(session_id),
        "active_analysis": {
            "analysis_id": active["analysis_id"],
            "deck": active["analysis"].get("deck"),
            "insights": active["analysis"].get("insights") or {},
            "memo": active["analysis"].get("memo") or {},
            "research": active["analysis"].get("research") or [],
            "created_at": active["analysis"].get("created_at"),
        },
    }


@router.post("/api/session/analysis/new")
async def start_new_analysis(request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    created = create_new_analysis(session_id)
    return {
        "active_analysis_id": created["analysis_id"],
        "analysis": created["analysis"],
    }


@router.post("/api/session/analysis/activate")
async def activate_analysis(payload: ActivateAnalysisPayload, request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    try:
        analysis = set_active_analysis(session_id, payload.analysis_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "active_analysis_id": payload.analysis_id,
        "analysis": analysis,
    }


@router.post("/api/session/analysis/research")
async def save_research_state(payload: ResearchStatePayload, request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    updated = upsert_research(session_id, payload.messages)
    return {
        "analysis_id": updated["analysis_id"],
        "research_count": len(updated["analysis"].get("research") or []),
    }
