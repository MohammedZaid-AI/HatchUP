import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from src.auth import require_user_id
from src.document_parser import DocumentParser
from src.env_utils import normalize_secret
from src.revenue_wedge_engine import RevenueWedgeEngine
from src.services.founder_workspace_service import FounderWorkspaceService

router = APIRouter()

ALLOWED_FOUNDER_TAGS = {
    "sales_call",
    "customer_interview",
    "lost_deal",
    "support",
    "landing_page",
    "pitch_deck",
    "crm_export",
}

SUPPORTED_REVENUE_WEDGE_EXTENSIONS = {".txt", ".pdf", ".docx", ".csv"}
PARSER_ERROR_PREFIXES = (
    "Error parsing PDF:",
    "Error parsing PPTX:",
    "Error parsing DOCX:",
    "Error parsing CSV:",
    "Error parsing Image",
    "Error reading text file:",
)
COMMERCIAL_SIGNAL_TERMS = {
    "customer",
    "prospect",
    "buyer",
    "user",
    "revenue",
    "pricing",
    "price",
    "deal",
    "pipeline",
    "lead",
    "conversion",
    "trial",
    "demo",
    "signup",
    "onboarding",
    "support",
    "objection",
    "pain",
    "problem",
    "segment",
    "icp",
    "persona",
    "retention",
    "churn",
    "renewal",
    "budget",
    "contract",
    "close",
    "win",
    "loss",
    "crm",
    "call",
    "interview",
    "complaint",
    "landing",
    "copy",
    "message",
    "feature",
    "request",
    "billing",
    "purchase",
    "sales",
    "qualified",
    "mrr",
    "arr",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_authenticated_user_id(request: Request) -> str:
    return require_user_id(request)


@lru_cache(maxsize=1)
def get_founder_workspace_service() -> FounderWorkspaceService:
    return FounderWorkspaceService()


@lru_cache(maxsize=1)
def get_revenue_wedge_engine() -> RevenueWedgeEngine:
    return RevenueWedgeEngine(api_key=normalize_secret(os.environ.get("GROQ_API_KEY")))


class RevenueRunRequest(BaseModel):
    input_ids: Optional[List[str]] = None


class RevenueRunResultPayload(BaseModel):
    outcome: str
    replies: int = 0
    calls_booked: int = 0
    deals_closed: int = 0
    top_objection: str = ""
    metric_delta: str = ""
    notes: str = ""


def _parse_uploaded_file(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in SUPPORTED_REVENUE_WEDGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Revenue Wedge accepts .txt, .pdf, .docx, and .csv files only.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as temp_file:
            class MockFile:
                def __init__(self, file_obj, name):
                    self.f = file_obj
                    self.name = name

                def read(self, *args):
                    return self.f.read(*args)

                def seek(self, *args):
                    return self.f.seek(*args)

                def tell(self):
                    return self.f.tell()

                def __getattr__(self, name):
                    return getattr(self.f, name)

            return DocumentParser.parse_file(MockFile(temp_file, file.filename or "upload.txt"))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _ensure_valid_tag(tag: str) -> str:
    normalized = (tag or "").strip()
    if normalized not in ALLOWED_FOUNDER_TAGS:
        raise HTTPException(status_code=400, detail="Invalid founder input tag.")
    return normalized


def _build_excerpt(text: str) -> str:
    compact = " ".join((text or "").split())
    return compact[:200] + ("..." if len(compact) > 200 else "")


def _validate_revenue_wedge_text(raw_text: str, source_type: str) -> str:
    normalized = (raw_text or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Provide pasted text or upload a supported file.")

    if normalized.startswith(PARSER_ERROR_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail="We couldn't read usable text from that file. Try a cleaner export or paste the relevant notes directly.",
        )

    alpha_tokens = re.findall(r"[a-zA-Z]{3,}", normalized.lower())
    compact = re.sub(r"\s+", " ", normalized)
    commercial_hits = sum(1 for token in alpha_tokens if token in COMMERCIAL_SIGNAL_TERMS)

    if len(compact) < 60 or len(alpha_tokens) < 8:
        raise HTTPException(
            status_code=400,
            detail="That input is too thin for Revenue Wedge. Add more founder notes, call transcripts, objections, CRM reasons, or landing page copy.",
        )

    if commercial_hits < 2:
        source_label = "uploaded file" if source_type == "upload" else "pasted text"
        raise HTTPException(
            status_code=400,
            detail=f"The {source_label} does not look like revenue or customer feedback input yet. Add sales calls, support issues, objections, CRM loss reasons, or GTM copy.",
        )

    return normalized


def _serialize_workspace(workspace: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace_id": workspace.get("workspace_id"),
        "inputs": workspace.get("inputs") or [],
        "latest_run_id": workspace.get("latest_run_id"),
        "latest_run": workspace.get("latest_run"),
        "runs": workspace.get("runs") or [],
        "learned_patterns": workspace.get("learned_patterns") or {},
        "updated_at": workspace.get("updated_at"),
    }


@router.get("/api/founder/revenue-wedge/workspace")
async def get_revenue_wedge_workspace(request: Request):
    user_id = get_authenticated_user_id(request)
    service = get_founder_workspace_service()
    workspace = service.get_or_create_workspace(user_id)
    return _serialize_workspace(workspace)


@router.post("/api/founder/revenue-wedge/input")
async def create_revenue_wedge_input(
    request: Request,
    tag: str = Form(...),
    title: str = Form(""),
    pasted_text: str = Form(""),
    file: Optional[UploadFile] = File(default=None),
):
    user_id = get_authenticated_user_id(request)
    normalized_tag = _ensure_valid_tag(tag)

    raw_text = (pasted_text or "").strip()
    source_type = "paste"
    filename = None
    content_type = "text/plain"

    if file and file.filename:
        raw_text = _parse_uploaded_file(file).strip()
        source_type = "upload"
        filename = file.filename
        content_type = file.content_type or "application/octet-stream"

    raw_text = _validate_revenue_wedge_text(raw_text, source_type)

    now = _utc_now()
    input_record = {
        "input_id": str(uuid.uuid4()),
        "title": (title or filename or normalized_tag.replace("_", " ").title()).strip() or normalized_tag.replace("_", " ").title(),
        "tag": normalized_tag,
        "source_type": source_type,
        "filename": filename,
        "content_type": content_type,
        "raw_text": raw_text,
        "excerpt": _build_excerpt(raw_text),
        "created_at": now,
        "updated_at": now,
    }
    service = get_founder_workspace_service()
    workspace = service.save_input(user_id, input_record)
    return _serialize_workspace(workspace)


@router.delete("/api/founder/revenue-wedge/input/{input_id}")
async def delete_revenue_wedge_input(input_id: str, request: Request):
    user_id = get_authenticated_user_id(request)
    service = get_founder_workspace_service()
    workspace = service.delete_input(user_id, input_id)
    return _serialize_workspace(workspace)


@router.post("/api/founder/revenue-wedge/run")
async def run_revenue_wedge(payload: RevenueRunRequest, request: Request):
    user_id = get_authenticated_user_id(request)
    service = get_founder_workspace_service()
    workspace = service.get_or_create_workspace(user_id)
    selected_ids = set(payload.input_ids or [])
    inputs = workspace.get("inputs") or []
    if selected_ids:
        inputs = [item for item in inputs if item.get("input_id") in selected_ids]
    if not inputs:
        raise HTTPException(status_code=400, detail="Add founder inputs before running Revenue Wedge Engine.")

    previous_run = workspace.get("latest_run")
    run_history = workspace.get("runs") or []
    learned_patterns = workspace.get("learned_patterns") or {}
    engine = get_revenue_wedge_engine()
    result = engine.generate(inputs, previous_run=previous_run, run_history=run_history, learned_patterns=learned_patterns)
    signals = {
        key: [cluster.model_dump() if hasattr(cluster, "model_dump") else cluster for cluster in value]
        for key, value in (result.get("signals") or {}).items()
    }
    brief = result.get("decision_brief") or {}
    run_record = {
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_now(),
        "input_ids": [item.get("input_id") for item in inputs],
        "signals": signals,
        "decision_brief": brief,
        "snapshot": {
            "recommended_icp": brief.get("recommended_icp"),
            "core_problem": brief.get("core_problem"),
            "decision": brief.get("decision"),
            "actions": brief.get("this_week_execution") or [],
            "assets": brief.get("assets") or {},
            "confidence_score": brief.get("confidence_score"),
            "captured_at": _utc_now(),
        },
        "synthesis_notes": result.get("synthesis_notes") or [],
        "generation_source": result.get("generation_source") or "unknown",
        "signal_quality": result.get("signal_quality") or {},
        "comparison": result.get("comparison"),
        "outcome_log": None,
    }
    updated_workspace = service.save_run(user_id, run_record)
    return _serialize_workspace(updated_workspace)


@router.post("/api/founder/revenue-wedge/run/{run_id}/result")
async def log_revenue_wedge_result(run_id: str, payload: RevenueRunResultPayload, request: Request):
    user_id = get_authenticated_user_id(request)
    service = get_founder_workspace_service()
    try:
        workspace = service.log_run_result(
            user_id,
            run_id,
            {
                "outcome": (payload.outcome or "").strip() or "unknown",
                "replies": max(0, payload.replies or 0),
                "calls_booked": max(0, payload.calls_booked or 0),
                "deals_closed": max(0, payload.deals_closed or 0),
                "top_objection": (payload.top_objection or "").strip(),
                "metric_delta": (payload.metric_delta or "").strip(),
                "notes": (payload.notes or "").strip(),
            },
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Revenue wedge run not found.") from exc
    return _serialize_workspace(workspace)
