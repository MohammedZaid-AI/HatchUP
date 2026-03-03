import os
import uuid
from typing import Any, Dict, List, Optional


class ChatService:
    def __init__(self) -> None:
        try:
            from supabase import create_client
        except Exception as exc:
            raise RuntimeError("Supabase client is not installed. Add `supabase` to dependencies.") from exc

        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
        if not supabase_url or not supabase_key:
            raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY.")
        self.client = create_client(supabase_url, supabase_key)

    def _normalize_message_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "user_id": row.get("user_id"),
            "chat_id": row.get("chat_id"),
            "role": row.get("role"),
            "content": row.get("content") or "",
            "created_at": row.get("created_at"),
        }

    def create_chat_id(self) -> str:
        return str(uuid.uuid4())

    def get_latest_chat_id(self, user_id: str) -> Optional[str]:
        if not user_id:
            return None
        response = (
            self.client.table("chats")
            .select("chat_id")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            return None
        return str(row.get("chat_id") or "").strip() or None

    def get_chat_messages(self, user_id: str, chat_id: str) -> List[Dict[str, Any]]:
        if not user_id or not chat_id:
            return []
        response = (
            self.client.table("chats")
            .select("id,user_id,chat_id,role,content,created_at")
            .eq("user_id", user_id)
            .eq("chat_id", chat_id)
            .order("created_at", desc=False)
            .execute()
        )
        rows = response.data or []
        return [self._normalize_message_row(row) for row in rows]

    def save_message(self, user_id: str, chat_id: str, role: str, content: str) -> Dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")
        if not chat_id:
            raise ValueError("chat_id is required")
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        payload = {
            "user_id": user_id,
            "chat_id": chat_id,
            "role": role,
            "content": content or "",
        }
        response = self.client.table("chats").insert(payload).execute()
        row = (response.data or [None])[0]
        if not row:
            raise RuntimeError("Failed to save chat message.")
        return self._normalize_message_row(row)
