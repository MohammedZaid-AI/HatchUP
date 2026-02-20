from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response
from src.document_parser import DocumentParser
from src.analyzer import PitchDeckAnalyzer
from src.models import PitchDeckData
from src.analysis_store import ensure_session_id, upsert_data, load_analysis
import os
import shutil
import tempfile

router = APIRouter()

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
            upsert_data(session_id, deck_data.dict())
            
            return deck_data.dict()

        finally:
            # Cleanup temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/session/analysis")
async def get_session_analysis(request: Request, response: Response):
    session_id = ensure_session_id(request, response)
    analysis = load_analysis(session_id)
    return {
        "has_analysis": bool(analysis and analysis.get("data")),
        "analysis": analysis,
        "session_id": session_id,
    }
