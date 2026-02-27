import os
import shutil
import tempfile
from functools import lru_cache
from typing import Any, Dict, List

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from src.analyzer import PitchDeckAnalyzer
from src.auth import require_user_id
from src.document_parser import DocumentParser
from src.services.analysis_service import AnalysisService
from src.session import get_active_analysis_id, set_active_analysis_id

router = APIRouter()


@lru_cache(maxsize=1)
def get_analysis_service() -> AnalysisService:
    return AnalysisService()


class ActivateAnalysisPayload(BaseModel):
    analysis_id: str


class ResearchStatePayload(BaseModel):
    messages: List[Dict[str, Any]]


def get_authenticated_user_id(request: Request) -> str:
    return require_user_id(request)

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
            user_id = get_authenticated_user_id(request)
            service = get_analysis_service()
            active_analysis = service.get_or_create_active_analysis(
                user_id=user_id,
                active_analysis_id=get_active_analysis_id(request),
            )
            updated = service.update_deck_and_reset_outputs(
                user_id=user_id,
                analysis_id=active_analysis["analysis_id"],
                deck_data=deck_data.dict(),
            )
            set_active_analysis_id(response, updated["analysis_id"])
            
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
    user_id = get_authenticated_user_id(request)
    service = get_analysis_service()
    active = service.get_or_create_active_analysis(
        user_id=user_id,
        active_analysis_id=get_active_analysis_id(request),
    )
    set_active_analysis_id(response, active["analysis_id"])
    deck = active.get("deck")
    return {
        "has_analysis": bool(deck),
        "analysis_id": active["analysis_id"],
        "analysis": {
            "data": deck,
            "memo": active.get("memo") or {},
            "summary": active.get("insights") or {},
            "research": active.get("research") or [],
            "created_at": active.get("created_at"),
        },
        "user_id": user_id,
    }


@router.get("/api/session/analyses")
async def get_session_analyses(request: Request, response: Response):
    user_id = get_authenticated_user_id(request)
    service = get_analysis_service()
    active = service.get_or_create_active_analysis(
        user_id=user_id,
        active_analysis_id=get_active_analysis_id(request),
    )
    set_active_analysis_id(response, active["analysis_id"])
    analyses = service.list_analyses(user_id)
    return {
        "active_analysis_id": active["analysis_id"],
        "analyses": analyses,
        "active_analysis": {
            "analysis_id": active["analysis_id"],
            "deck": active.get("deck"),
            "insights": active.get("insights") or {},
            "memo": active.get("memo") or {},
            "research": active.get("research") or [],
            "created_at": active.get("created_at"),
        },
    }


@router.post("/api/session/analysis/new")
async def start_new_analysis(request: Request, response: Response):
    user_id = get_authenticated_user_id(request)
    service = get_analysis_service()
    created = service.create_analysis(user_id=user_id)
    set_active_analysis_id(response, created["analysis_id"])
    return {
        "active_analysis_id": created["analysis_id"],
        "analysis": {
            "deck": created.get("deck"),
            "insights": created.get("insights") or {},
            "memo": created.get("memo") or {},
            "research": created.get("research") or [],
            "created_at": created.get("created_at"),
        },
    }


@router.post("/api/session/analysis/activate")
async def activate_analysis(payload: ActivateAnalysisPayload, request: Request, response: Response):
    user_id = get_authenticated_user_id(request)
    service = get_analysis_service()
    analysis = service.get_analysis(user_id, payload.analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    set_active_analysis_id(response, payload.analysis_id)
    return {
        "active_analysis_id": payload.analysis_id,
        "analysis": {
            "deck": analysis.get("deck"),
            "insights": analysis.get("insights") or {},
            "memo": analysis.get("memo") or {},
            "research": analysis.get("research") or [],
            "created_at": analysis.get("created_at"),
        },
    }


@router.post("/api/session/analysis/research")
async def save_research_state(payload: ResearchStatePayload, request: Request, response: Response):
    user_id = get_authenticated_user_id(request)
    service = get_analysis_service()
    active = service.get_or_create_active_analysis(
        user_id=user_id,
        active_analysis_id=get_active_analysis_id(request),
    )
    updated = service.update_deep_research(
        user_id=user_id,
        analysis_id=active["analysis_id"],
        deep_research=payload.messages,
    )
    set_active_analysis_id(response, updated["analysis_id"])
    return {
        "analysis_id": updated["analysis_id"],
        "research_count": len(updated.get("research") or []),
    }
