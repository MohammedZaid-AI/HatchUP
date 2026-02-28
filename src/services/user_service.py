import os
import re
from time import time
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
        self.avatar_bucket = "avatars"
        self.avatar_file_size_limit = 5 * 1024 * 1024
        self.avatar_allowed_mime_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]

    @staticmethod
    def _is_missing_profile_column_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "pgrst204" in message
            and (
                "avatar_url" in message
                or "full_name" in message
                or "updated_at" in message
            )
        )

    def _profile_schema_migration_hint(self) -> str:
        return (
            "public.users is missing profile columns. Run this SQL in Supabase SQL Editor:\n"
            "ALTER TABLE public.users\n"
            "  ADD COLUMN IF NOT EXISTS full_name text,\n"
            "  ADD COLUMN IF NOT EXISTS avatar_url text,\n"
            "  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();\n"
            "UPDATE public.users SET full_name = COALESCE(full_name, name)\n"
            "WHERE full_name IS NULL OR full_name = '';"
        )

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
            full_name text,
            avatar_url text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE public.users
            ADD COLUMN IF NOT EXISTS full_name text,
            ADD COLUMN IF NOT EXISTS avatar_url text,
            ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                  AND column_name = 'name'
            ) THEN
                UPDATE public.users
                SET full_name = COALESCE(full_name, name)
                WHERE full_name IS NULL OR full_name = '';
            END IF;
        END $$;
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(ddl_sql)
            connection.commit()

    def ensure_avatar_storage_ready(self) -> Dict[str, object]:
        """Ensure avatars bucket and access policies exist."""
        if self.database_url:
            return self._ensure_avatar_storage_with_sql()
        return self._ensure_avatar_bucket_with_api_only()

    def _ensure_avatar_storage_with_sql(self) -> Dict[str, object]:
        try:
            import psycopg
        except Exception:
            raise RuntimeError("psycopg is required for automatic storage setup when SUPABASE_DB_URL is configured.")

        setup_sql = """
        INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        VALUES (
            'avatars',
            'avatars',
            true,
            5242880,
            ARRAY['image/jpeg','image/png','image/webp','image/gif']::text[]
        )
        ON CONFLICT (id) DO UPDATE
        SET public = EXCLUDED.public,
            file_size_limit = EXCLUDED.file_size_limit,
            allowed_mime_types = EXCLUDED.allowed_mime_types;

        DROP POLICY IF EXISTS "Allow authenticated uploads" ON storage.objects;
        CREATE POLICY "Allow authenticated uploads"
        ON storage.objects
        FOR INSERT
        TO authenticated
        WITH CHECK (bucket_id = 'avatars');

        DROP POLICY IF EXISTS "Allow authenticated avatar updates" ON storage.objects;
        CREATE POLICY "Allow authenticated avatar updates"
        ON storage.objects
        FOR UPDATE
        TO authenticated
        USING (bucket_id = 'avatars')
        WITH CHECK (bucket_id = 'avatars');

        DROP POLICY IF EXISTS "Allow public read" ON storage.objects;
        CREATE POLICY "Allow public read"
        ON storage.objects
        FOR SELECT
        TO public
        USING (bucket_id = 'avatars');
        """

        try:
            with psycopg.connect(self.database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(setup_sql)
                connection.commit()
        except Exception as exc:
            raise RuntimeError(f"Failed to configure avatars storage bucket/policies: {exc}") from exc

        return {
            "bucket": self.avatar_bucket,
            "public": True,
            "file_size_limit": self.avatar_file_size_limit,
            "allowed_mime_types": self.avatar_allowed_mime_types,
        }

    def _ensure_avatar_bucket_with_api_only(self) -> Dict[str, object]:
        storage = self.client.storage
        try:
            buckets = storage.list_buckets()
            bucket_names = set()
            if isinstance(buckets, list):
                for item in buckets:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("id")
                    else:
                        name = getattr(item, "name", None) or getattr(item, "id", None)
                    if name:
                        bucket_names.add(str(name))
            if self.avatar_bucket not in bucket_names:
                self._create_avatar_bucket_with_fallback_signatures(storage)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to verify avatars storage bucket: {exc}") from exc

        return {
            "bucket": self.avatar_bucket,
            "public": True,
            "file_size_limit": self.avatar_file_size_limit,
            "allowed_mime_types": self.avatar_allowed_mime_types,
        }

    def _create_avatar_bucket_with_fallback_signatures(self, storage) -> None:
        options = {
            "public": True,
            "file_size_limit": self.avatar_file_size_limit,
            "allowed_mime_types": self.avatar_allowed_mime_types,
        }
        attempts = [
            ("create_bucket(name, options)", lambda: storage.create_bucket(self.avatar_bucket, options)),
            ("create_bucket(name, options=...)", lambda: storage.create_bucket(self.avatar_bucket, options=options)),
            (
                "create_bucket(body:name+opts)",
                lambda: storage.create_bucket({
                    "name": self.avatar_bucket,
                    "public": True,
                    "file_size_limit": self.avatar_file_size_limit,
                    "allowed_mime_types": self.avatar_allowed_mime_types,
                }),
            ),
            (
                "create_bucket(body:id+name+opts)",
                lambda: storage.create_bucket({
                    "id": self.avatar_bucket,
                    "name": self.avatar_bucket,
                    "public": True,
                    "file_size_limit": self.avatar_file_size_limit,
                    "allowed_mime_types": self.avatar_allowed_mime_types,
                }),
            ),
        ]

        errors = []
        for label, call in attempts:
            try:
                call()
                return
            except Exception as exc:
                message = str(exc).lower()
                if "already exists" in message or "duplicate" in message:
                    return
                errors.append(f"{label}: {exc}")

        raise RuntimeError(
            "Failed to create avatars storage bucket via SDK fallback signatures. "
            f"Tried {len(attempts)} variants. Last errors: {' | '.join(errors[-2:])}. "
            "Run data/supabase_avatars_storage.sql in Supabase SQL Editor."
        )

    def upsert_first_login(
        self,
        user_id: str,
        email: str,
        full_name: Optional[str],
        avatar_url: Optional[str] = None,
    ) -> Dict[str, str]:
        self._ensure_users_table_if_possible()
        normalized_email = (email or "").strip().lower()
        existing = self.get_user_profile_by_id(user_id)
        resolved_full_name = full_name if full_name is not None else (existing.get("full_name") if existing else None)
        resolved_avatar_url = avatar_url if avatar_url is not None else (existing.get("avatar_url") if existing else None)
        payload = {
            "user_id": user_id,
            "email": normalized_email,
            "full_name": resolved_full_name,
            "avatar_url": resolved_avatar_url,
            "updated_at": _utc_now(),
        }
        if not existing:
            payload["created_at"] = _utc_now()
        try:
            response = (
                self.client.table("users")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
        except Exception as exc:
            if self._is_missing_profile_column_error(exc):
                if self.database_url:
                    self._ensure_users_table_if_possible()
                    try:
                        response = (
                            self.client.table("users")
                            .upsert(payload, on_conflict="user_id")
                            .execute()
                        )
                    except Exception as retry_exc:
                        raise RuntimeError(
                            f"Failed to upsert user after users schema migration attempt: {retry_exc}"
                        ) from retry_exc
                else:
                    raise RuntimeError(self._profile_schema_migration_hint()) from exc
            # If email is already present with another user_id (e.g., provider migration),
            # update the existing email row so auth flow is not blocked.
            if "users_email_key" in str(exc) or "duplicate key value violates unique constraint" in str(exc):
                try:
                    update_response = (
                        self.client.table("users")
                        .update({
                            "user_id": user_id,
                            "full_name": resolved_full_name,
                            "avatar_url": resolved_avatar_url,
                            "updated_at": _utc_now(),
                        })
                        .eq("email", normalized_email)
                        .execute()
                    )
                    update_row = (update_response.data or [None])[0]
                    if update_row:
                        return self._normalize_profile_row(update_row, default_user_id=user_id, default_email=normalized_email)
                except Exception as update_exc:
                    raise RuntimeError(f"Failed to update existing email user in public.users: {update_exc}") from update_exc
            raise RuntimeError(f"Failed to upsert user in public.users: {exc}") from exc
        row = (response.data or [None])[0]
        if row:
            return self._normalize_profile_row(row, default_user_id=user_id, default_email=normalized_email)
        return {
            "user_id": user_id,
            "email": normalized_email,
            "full_name": resolved_full_name or "",
            "avatar_url": resolved_avatar_url or "",
            "created_at": payload.get("created_at") or _utc_now(),
            "updated_at": payload["updated_at"],
        }

    def _normalize_profile_row(self, row: dict, default_user_id: str, default_email: str) -> Dict[str, str]:
        resolved_name = row.get("full_name") or row.get("name") or ""
        return {
            "user_id": row.get("user_id", default_user_id),
            "email": row.get("email", default_email),
            "full_name": resolved_name,
            "avatar_url": row.get("avatar_url") or "",
            "created_at": row.get("created_at", _utc_now()),
            "updated_at": row.get("updated_at", _utc_now()),
        }

    def get_user_profile_by_id(self, user_id: str) -> Optional[Dict[str, str]]:
        self._ensure_users_table_if_possible()
        try:
            response = (
                self.client.table("users")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            if self._is_missing_profile_column_error(exc):
                if self.database_url:
                    self._ensure_users_table_if_possible()
                    response = (
                        self.client.table("users")
                        .select("*")
                        .eq("user_id", user_id)
                        .limit(1)
                        .execute()
                    )
                else:
                    raise RuntimeError(self._profile_schema_migration_hint()) from exc
            else:
                raise RuntimeError(f"Failed to fetch user profile from public.users: {exc}") from exc
        row = (response.data or [None])[0]
        if not row:
            return None
        return self._normalize_profile_row(row, default_user_id=user_id, default_email=row.get("email", ""))

    def get_or_create_profile(self, user_id: str, email: str, full_name: Optional[str], avatar_url: Optional[str]) -> Dict[str, str]:
        profile = self.get_user_profile_by_id(user_id)
        if profile:
            needs_update = False
            updates = {}
            normalized_email = (email or "").strip().lower()
            if normalized_email and normalized_email != profile.get("email"):
                updates["email"] = normalized_email
                needs_update = True
            if full_name and not profile.get("full_name"):
                updates["full_name"] = full_name
                needs_update = True
            if avatar_url and not profile.get("avatar_url"):
                updates["avatar_url"] = avatar_url
                needs_update = True
            if needs_update:
                updates["updated_at"] = _utc_now()
                try:
                    response = (
                        self.client.table("users")
                        .update(updates)
                        .eq("user_id", user_id)
                        .execute()
                    )
                    row = (response.data or [None])[0]
                    if row:
                        return self._normalize_profile_row(row, default_user_id=user_id, default_email=normalized_email)
                except Exception as exc:
                    raise RuntimeError(f"Failed to update existing profile in public.users: {exc}") from exc
            return profile
        return self.upsert_first_login(user_id=user_id, email=email, full_name=full_name, avatar_url=avatar_url)

    def update_profile(self, user_id: str, full_name: Optional[str], avatar_url: Optional[str]) -> Dict[str, str]:
        self._ensure_users_table_if_possible()
        updates = {
            "updated_at": _utc_now(),
        }
        if full_name is not None:
            updates["full_name"] = full_name.strip()
        if avatar_url is not None:
            updates["avatar_url"] = avatar_url.strip()
        try:
            response = (
                self.client.table("users")
                .update(updates)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            if self._is_missing_profile_column_error(exc):
                if self.database_url:
                    self._ensure_users_table_if_possible()
                    try:
                        response = (
                            self.client.table("users")
                            .update(updates)
                            .eq("user_id", user_id)
                            .execute()
                        )
                    except Exception as retry_exc:
                        raise RuntimeError(
                            f"Failed to update user profile after users schema migration attempt: {retry_exc}"
                        ) from retry_exc
                else:
                    raise RuntimeError(self._profile_schema_migration_hint()) from exc
            else:
                raise RuntimeError(f"Failed to update user profile in public.users: {exc}") from exc
        row = (response.data or [None])[0]
        if not row:
            existing = self.get_user_profile_by_id(user_id)
            if existing:
                return existing
            raise RuntimeError("Profile row not found for update.")
        return self._normalize_profile_row(row, default_user_id=user_id, default_email=row.get("email", ""))

    def upload_profile_avatar(self, user_id: str, filename: str, content_type: str, file_bytes: bytes) -> str:
        if not user_id:
            raise RuntimeError("Missing user_id for avatar upload.")
        if not file_bytes:
            raise RuntimeError("Avatar file payload is empty.")

        self.ensure_avatar_storage_ready()
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename or "avatar")
        path = f"{user_id}/{int(time() * 1000)}-{safe_name}"

        storage = self.client.storage
        bucket_factory = getattr(storage, "from_", None) or getattr(storage, "from", None)
        if not bucket_factory:
            raise RuntimeError("Supabase storage API is unavailable on current SDK.")
        bucket = bucket_factory(self.avatar_bucket)

        file_options = {
            "content-type": content_type or "application/octet-stream",
            "upsert": "false",
        }
        attempts = [
            ("upload(path, bytes, options)", lambda: bucket.upload(path, file_bytes, file_options)),
            ("upload(path, bytes, file_options=...)", lambda: bucket.upload(path, file_bytes, file_options=file_options)),
            ("upload(file=..., path=...)", lambda: bucket.upload(file=file_bytes, path=path, file_options=file_options)),
        ]
        upload_errors = []
        for label, call in attempts:
            try:
                result = call()
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(str(result.get("error")))
                break
            except Exception as exc:
                upload_errors.append(f"{label}: {exc}")
        else:
            raise RuntimeError(
                "Failed to upload avatar file to Supabase Storage. "
                f"Tried {len(attempts)} SDK variants. Last errors: {' | '.join(upload_errors[-2:])}"
            )

        public_url = self._extract_public_url(bucket, path)
        if not public_url:
            raise RuntimeError("Avatar uploaded but public URL could not be generated.")
        return public_url

    @staticmethod
    def _extract_public_url(bucket, path: str) -> str:
        try:
            result = bucket.get_public_url(path)
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch public avatar URL: {exc}") from exc

        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                return data.get("publicUrl") or data.get("publicURL") or ""
            return result.get("publicUrl") or result.get("publicURL") or ""
        if hasattr(result, "get"):
            try:
                return result.get("publicUrl") or result.get("publicURL") or ""
            except Exception:
                return ""
        if hasattr(result, "public_url"):
            return getattr(result, "public_url") or ""
        return ""


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService()
