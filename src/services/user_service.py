import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserService:
    def __init__(self) -> None:
        try:
            from supabase import create_client
        except Exception as exc:
            raise RuntimeError("Supabase client is not installed. Add `supabase` to dependencies.") from exc

        supabase_url = os.environ.get("SUPABASE_URL")
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not supabase_url or not service_key:
            raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")

        self.client = create_client(supabase_url, service_key)
        self.database_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")

    @staticmethod
    def _extract_user_email(user_obj) -> str:
        if isinstance(user_obj, dict):
            return (user_obj.get("email") or "").strip().lower()
        return (getattr(user_obj, "email", "") or "").strip().lower()

    @staticmethod
    def _extract_users_list(response_obj):
        if isinstance(response_obj, dict):
            users = response_obj.get("users")
            return users if isinstance(users, list) else []
        users_attr = getattr(response_obj, "users", None)
        if isinstance(users_attr, list):
            return users_attr
        if hasattr(response_obj, "model_dump"):
            try:
                dumped = response_obj.model_dump()
                users = dumped.get("users")
                return users if isinstance(users, list) else []
            except Exception:
                return []
        return []

    def auth_user_exists_by_email(self, email: str) -> bool:
        target = (email or "").strip().lower()
        if not target:
            return False

        admin = self.client.auth.admin
        page = 1
        per_page = 200
        max_pages = 50
        uses_pagination = True

        while page <= max_pages:
            try:
                response = admin.list_users(page=page, per_page=per_page)
            except TypeError:
                # Older SDK variants may not support pagination kwargs.
                uses_pagination = False
                response = admin.list_users()

            users = self._extract_users_list(response)
            for user in users:
                if self._extract_user_email(user) == target:
                    return True

            if not uses_pagination:
                return False
            if len(users) < per_page:
                return False
            page += 1

        return False

    def _ensure_users_table_if_possible(self) -> None:
        if not self.database_url:
            try:
                self.client.table("users").select("user_id").limit(1).execute()
                return
            except Exception as exc:
                raise RuntimeError(
                    "users table is missing. Set SUPABASE_DB_URL or DATABASE_URL to auto-create it."
                ) from exc
        try:
            import psycopg
        except Exception:
            raise RuntimeError("psycopg is required for automatic users table creation when SUPABASE_DB_URL is configured.")

        ddl_sql = """
        CREATE TABLE IF NOT EXISTS public.users (
            user_id uuid PRIMARY KEY,
            email text NOT NULL UNIQUE,
            name text,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(ddl_sql)
            connection.commit()

    def upsert_first_login(self, user_id: str, email: str, name: Optional[str]) -> Dict[str, str]:
        self._ensure_users_table_if_possible()
        payload = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "created_at": _utc_now(),
        }
        try:
            response = (
                self.client.table("users")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
        except Exception as exc:
            # If email is already present with another user_id (e.g., provider migration),
            # update the existing email row so auth flow is not blocked.
            if "users_email_key" in str(exc) or "duplicate key value violates unique constraint" in str(exc):
                try:
                    update_response = (
                        self.client.table("users")
                        .update({
                            "user_id": user_id,
                            "name": name,
                        })
                        .eq("email", email)
                        .execute()
                    )
                    update_row = (update_response.data or [None])[0]
                    if update_row:
                        return {
                            "user_id": update_row.get("user_id", user_id),
                            "email": update_row.get("email", email),
                            "name": update_row.get("name", name),
                            "created_at": update_row.get("created_at", payload["created_at"]),
                        }
                except Exception as update_exc:
                    raise RuntimeError(f"Failed to update existing email user in public.users: {update_exc}") from update_exc
            raise RuntimeError(f"Failed to upsert user in public.users: {exc}") from exc
        row = (response.data or [None])[0]
        if row:
            return {
                "user_id": row.get("user_id", user_id),
                "email": row.get("email", email),
                "name": row.get("name", name),
                "created_at": row.get("created_at", payload["created_at"]),
            }
        return payload


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService()
