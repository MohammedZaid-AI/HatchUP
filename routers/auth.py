from fastapi import APIRouter, HTTPException, Request

from src.auth import require_user
from src.services.user_service import get_user_service

router = APIRouter()


def _extract_user_name(user) -> str:
    metadata = getattr(user, "user_metadata", {}) or {}
    return (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("preferred_name")
        or ""
    )


@router.post("/api/auth/sync-user")
async def sync_user(request: Request):
    user = require_user(request)
    user_id = getattr(user, "id", None)
    email = getattr(user, "email", None)
    name = _extract_user_name(user)

    if not user_id or not email:
        raise HTTPException(status_code=400, detail="Invalid authenticated user payload")

    try:
        service = get_user_service()
        persisted = service.upsert_first_login(user_id=user_id, email=email, name=name)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected sync-user failure: {exc}") from exc
    return {
        "ok": True,
        "user": {
            "id": persisted["user_id"],
            "email": persisted["email"],
            "name": persisted.get("name") or "",
            "created_at": persisted["created_at"],
        },
    }
