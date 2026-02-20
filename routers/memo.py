from fastapi import APIRouter, Body, Response, HTTPException, Request
from src.models import PitchDeckData, InvestmentMemo, ExecutiveSummary
from src.memo_generator import MemoGenerator
from src.exporter import Exporter
from src.analysis_store import ensure_session_id, upsert_full
import os

router = APIRouter()

@router.post("/api/generate_memo")
async def generate_memo_endpoint(request: Request, response: Response, data: PitchDeckData):
    """
    Generates an investment memo and executive summary from pitch deck data.
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GROQ_API_KEY not found in environment variables.")

        generator = MemoGenerator(api_key=api_key)
        memo = generator.generate_memo(data)
        summary = generator.generate_executive_summary(data, memo)
        session_id = ensure_session_id(request, response)
        upsert_full(session_id, data.dict(), memo.dict(), summary.dict())
        
        return {
            "memo": memo.dict(),
            "summary": summary.dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/export/excel")
async def export_excel_endpoint(data: PitchDeckData):
    """
    Exports pitch deck data to Excel.
    """
    try:
        excel_bytes = Exporter.to_excel(data)
        filename = f"{data.startup_name}_hatchup_data.xlsx"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return Response(content=excel_bytes, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/export/pdf_memo")
async def export_pdf_memo_endpoint(memo: InvestmentMemo, startup_name: str = Body(embed=True)):
    """
    Exports investment memo to PDF.
    Expects JSON body: { "memo": {...}, "startup_name": "Name" }
    """
    try:
        pdf_bytes = Exporter.to_pdf_memo(memo, startup_name)
        filename = f"{startup_name}_memo.pdf"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/export/text_memo")
async def export_text_memo_endpoint(memo: InvestmentMemo, startup_name: str = Body(embed=True)):
    """
    Exports investment memo to Text.
    Expects JSON body: { "memo": {...}, "startup_name": "Name" }
    """
    try:
        text_str = Exporter.to_text_memo(memo, startup_name)
        filename = f"{startup_name}_memo.txt"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return Response(content=text_str, media_type="text/plain", headers=headers)
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))
