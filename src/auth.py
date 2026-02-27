import os
from functools import lru_cache
from typing import Optional, Any

from fastapi import HTTPException, Request

AUTH_COOKIE_NAME = "hatchup_access_token"


@lru_cache(maxsize=1)
def get_supabase_auth_client():
    try:
        from supabase import create_client
    except Exception as exc:
        raise RuntimeError("Supabase client is not installed. Add `supabase` to dependencies.") from exc

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_anon_key:
        raise RuntimeError("Supabase auth is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.")

    return create_client(supabase_url, supabase_anon_key)


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    prefix = "bearer "
    lower = authorization.lower()
    if lower.startswith(prefix):
        token = authorization[len(prefix):].strip()
        return token or None
    return None


def get_request_access_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    token = _extract_bearer_token(auth_header)
    if token:
        return token
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    return cookie_token or None


def require_user_id(request: Request) -> str:
    user = require_user(request)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return user_id


def require_user(request: Request) -> Any:
    token = get_request_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        client = get_supabase_auth_client()
        auth_response = client.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    user = getattr(auth_response, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return user
