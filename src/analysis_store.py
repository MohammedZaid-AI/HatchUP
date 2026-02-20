import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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


def upsert_data(session_id: str, data: Dict[str, Any]) -> None:
    current = load_analysis(session_id) or {}
    current["data"] = data
    save_analysis(session_id, current)


def upsert_full(session_id: str, data: Dict[str, Any], memo: Dict[str, Any], summary: Dict[str, Any]) -> None:
    save_analysis(session_id, {"data": data, "memo": memo, "summary": summary})
