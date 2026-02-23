import re
import uuid
from typing import Optional

from fastapi import Request, Response

SESSION_COOKIE_NAME = "hatchup_sid"
SESSION_HEADER_NAME = "x-hatchup-session"
ACTIVE_ANALYSIS_COOKIE_NAME = "hatchup_active_analysis_id"
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


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
            max_age=60 * 60 * 24 * 30,
        )

    return session_id


def get_active_analysis_id(request: Request) -> Optional[str]:
    analysis_id = request.headers.get("x-hatchup-analysis-id")
    if analysis_id:
        return analysis_id
    return request.cookies.get(ACTIVE_ANALYSIS_COOKIE_NAME)


def set_active_analysis_id(response: Response, analysis_id: str) -> None:
    response.set_cookie(
        key=ACTIVE_ANALYSIS_COOKIE_NAME,
        value=analysis_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
