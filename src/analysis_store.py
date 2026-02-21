import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Request, Response

SESSION_COOKIE_NAME = "hatchup_sid"
SESSION_HEADER_NAME = "x-hatchup-session"
STORE_DIR = Path("data") / "analysis_store"
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


def _ensure_store_dir() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def _store_path(session_id: str) -> Path:
    return STORE_DIR / f"{session_id}.json"


def ensure_session_id(request: Request, response: Optional[Response] = None) -> str:
    header_session = request.headers.get(SESSION_HEADER_NAME)
    session_id = None
    if header_session and SESSION_ID_RE.match(header_session):
        session_id = header_session
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if not session_id:
        session_id = str(uuid.uuid4())
    if response is not None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,  # 30 days
        )
    return session_id


def load_analysis(session_id: str) -> Optional[Dict[str, Any]]:
    _ensure_store_dir()
    path = _store_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_analysis(session_id: str, analysis: Dict[str, Any]) -> None:
    _ensure_store_dir()
    payload = dict(analysis)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _store_path(session_id).write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_analysis_record() -> Dict[str, Any]:
    now = _utc_now()
    return {
        "deck": None,
        "insights": None,
        "research": [],
        "memo": None,
        "created_at": now,
        "updated_at": now,
    }


def _normalize_workspace(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    workspace = raw or {}
    analyses = workspace.get("analyses")
    active_analysis_id = workspace.get("active_analysis_id")

    if isinstance(analyses, dict) and analyses:
        normalized: Dict[str, Any] = {}
        for analysis_id, analysis in analyses.items():
            if not isinstance(analysis, dict):
                analysis = {}
            created_at = analysis.get("created_at") or _utc_now()
            updated_at = analysis.get("updated_at") or created_at
            normalized[analysis_id] = {
                "deck": analysis.get("deck"),
                "insights": analysis.get("insights"),
                "research": analysis.get("research") or [],
                "memo": analysis.get("memo"),
                "created_at": created_at,
                "updated_at": updated_at,
            }
        if not active_analysis_id or active_analysis_id not in normalized:
            active_analysis_id = next(iter(normalized.keys()))
        workspace["analyses"] = normalized
        workspace["active_analysis_id"] = active_analysis_id
        return workspace

    # Backward compatibility migration from single-analysis payload.
    if workspace.get("data") or workspace.get("memo") or workspace.get("summary"):
        analysis_id = str(uuid.uuid4())
        created_at = workspace.get("created_at") or _utc_now()
        workspace = {
            "active_analysis_id": analysis_id,
            "analyses": {
                analysis_id: {
                    "deck": workspace.get("data"),
                    "insights": workspace.get("summary"),
                    "research": workspace.get("research") or [],
                    "memo": workspace.get("memo"),
                    "created_at": created_at,
                    "updated_at": workspace.get("updated_at") or _utc_now(),
                }
            },
        }
        return workspace

    # Empty workspace bootstrap.
    analysis_id = str(uuid.uuid4())
    workspace = {
        "active_analysis_id": analysis_id,
        "analyses": {analysis_id: _new_analysis_record()},
    }
    return workspace


def load_workspace(session_id: str) -> Dict[str, Any]:
    current = load_analysis(session_id)
    normalized = _normalize_workspace(current)
    # Persist normalization/migration result.
    save_analysis(session_id, normalized)
    return normalized


def save_workspace(session_id: str, workspace: Dict[str, Any]) -> None:
    save_analysis(session_id, workspace)


def list_analyses(session_id: str) -> List[Dict[str, Any]]:
    workspace = load_workspace(session_id)
    analyses = workspace.get("analyses", {})
    ordered = sorted(
        analyses.items(),
        key=lambda item: item[1].get("created_at", ""),
        reverse=True,
    )
    result: List[Dict[str, Any]] = []
    for analysis_id, analysis in ordered:
        deck = analysis.get("deck") or {}
        startup_name = (deck.get("startup_name") or "").strip()
        created_at = analysis.get("created_at")
        title = startup_name or f"Analysis {analysis_id[:8]}"
        if not startup_name:
            title = "Untitled Analysis"
        result.append(
            {
                "analysis_id": analysis_id,
                "title": title,
                "startup_name": startup_name or None,
                "created_at": created_at,
                "has_deck": bool(deck),
            }
        )
    return result


def create_new_analysis(session_id: str) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analysis_id = str(uuid.uuid4())
    workspace.setdefault("analyses", {})[analysis_id] = _new_analysis_record()
    workspace["active_analysis_id"] = analysis_id
    save_workspace(session_id, workspace)
    return {"analysis_id": analysis_id, "analysis": workspace["analyses"][analysis_id]}


def set_active_analysis(session_id: str, analysis_id: str) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analyses = workspace.get("analyses", {})
    if analysis_id not in analyses:
        raise KeyError("analysis_id_not_found")
    workspace["active_analysis_id"] = analysis_id
    save_workspace(session_id, workspace)
    return analyses[analysis_id]


def get_active_analysis(session_id: str) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analysis_id = workspace["active_analysis_id"]
    analysis = workspace["analyses"][analysis_id]
    return {"analysis_id": analysis_id, "analysis": analysis}


def upsert_data(session_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analysis_id = workspace["active_analysis_id"]
    analysis = workspace["analyses"][analysis_id]
    analysis["deck"] = data
    analysis["memo"] = None
    analysis["insights"] = None
    analysis["research"] = []
    analysis["updated_at"] = _utc_now()
    save_workspace(session_id, workspace)
    return {"analysis_id": analysis_id, "analysis": analysis}


def upsert_full(session_id: str, data: Dict[str, Any], memo: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analysis_id = workspace["active_analysis_id"]
    analysis = workspace["analyses"][analysis_id]
    analysis["deck"] = data
    analysis["memo"] = memo
    analysis["insights"] = summary
    analysis["updated_at"] = _utc_now()
    save_workspace(session_id, workspace)
    return {"analysis_id": analysis_id, "analysis": analysis}


def upsert_research(session_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    workspace = load_workspace(session_id)
    analysis_id = workspace["active_analysis_id"]
    analysis = workspace["analyses"][analysis_id]
    analysis["research"] = messages
    analysis["updated_at"] = _utc_now()
    save_workspace(session_id, workspace)
    return {"analysis_id": analysis_id, "analysis": analysis}
