from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from typing import Optional

from src.auth import require_user
from src.services.user_service import get_user_service

router = APIRouter()


class EmailExistsPayload(BaseModel):
    email: str


class UpdateProfilePayload(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


def _extract_user_name(user) -> str:
    metadata = getattr(user, "user_metadata", {}) or {}
    return (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("preferred_name")
        or ""
    )

def _extract_user_avatar_url(user) -> str:
    metadata = getattr(user, "user_metadata", {}) or {}
    return (
        metadata.get("avatar_url")
        or metadata.get("picture")
        or ""
    )


@router.post("/api/auth/sync-user")
async def sync_user(request: Request):
    user = require_user(request)
    user_id = getattr(user, "id", None)
    email = getattr(user, "email", None)
    full_name = _extract_user_name(user)
    avatar_url = _extract_user_avatar_url(user)

    if not user_id or not email:
        raise HTTPException(status_code=400, detail="Invalid authenticated user payload")

    try:
        service = get_user_service()
        persisted = service.upsert_first_login(
            user_id=user_id,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected sync-user failure: {exc}") from exc
    return {
        "ok": True,
        "user": {
            "id": persisted["user_id"],
            "email": persisted["email"],
            "full_name": persisted.get("full_name") or "",
            "avatar_url": persisted.get("avatar_url") or "",
            "name": persisted.get("full_name") or "",
            "created_at": persisted["created_at"],
            "updated_at": persisted.get("updated_at"),
        },
    }


@router.post("/api/auth/email-exists")
async def email_exists(payload: EmailExistsPayload):
    email = (payload.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    try:
        service = get_user_service()
        exists = service.auth_user_exists_by_email(email)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected email-exists failure: {exc}") from exc
    return {
        "ok": True,
        "exists": bool(exists),
    }


@router.get("/api/auth/profile")
async def get_profile(request: Request):
    user = require_user(request)
    user_id = getattr(user, "id", None)
    email = getattr(user, "email", None)
    full_name = _extract_user_name(user)
    avatar_url = _extract_user_avatar_url(user)

    if not user_id or not email:
        raise HTTPException(status_code=400, detail="Invalid authenticated user payload")

    try:
        service = get_user_service()
        profile = service.get_or_create_profile(
            user_id=user_id,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected get-profile failure: {exc}") from exc

    return {
        "ok": True,
        "profile": {
            "user_id": profile["user_id"],
            "email": profile["email"],
            "full_name": profile.get("full_name") or "",
            "avatar_url": profile.get("avatar_url") or "",
            "created_at": profile["created_at"],
            "updated_at": profile.get("updated_at"),
        },
    }


@router.put("/api/auth/profile")
async def update_profile(request: Request, payload: UpdateProfilePayload):
    user = require_user(request)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid authenticated user payload")

    try:
        service = get_user_service()
        profile = service.update_profile(
            user_id=user_id,
            full_name=payload.full_name,
            avatar_url=payload.avatar_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected update-profile failure: {exc}") from exc

    return {
        "ok": True,
        "profile": {
            "user_id": profile["user_id"],
            "email": profile["email"],
            "full_name": profile.get("full_name") or "",
            "avatar_url": profile.get("avatar_url") or "",
            "created_at": profile["created_at"],
            "updated_at": profile.get("updated_at"),
        },
    }


@router.post("/api/auth/storage/avatars/prepare")
async def prepare_avatar_storage(request: Request):
    # Require authenticated user to keep this setup path scoped to signed-in usage.
    require_user(request)
    try:
        service = get_user_service()
        result = service.ensure_avatar_storage_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected storage-prepare failure: {exc}") from exc
    return {
        "ok": True,
        "storage": result,
    }


@router.post("/api/auth/profile/avatar")
async def upload_profile_avatar(request: Request, file: UploadFile = File(...)):
    user = require_user(request)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid authenticated user payload")

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed.")

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read upload file: {exc}") from exc

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Profile image is too large. Maximum size is 5MB.")

    try:
        service = get_user_service()
        avatar_url = service.upload_profile_avatar(
            user_id=user_id,
            filename=file.filename or "avatar",
            content_type=content_type,
            file_bytes=file_bytes,
        )
        profile = service.update_profile(user_id=user_id, full_name=None, avatar_url=avatar_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected avatar upload failure: {exc}") from exc

    return {
        "ok": True,
        "avatar_url": avatar_url,
        "profile": {
            "user_id": profile["user_id"],
            "email": profile["email"],
            "full_name": profile.get("full_name") or "",
            "avatar_url": profile.get("avatar_url") or "",
            "created_at": profile["created_at"],
            "updated_at": profile.get("updated_at"),
        },
    }
