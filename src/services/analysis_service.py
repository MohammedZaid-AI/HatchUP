import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisService:
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

    def _row_to_analysis(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "analysis_id": row["analysis_id"],
            "title": row.get("title") or "Untitled Analysis",
            "deck": row.get("deck_data"),
            "insights": row.get("insights") or {},
            "research": row.get("deep_research") or [],
            "memo": row.get("memo") or {},
            "created_at": row.get("created_at"),
            "status": row.get("status") or "draft",
            "user_id": row.get("user_id"),
        }

    def list_analyses(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("analyses")
            .select("analysis_id,title,deck_data")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = response.data or []
        items: List[Dict[str, Any]] = []
        for row in rows:
            deck = row.get("deck_data") or {}
            startup_name = (deck.get("startup_name") or "").strip() if isinstance(deck, dict) else ""
            title = (row.get("title") or "").strip() or startup_name or "Untitled Analysis"
            items.append(
                {
                    "analysis_id": row["analysis_id"],
                    "title": title,
                }
            )
        return items

    def create_analysis(self, user_id: str, title: Optional[str] = None, status: str = "draft") -> Dict[str, Any]:
        analysis_id = str(uuid.uuid4())
        insert_payload = {
            "analysis_id": analysis_id,
            "user_id": user_id,
            "title": (title or "Untitled Analysis").strip() or "Untitled Analysis",
            "deck_data": None,
            "insights": {},
            "deep_research": [],
            "memo": {},
            "status": status,
        }
        response = self.client.table("analyses").insert(insert_payload).execute()
        row = (response.data or [None])[0]
        if not row:
            raise RuntimeError("Failed to create analysis")
        return self._row_to_analysis(row)

    def get_analysis(self, user_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table("analyses")
            .select("*")
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            return None
        return self._row_to_analysis(row)

    def get_latest_analysis(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            return None
        return self._row_to_analysis(row)

    def get_or_create_active_analysis(self, user_id: str, active_analysis_id: Optional[str]) -> Dict[str, Any]:
        if active_analysis_id:
            found = self.get_analysis(user_id, active_analysis_id)
            if found:
                return found
        latest = self.get_latest_analysis(user_id)
        if latest:
            return latest
        return self.create_analysis(user_id=user_id)

    def update_deck_and_reset_outputs(self, user_id: str, analysis_id: str, deck_data: Dict[str, Any]) -> Dict[str, Any]:
        title = ((deck_data or {}).get("startup_name") or "").strip() or "Untitled Analysis"
        update_payload = {
            "deck_data": deck_data,
            "insights": {},
            "memo": {},
            "deep_research": [],
            "title": title,
            "status": "draft",
            "updated_at": _utc_now(),
        }
        response = (
            self.client.table("analyses")
            .update(update_payload)
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            raise KeyError("analysis_id_not_found")
        return self._row_to_analysis(row)

    def update_memo_and_insights(
        self,
        user_id: str,
        analysis_id: str,
        deck_data: Dict[str, Any],
        memo: Dict[str, Any],
        insights: Dict[str, Any],
    ) -> Dict[str, Any]:
        title = ((deck_data or {}).get("startup_name") or "").strip() or "Untitled Analysis"
        update_payload = {
            "deck_data": deck_data,
            "memo": memo,
            "insights": insights,
            "title": title,
            "status": "completed",
            "updated_at": _utc_now(),
        }
        response = (
            self.client.table("analyses")
            .update(update_payload)
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            raise KeyError("analysis_id_not_found")
        return self._row_to_analysis(row)

    def update_deep_research(self, user_id: str, analysis_id: str, deep_research: List[Dict[str, Any]]) -> Dict[str, Any]:
        update_payload = {
            "deep_research": deep_research,
            "updated_at": _utc_now(),
        }
        response = (
            self.client.table("analyses")
            .update(update_payload)
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            raise KeyError("analysis_id_not_found")
        return self._row_to_analysis(row)
