import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FounderWorkspaceService:
    WORKSPACE_TYPE = "founder_revenue_wedge"
    WORKSPACE_STATUS = "draft"
    WORKSPACE_TITLE = "Revenue Wedge Engine"

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

    def _empty_state(self) -> Dict[str, Any]:
        return {
            "workspace_type": self.WORKSPACE_TYPE,
            "inputs": [],
            "latest_run_id": None,
            "learned_patterns": {
                "best_icp": "",
                "recurring_objections": [],
                "winning_messages": [],
                "last_adaptation": "",
                "strongest_problem": "",
                "winning_pattern_summary": "",
            },
        }

    def _normalize_workspace(self, row: Dict[str, Any]) -> Dict[str, Any]:
        state = row.get("deck_data") or {}
        runs = row.get("deep_research") or []
        latest_run_id = state.get("latest_run_id")
        latest_run = None
        if latest_run_id:
            latest_run = next((run for run in runs if run.get("run_id") == latest_run_id), None)
        if not latest_run and runs:
            latest_run = runs[-1]
            state["latest_run_id"] = latest_run.get("run_id")
        return {
            "workspace_id": row["analysis_id"],
            "inputs": state.get("inputs") or [],
            "latest_run_id": state.get("latest_run_id"),
            "latest_run": latest_run,
            "runs": list(reversed(runs)),
            "learned_patterns": state.get("learned_patterns") or self._empty_state()["learned_patterns"],
            "updated_at": row.get("updated_at") or row.get("created_at"),
        }

    def _build_learned_patterns(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not runs:
            return self._empty_state()["learned_patterns"]

        objection_counts: Dict[str, int] = {}
        winning_messages: List[str] = []
        best_icp = ""
        best_score = -1
        strongest_problem = ""
        last_adaptation = ""
        winning_pattern_summary = ""

        for run in runs:
            brief = run.get("decision_brief") or {}
            outcome = run.get("outcome_log") or run.get("result_log") or {}
            comparison = run.get("comparison") or {}
            replies = int(outcome.get("replies") or 0)
            calls_booked = int(outcome.get("calls_booked") or 0)
            deals_closed = int(outcome.get("deals_closed") or 0)
            score = replies + (calls_booked * 3) + (deals_closed * 8)
            if score > best_score and brief.get("recommended_icp"):
                best_score = score
                best_icp = brief.get("recommended_icp") or ""
                strongest_problem = brief.get("core_problem") or strongest_problem
                headline = (((brief.get("assets") or {}).get("landing_page_headline")) or "").strip()
                if headline:
                    winning_messages = [headline]
                winning_pattern_summary = (
                    f"Winning runs concentrated around {best_icp} when the message made the decision output clearer and the core problem was "
                    f"{strongest_problem}."
                ).strip()

            objection = (outcome.get("top_objection") or "").strip()
            if objection:
                objection_counts[objection] = objection_counts.get(objection, 0) + 1

            next_move = (comparison.get("next_move") or "").strip()
            if next_move:
                last_adaptation = next_move

        recurring_objections = [
            objection for objection, _count in sorted(objection_counts.items(), key=lambda item: item[1], reverse=True)[:3]
        ]
        return {
            "best_icp": best_icp,
            "recurring_objections": recurring_objections,
            "winning_messages": winning_messages[:3],
            "last_adaptation": last_adaptation,
            "strongest_problem": strongest_problem,
            "winning_pattern_summary": winning_pattern_summary,
        }

    def get_or_create_workspace(self, user_id: str) -> Dict[str, Any]:
        response = (
            self.client.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .eq("title", self.WORKSPACE_TITLE)
            .execute()
        )
        rows = response.data or []
        row = next(
            (
                item for item in rows
                if (item.get("deck_data") or {}).get("workspace_type") == self.WORKSPACE_TYPE
            ),
            None,
        )
        if row:
            return self._normalize_workspace(row)

        insert_payload = {
            "analysis_id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": self.WORKSPACE_TITLE,
            "deck_data": self._empty_state(),
            "insights": {},
            "memo": {},
            "deep_research": [],
            "status": self.WORKSPACE_STATUS,
        }
        create_response = self.client.table("analyses").insert(insert_payload).execute()
        created = (create_response.data or [None])[0]
        if not created:
            raise RuntimeError("Failed to create founder workspace.")
        return self._normalize_workspace(created)

    def _update_row(self, user_id: str, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table("analyses")
            .update(payload)
            .eq("analysis_id", workspace_id)
            .eq("user_id", user_id)
            .execute()
        )
        row = (response.data or [None])[0]
        if not row:
            raise RuntimeError("Founder workspace update failed.")
        return self._normalize_workspace(row)

    def save_input(self, user_id: str, input_record: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.get_or_create_workspace(user_id)
        inputs = workspace["inputs"]
        existing_index = next((index for index, item in enumerate(inputs) if item.get("input_id") == input_record["input_id"]), None)
        if existing_index is None:
            inputs.append(input_record)
        else:
            inputs[existing_index] = input_record
        return self._update_row(
            user_id=user_id,
            workspace_id=workspace["workspace_id"],
            payload={
                "deck_data": {
                    "workspace_type": self.WORKSPACE_TYPE,
                    "inputs": inputs,
                    "latest_run_id": workspace.get("latest_run_id"),
                    "learned_patterns": workspace.get("learned_patterns") or self._empty_state()["learned_patterns"],
                },
                "updated_at": _utc_now(),
            },
        )

    def delete_input(self, user_id: str, input_id: str) -> Dict[str, Any]:
        workspace = self.get_or_create_workspace(user_id)
        filtered_inputs = [item for item in workspace["inputs"] if item.get("input_id") != input_id]
        filtered_runs = []
        for run in workspace["runs"]:
            if input_id in (run.get("input_ids") or []):
                run = {**run, "input_ids": [value for value in (run.get("input_ids") or []) if value != input_id]}
            filtered_runs.append(run)
        latest_run_id = workspace.get("latest_run_id")
        if latest_run_id and not any(run.get("run_id") == latest_run_id for run in filtered_runs):
            latest_run_id = filtered_runs[0].get("run_id") if filtered_runs else None
        return self._update_row(
            user_id=user_id,
            workspace_id=workspace["workspace_id"],
            payload={
                "deck_data": {
                    "workspace_type": self.WORKSPACE_TYPE,
                    "inputs": filtered_inputs,
                    "latest_run_id": latest_run_id,
                    "learned_patterns": self._build_learned_patterns(list(reversed(filtered_runs))),
                },
                "deep_research": list(reversed(filtered_runs)),
                "updated_at": _utc_now(),
            },
        )

    def save_run(self, user_id: str, run_record: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.get_or_create_workspace(user_id)
        runs = list(reversed(workspace["runs"]))
        runs.append(run_record)
        learned_patterns = self._build_learned_patterns(runs)
        brief = run_record.get("decision_brief") or {}
        signal_quality = run_record.get("signal_quality") or {}
        return self._update_row(
            user_id=user_id,
            workspace_id=workspace["workspace_id"],
            payload={
                "deck_data": {
                    "workspace_type": self.WORKSPACE_TYPE,
                    "inputs": workspace["inputs"],
                    "latest_run_id": run_record.get("run_id"),
                    "learned_patterns": learned_patterns,
                },
                "insights": {
                    "recommended_icp": brief.get("recommended_icp"),
                    "confidence_score": brief.get("confidence_score") or signal_quality.get("score"),
                    "core_problem": brief.get("core_problem"),
                    "decision": brief.get("decision"),
                    "best_icp": learned_patterns.get("best_icp"),
                    "recurring_objections": learned_patterns.get("recurring_objections"),
                    "generation_source": run_record.get("generation_source"),
                    "insufficient_signal": signal_quality.get("insufficient_signal", False),
                },
                "memo": brief,
                "deep_research": runs,
                "updated_at": _utc_now(),
            },
        )

    def log_run_result(self, user_id: str, run_id: str, result_log: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.get_or_create_workspace(user_id)
        runs = list(reversed(workspace["runs"]))
        updated = False
        for index, run in enumerate(runs):
            if run.get("run_id") == run_id:
                runs[index] = {
                    **run,
                    "outcome_log": {
                        **(run.get("outcome_log") or run.get("result_log") or {}),
                        **result_log,
                        "logged_at": _utc_now(),
                    },
                }
                updated = True
                break
        if not updated:
            raise KeyError("run_not_found")
        learned_patterns = self._build_learned_patterns(runs)
        latest_run = next((run for run in runs if run.get("run_id") == workspace.get("latest_run_id")), runs[-1] if runs else {})
        latest_brief = (latest_run or {}).get("decision_brief") or {}
        return self._update_row(
            user_id=user_id,
            workspace_id=workspace["workspace_id"],
            payload={
                "deck_data": {
                    "workspace_type": self.WORKSPACE_TYPE,
                    "inputs": workspace["inputs"],
                    "latest_run_id": workspace.get("latest_run_id"),
                    "learned_patterns": learned_patterns,
                },
                "deep_research": runs,
                "insights": {
                    "recommended_icp": latest_brief.get("recommended_icp"),
                    "confidence_score": latest_brief.get("confidence_score"),
                    "core_problem": latest_brief.get("core_problem"),
                    "decision": latest_brief.get("decision"),
                    "best_icp": learned_patterns.get("best_icp"),
                    "recurring_objections": learned_patterns.get("recurring_objections"),
                },
                "updated_at": _utc_now(),
            },
        )
