import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from src.models import (
    RevenueCluster,
    RevenueEvidenceItem,
    RevenueSignalExtraction,
    RevenueWedgeDecisionBrief,
    RevenueWedgeInputRecord,
)


SOURCE_WEIGHTS = {
    "sales_call": 4,
    "customer_interview": 3,
    "lost_deal": 5,
    "support": 3,
    "landing_page": 2,
    "pitch_deck": 2,
    "crm_export": 4,
}

STAGE_WEIGHTS = {
    "awareness": 1,
    "discovery": 2,
    "evaluation": 3,
    "proposal": 4,
    "decision": 5,
    "onboarding": 3,
    "renewal": 4,
    "unknown": 1,
}

GENERIC_PHRASES = (
    "improve landing page",
    "increase engagement",
    "optimize funnel",
    "improve conversion",
    "enhance user experience",
    "better messaging",
    "refine positioning",
    "drive growth",
    "increase awareness",
)

RAW_LABEL_PATTERNS = (
    "lost reason",
    "trust issue",
    "manual",
    "founder",
    "ops",
    "revops",
    "stuck",
)

PRODUCT_NAME = "HatchUp"

CATEGORY_KEYWORDS = {
    "segment": ["founder", "operator", "ops", "finance", "sales", "agency", "smb", "startup", "revops", "team"],
    "pain": ["manual", "slow", "waste", "stuck", "messy", "unclear", "broken", "delay", "late", "hard"],
    "objection": ["expensive", "price", "budget", "trust", "accuracy", "integration", "security", "risk"],
    "trigger": ["urgent", "asap", "this week", "launch", "renewal", "pipeline", "quota", "revenue"],
    "blocker": ["approval", "procurement", "blocked", "stall", "stalled", "legal", "workflow", "buy-in"],
    "feature_request": ["need", "want", "wish", "export", "integration", "dashboard", "reporting"],
    "urgency": ["urgent", "now", "immediately", "this week", "today", "asap"],
    "language": ["said", "called", "described", "worded", "phrased"],
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize_text(value).lower()).strip("-")


def _clip(value: str, limit: int = 2200) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[:limit] + " ..."


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[\.\!\?\n])\s+", text or "")
    return [_normalize_text(part) for part in parts if _normalize_text(part)]


def _extract_label(sentence: str, keyword: str) -> str:
    lowered = sentence.lower()
    if keyword in {"revops", "ops", "finance", "sales", "agency", "smb", "startup", "founder", "team"}:
        patterns = (
            r"(revenue operations managers?)",
            r"(revops teams?)",
            r"(finance teams?)",
            r"(sales teams?)",
            r"(operators?)",
            r"(agencies?)",
            r"(smb teams?)",
            r"(startup founders?)",
            r"(founders?)",
        )
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return match.group(1)

    pain_patterns = (
        r"too ([a-z0-9-]+(?: [a-z0-9-]+){0,3})",
        r"still needs ([a-z0-9-]+(?: [a-z0-9-]+){0,3})",
        r"cannot ([a-z0-9-]+(?: [a-z0-9-]+){0,5})",
        r"can't ([a-z0-9-]+(?: [a-z0-9-]+){0,5})",
        r"did not trust ([a-z0-9-]+(?: [a-z0-9-]+){0,3})",
    )
    for pattern in pain_patterns:
        match = re.search(pattern, lowered)
        if match:
            phrase = re.split(r"\b(and|or|before|after|because|but)\b", match.group(1))[0]
            return phrase.strip(" .,:;!?")

    words = re.findall(r"[a-zA-Z0-9']+", sentence.lower())
    if not words:
        return keyword
    try:
        index = words.index(keyword.split()[0])
    except ValueError:
        index = next((idx for idx, value in enumerate(words) if keyword in value), 0)
    start = max(0, index - 2)
    end = min(len(words), index + 3)
    phrase = " ".join(words[start:end]).strip()
    return phrase or keyword


def _score_outcome(source_tag: str, quote: str) -> int:
    text = (quote or "").lower()
    score = 0
    if source_tag == "lost_deal":
        score += 14
    if source_tag == "sales_call":
        score += 6
    if source_tag == "crm_export":
        score += 8
    if any(term in text for term in ("lost", "churn", "stalled", "no decision", "blocked", "budget", "expensive")):
        score += 10
    if any(term in text for term in ("won", "closed", "renewed", "expanded")):
        score += 6
    return score


def _quote_to_phrase(quote: str, limit: int = 10) -> str:
    words = re.findall(r"[A-Za-z0-9']+", quote or "")
    return " ".join(words[:limit]).strip() or "the repeated complaint"


def _paraphrase_quote(quote: str) -> str:
    text = _normalize_text(quote).strip("\"'")
    lowered = text.lower()
    if "manual cleanup" in lowered or ("manual" in lowered and "cleanup" in lowered):
        return "teams still need manual cleanup before they can trust the workflow"
    if "trust data accuracy" in lowered or ("accuracy" in lowered and "trust" in lowered):
        return "buyers do not trust the output enough to use it in real decisions"
    if "spreadsheet" in lowered:
        return "the product still feels like another spreadsheet-heavy process"
    if "sign off" in lowered:
        return "finance will not approve the rollout without stronger proof"
    if "stalled" in lowered or "no decision" in lowered:
        return "deals are slowing down because confidence breaks late in the buying cycle"
    if "slow" in lowered or "messy" in lowered:
        return "buyers describe the current workflow as too messy to trust"
    words = re.findall(r"[A-Za-z0-9']+", lowered)
    return ("buyers describe " + " ".join(words[:8]).strip()) if words else "buyers describe the workflow as hard to trust"


def _humanize_segment(label: str, evidence_quotes: List[str], stage_hint: str) -> str:
    text = _normalize_text(label).lower()
    evidence_text = " ".join(evidence_quotes).lower()
    if "revops" in text or "revenue operations" in text or ("ops" in text and "finance" in evidence_text):
        return "Revenue operations leaders at early-stage B2B SaaS teams"
    if "finance" in text:
        return "Finance leads at small B2B software teams reviewing rollout risk"
    if "agency" in text:
        return "Agency owners with lean delivery teams managing client-facing operations"
    if "founder" in text or "startup" in text:
        return "Early-stage B2B SaaS founders making hands-on buying decisions"
    if "sales" in text:
        return "Sales leaders at lean B2B teams trying to move deals without adding operational drag"
    return f"Operators in {stage_hint} who are close to the buying decision"


def _humanize_problem(label: str, evidence_quotes: List[str]) -> str:
    combined = f"{label} {' '.join(evidence_quotes)}".lower()
    if "accuracy" in combined or "trust" in combined:
        return "Buyers do not trust the output enough to use it in real decisions"
    if "manual" in combined or "cleanup" in combined or "spreadsheet" in combined:
        return "The workflow still feels too manual for a lean team to trust and adopt"
    if "budget" in combined or "expensive" in combined or "sign off" in combined:
        return "The buyer cannot justify the rollout because the value still feels risky"
    if "integration" in combined:
        return "The product feels hard to fit into the buyer's existing workflow"
    if "approval" in combined or "procurement" in combined:
        return "Deals stall because internal approval arrives after confidence has already dropped"
    return "The strongest repeated blocker is still slowing down purchase confidence"


def _humanize_trigger(label: str, evidence_quotes: List[str]) -> str:
    combined = f"{label} {' '.join(evidence_quotes)}".lower()
    if "quarter" in combined or "quota" in combined or "pipeline" in combined:
        return "the team is under near-term revenue pressure"
    if "budget" in combined or "sign off" in combined or "approval" in combined:
        return "internal approval is happening right now"
    if "launch" in combined:
        return "they need the workflow in place before an upcoming launch"
    if "renewal" in combined:
        return "they need proof before renewal or expansion"
    return "the buyer has a near-term reason to act now"


def _sounds_like_raw_label(value: str) -> bool:
    text = _normalize_text(value).lower()
    if not text:
        return True
    if len(text.split()) <= 2 and any(token in text for token in RAW_LABEL_PATTERNS):
        return True
    return any(pattern in text for pattern in ("lost reason", "trust issue", "manual and", "revops teams: stop"))


def _clean_copy(value: str) -> str:
    return _normalize_text(re.sub(r"\s+([,.;:!?])", r"\1", value or ""))


def _strip_product_name(value: str) -> str:
    return _clean_copy(re.sub(r"\bHatchUp\b", "", value or "", flags=re.IGNORECASE))


def _trigger_to_clause(trigger: str) -> str:
    text = _normalize_text(trigger).lower()
    if "internal approval" in text:
        return "buyers are already looking for internal sign-off"
    if "revenue pressure" in text:
        return "the team is under immediate revenue pressure"
    if "launch" in text:
        return "the team is trying to get in place before launch"
    if "renewal" in text:
        return "renewal pressure is making the risk harder to ignore"
    return "the team needs to make a buying decision soon"


def _metric_change_label(current: str, previous: str, field_name: str) -> str:
    if not current and not previous:
        return ""
    if current == previous:
        return f"{field_name} stayed the same"
    return f"{field_name} shifted from {previous or 'none'} to {current or 'none'}"


class RevenueWedgeEngine:
    def __init__(self, api_key: Optional[str], model_name: str = "openai/gpt-oss-20b") -> None:
        self.api_key = (api_key or os.environ.get("GROQ_API_KEY") or "").strip()
        self.model_name = model_name
        self.llm = None
        if self.api_key:
            self.llm = ChatGroq(
                temperature=0,
                model_name=model_name,
                groq_api_key=self.api_key,
            )

    def generate(
        self,
        inputs: List[Dict[str, Any]],
        previous_run: Optional[Dict[str, Any]] = None,
        run_history: Optional[List[Dict[str, Any]]] = None,
        learned_patterns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_inputs = [RevenueWedgeInputRecord(**item) for item in inputs if item.get("raw_text")]
        if not normalized_inputs:
            raise ValueError("At least one founder input is required.")

        extraction, extraction_source = self._extract_signals(normalized_inputs)
        cluster_map = self._cluster_observations(extraction.observations)
        summary = self._summarize_clusters(cluster_map)
        decision_context = self._build_decision_context(summary, previous_run, run_history or [], learned_patterns or {})
        quality = self._assess_signal_quality(normalized_inputs, extraction, summary, extraction_source)
        comparison = self._build_run_comparison(previous_run, None, learned_patterns or {})
        if quality["insufficient_signal"]:
            return {
                "signals": summary,
                "synthesis_notes": extraction.synthesis_notes,
                "decision_brief": None,
                "generation_source": extraction_source,
                "signal_quality": quality,
                "comparison": comparison,
            }
        brief, decision_source = self._build_decision_brief(summary, extraction, decision_context, previous_run)
        comparison = self._build_run_comparison(previous_run, brief.model_dump(), learned_patterns or {})
        brief = RevenueWedgeDecisionBrief.model_validate(
            {
                **brief.model_dump(),
                "comparison_to_last_run": comparison.get("adaptation_reasoning") or brief.comparison_to_last_run,
                "run_to_run_intelligence": comparison,
            }
        )
        return {
            "signals": summary,
            "synthesis_notes": extraction.synthesis_notes,
            "decision_brief": brief.model_dump(),
            "generation_source": decision_source,
            "signal_quality": quality,
            "comparison": comparison,
        }

    def _build_corpus(self, inputs: List[RevenueWedgeInputRecord]) -> str:
        chunks = []
        for item in inputs:
            chunks.append(
                "\n".join(
                    [
                        f"INPUT_ID: {item.input_id}",
                        f"TITLE: {_normalize_text(item.title)}",
                        f"TAG: {item.tag}",
                        f"SOURCE_TYPE: {item.source_type}",
                        "CONTENT:",
                        _clip(item.raw_text, 2600),
                    ]
                )
            )
        return "\n\n---\n\n".join(chunks)

    def _extract_signals(self, inputs: List[RevenueWedgeInputRecord]):
        if not self.llm:
            return self._fallback_extraction(inputs), "fallback_heuristics"

        parser = PydanticOutputParser(pydantic_object=RevenueSignalExtraction)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are Revenue Wedge Engine, a founder decision system.
Extract only repeated commercial signals from startup inputs.

Rules:
- Emit observations only when the input contains direct evidence.
- Every supporting_quote must be a short verbatim quote from the inputs.
- If a claim has no quote, do not emit it.
- Categories allowed: segment, pain, objection, trigger, blocker, feature_request, urgency, language, stage.
- Prefer labels that are concrete and operational, not generic strategy language.
- Stage must be one of: awareness, discovery, evaluation, proposal, decision, onboarding, renewal, unknown.
- impact_direction must be positive, negative, or neutral.
- Prioritize signals tied to lost deals, pricing friction, urgency, workflow blockers, repeated ICP language, and buyer outcomes.
- Ignore compliments, generic advice, and broad startup platitudes.
Return valid JSON matching the schema.""",
                ),
                (
                    "user",
                    "Extract structured revenue signals from these founder inputs.\n\n{corpus}\n\n{format_instructions}",
                ),
            ]
        )
        chain = prompt | self.llm | parser
        try:
            return chain.invoke(
                {
                    "corpus": self._build_corpus(inputs),
                    "format_instructions": parser.get_format_instructions(),
                }
            ), "llm_extraction"
        except Exception:
            return self._fallback_extraction(inputs), "fallback_heuristics"

    def _fallback_extraction(self, inputs: List[RevenueWedgeInputRecord]) -> RevenueSignalExtraction:
        observations = []
        notes = []
        for item in inputs:
            sentences = _split_sentences(item.raw_text)
            matched = 0
            for sentence in sentences:
                lowered = sentence.lower()
                stage = "evaluation" if item.tag in {"sales_call", "lost_deal", "crm_export"} else "discovery"
                for category, keywords in CATEGORY_KEYWORDS.items():
                    keyword = next((value for value in keywords if value in lowered), None)
                    if not keyword:
                        continue
                    impact_direction = "negative" if category in {"pain", "objection", "blocker"} else "positive"
                    if category == "language":
                        impact_direction = "neutral"
                    label = _extract_label(sentence, keyword)
                    if label in {"said", "described", "called", "worded", "phrased"}:
                        continue
                    observations.append(
                        {
                            "input_id": item.input_id,
                            "source_tag": item.tag,
                            "category": category,
                            "label": label,
                            "supporting_quote": _clip(sentence, 180),
                            "stage": stage,
                            "impact_direction": impact_direction,
                        }
                    )
                    matched += 1
            if matched:
                notes.append(f"{item.title} added {matched} evidence-backed signals.")

        if not observations:
            seed_input = inputs[0]
            seed_sentences = _split_sentences(seed_input.raw_text)
            seed_quote = _clip(seed_sentences[0] if seed_sentences else seed_input.raw_text, 180)
            observations = [
                {
                    "input_id": seed_input.input_id,
                    "source_tag": seed_input.tag,
                    "category": "pain",
                    "label": _extract_label(seed_quote, "manual"),
                    "supporting_quote": seed_quote,
                    "stage": "evaluation",
                    "impact_direction": "negative",
                }
            ]
            notes.append("Fallback extraction found only one explicit commercial quote, so the engine is operating conservatively.")

        return RevenueSignalExtraction.model_validate(
            {
                "observations": observations,
                "synthesis_notes": notes[:8] or ["Signals extracted with fallback heuristics."],
            }
        )

    def _cluster_observations(self, observations: List[Any]) -> Dict[str, List[RevenueCluster]]:
        groups: Dict[str, Dict[str, Any]] = {}
        for observation in observations:
            data = observation.model_dump() if hasattr(observation, "model_dump") else dict(observation)
            label = _normalize_text(data.get("label"))
            category = data.get("category") or "pain"
            key = f"{category}:{_slug(label)}"
            if key not in groups:
                groups[key] = {
                    "category": category,
                    "label": label,
                    "frequency": 0,
                    "weighted_frequency": 0,
                    "positive_weight": 0,
                    "negative_weight": 0,
                    "outcome_score": 0,
                    "sources": set(),
                    "evidence_quotes": [],
                    "stages": set(),
                }
            source_tag = data.get("source_tag") or "customer_interview"
            weight = SOURCE_WEIGHTS.get(source_tag, 2)
            stage = data.get("stage") or "unknown"
            stage_weight = STAGE_WEIGHTS.get(stage, 1)
            outcome_score = _score_outcome(source_tag, data.get("supporting_quote") or "")
            groups[key]["frequency"] += 1
            groups[key]["weighted_frequency"] += weight
            groups[key]["outcome_score"] += outcome_score
            if data.get("impact_direction") == "negative":
                groups[key]["negative_weight"] += weight + stage_weight
            elif data.get("impact_direction") == "positive":
                groups[key]["positive_weight"] += weight + stage_weight
            groups[key]["sources"].add(source_tag)
            groups[key]["stages"].add(stage)
            quote = _clip(data.get("supporting_quote") or "", 140)
            if quote and quote not in groups[key]["evidence_quotes"]:
                groups[key]["evidence_quotes"].append(quote)

        cluster_map: Dict[str, List[RevenueCluster]] = defaultdict(list)
        for payload in groups.values():
            revenue_impact = min(100, payload["weighted_frequency"] * 7 + payload["negative_weight"] * 2 + payload["outcome_score"])
            conversion_signal = min(
                100,
                max(0, 25 + payload["positive_weight"] * 4 + payload["outcome_score"] - payload["negative_weight"]),
            )
            score = min(
                100,
                payload["weighted_frequency"] * 5
                + payload["frequency"] * 8
                + payload["outcome_score"]
                + max(payload["negative_weight"], payload["positive_weight"]),
            )
            cluster_map[payload["category"]].append(
                RevenueCluster(
                    category=payload["category"],
                    label=payload["label"],
                    score=score,
                    frequency=payload["frequency"],
                    weighted_frequency=payload["weighted_frequency"],
                    revenue_impact=revenue_impact,
                    conversion_signal=conversion_signal,
                    outcome_score=payload["outcome_score"],
                    sources=sorted(payload["sources"]),
                    evidence_quotes=payload["evidence_quotes"][:4],
                    stages=sorted(payload["stages"]),
                )
            )

        for category in cluster_map:
            cluster_map[category] = sorted(
                cluster_map[category],
                key=lambda item: (item.score, item.outcome_score, item.frequency, item.revenue_impact),
                reverse=True,
            )[:6]
        return dict(cluster_map)

    def _summarize_clusters(self, cluster_map: Dict[str, List[RevenueCluster]]) -> Dict[str, List[RevenueCluster]]:
        return {
            "segments": cluster_map.get("segment", []),
            "pains": cluster_map.get("pain", []),
            "objections": cluster_map.get("objection", []),
            "buying_triggers": cluster_map.get("trigger", []),
            "conversion_blockers": cluster_map.get("blocker", []),
            "feature_requests": cluster_map.get("feature_request", []),
            "urgency_signals": cluster_map.get("urgency", []),
            "customer_language": cluster_map.get("language", []),
            "stage_signals": cluster_map.get("stage", []),
        }

    def _build_adaptation_signal(
        self,
        previous_run: Optional[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, str]:
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        previous_outcome = (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {}
        replies = int(previous_outcome.get("replies") or 0)
        calls_booked = int(previous_outcome.get("calls_booked") or 0)
        deals_closed = int(previous_outcome.get("deals_closed") or 0)

        if replies > 0 and calls_booked == 0 and deals_closed == 0:
            return {
                "mode": "go_deeper",
                "instruction": "Replies improved, but conversions did not. Keep the ICP tight and move the recommendation deeper into pricing, proof, onboarding, or rollout risk.",
            }
        if replies == 0 and calls_booked == 0 and deals_closed == 0 and previous_brief:
            return {
                "mode": "pivot",
                "instruction": "The last run did not create measurable movement. Pivot either the core problem or the ICP instead of repeating the same wedge.",
            }
        if calls_booked > 0 or deals_closed > 0:
            return {
                "mode": "double_down",
                "instruction": "The last run produced downstream movement. Double down on the same ICP and sharpen the message that already worked.",
            }
        if learned_patterns.get("best_icp"):
            return {
                "mode": "memory_bias",
                "instruction": f"Past results suggest {learned_patterns.get('best_icp')} has been the strongest ICP so far. Only move away if the new evidence is clearly stronger.",
            }
        return {
            "mode": "neutral",
            "instruction": "No strong prior outcome signal exists yet. Use the freshest evidence, but note what needs to be learned next.",
        }

    def _build_run_comparison(
        self,
        previous_run: Optional[Dict[str, Any]],
        current_brief: Optional[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        previous_outcome = (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {}
        adaptation = self._build_adaptation_signal(previous_run, learned_patterns)
        if not previous_brief:
            return {
                "previous_run_id": "",
                "what_changed": ["This is the first tracked Revenue Wedge run, so future runs will compare against it."],
                "what_improved": [],
                "what_failed": [],
                "next_move": current_brief.get("decision") if current_brief else "Log outcomes from this run so the engine can adapt next time.",
                "adaptation_reasoning": adaptation["instruction"],
            }

        what_changed = [
            value
            for value in (
                _metric_change_label(
                    (current_brief or {}).get("recommended_icp", ""),
                    previous_brief.get("recommended_icp", ""),
                    "ICP",
                ),
                _metric_change_label(
                    (current_brief or {}).get("core_problem", ""),
                    previous_brief.get("core_problem", ""),
                    "core problem",
                ),
            )
            if value
        ]
        what_improved = []
        if int(previous_outcome.get("replies") or 0) > 0:
            what_improved.append(f"Last run generated {int(previous_outcome.get('replies') or 0)} replies.")
        if int(previous_outcome.get("calls_booked") or 0) > 0:
            what_improved.append(f"Last run booked {int(previous_outcome.get('calls_booked') or 0)} calls.")
        if int(previous_outcome.get("deals_closed") or 0) > 0:
            what_improved.append(f"Last run closed {int(previous_outcome.get('deals_closed') or 0)} deals.")

        what_failed = []
        if int(previous_outcome.get("replies") or 0) > 0 and int(previous_outcome.get("calls_booked") or 0) == 0:
            what_failed.append("Interest showed up, but it did not turn into booked calls.")
        if int(previous_outcome.get("replies") or 0) == 0 and int(previous_outcome.get("calls_booked") or 0) == 0 and int(previous_outcome.get("deals_closed") or 0) == 0:
            what_failed.append("The last run did not create measurable movement.")
        if (previous_outcome.get("top_objection") or "").strip():
            what_failed.append(f"Top objection last run: {previous_outcome.get('top_objection').strip()}.")

        return {
            "previous_run_id": (previous_run or {}).get("run_id") or "",
            "what_changed": what_changed,
            "what_improved": what_improved,
            "what_failed": what_failed,
            "next_move": (current_brief or {}).get("decision") or adaptation["instruction"],
            "adaptation_reasoning": adaptation["instruction"],
        }

    def _build_decision_context(
        self,
        summary: Dict[str, List[RevenueCluster]],
        previous_run: Optional[Dict[str, Any]],
        run_history: List[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        segments = summary.get("segments") or []
        problems = (summary.get("pains") or []) + (summary.get("objections") or []) + (summary.get("conversion_blockers") or [])
        problems = sorted(problems, key=lambda item: (item.score, item.outcome_score, item.frequency), reverse=True)
        triggers = summary.get("buying_triggers") or []
        language = summary.get("customer_language") or []
        stages = summary.get("stage_signals") or []

        chosen_segment = segments[0] if segments else None
        chosen_problem = problems[0] if problems else None
        chosen_trigger = triggers[0] if triggers else None
        chosen_language = language[0] if language else None
        chosen_stage = stages[0] if stages else None
        stage_hint = chosen_stage.label if chosen_stage else "evaluation"

        contradiction_note = "No major contradiction detected in the current inputs."
        if len(segments) > 1 and segments[0].score - segments[1].score <= 8:
            contradiction_note = (
                f"Two ICPs surfaced, but {segments[0].label} outranked {segments[1].label} on weighted repetition and revenue impact, "
                "so the engine is forcing focus instead of splitting effort."
            )
        elif len(problems) > 1 and problems[0].score - problems[1].score <= 8:
            contradiction_note = (
                f"Several pains appeared, but {problems[0].label} beat {problems[1].label} once frequency and lost-deal weight were combined."
            )

        evidence_bank = []
        for cluster in [chosen_segment, chosen_problem, chosen_trigger, chosen_language]:
            if not cluster:
                continue
            for quote in cluster.evidence_quotes[:2]:
                evidence_bank.append(
                    {
                        "quote": quote,
                        "source_tags": cluster.sources,
                        "signal": cluster.label,
                        "why_it_matters": (
                            f"This quote supports the chosen {cluster.category} signal because it repeated "
                            f"{cluster.frequency} time(s) with weighted score {cluster.score}."
                        ),
                    }
                )

        unique_evidence = []
        seen = set()
        for item in evidence_bank:
            key = item["quote"]
            if key in seen:
                continue
            seen.add(key)
            unique_evidence.append(item)

        adaptation = self._build_adaptation_signal(previous_run, learned_patterns)
        interpreted_icp = _humanize_segment(
            chosen_segment.label if chosen_segment else "",
            chosen_segment.evidence_quotes if chosen_segment else [],
            stage_hint,
        )
        interpreted_problem = _humanize_problem(
            chosen_problem.label if chosen_problem else "",
            chosen_problem.evidence_quotes if chosen_problem else [],
        )
        interpreted_trigger = _humanize_trigger(
            chosen_trigger.label if chosen_trigger else "",
            (chosen_trigger.evidence_quotes if chosen_trigger else []) + (chosen_problem.evidence_quotes if chosen_problem else []),
        )
        contradiction_resolution = contradiction_note.replace(
            chosen_segment.label if chosen_segment else "",
            interpreted_icp,
        ).replace(
            chosen_problem.label if chosen_problem else "",
            interpreted_problem,
        )

        interpreted_evidence = []
        for item in unique_evidence[:2]:
            interpreted_evidence.append(
                {
                    **item,
                    "why_it_matters": _clean_copy(_paraphrase_quote(item["quote"]).capitalize() + "."),
                }
            )

        return {
            "recommended_icp": interpreted_icp,
            "core_problem": interpreted_problem,
            "buying_trigger": interpreted_trigger,
            "language_anchor": _quote_to_phrase(
                (chosen_language.evidence_quotes[0] if chosen_language and chosen_language.evidence_quotes else "")
                or (chosen_problem.evidence_quotes[0] if chosen_problem and chosen_problem.evidence_quotes else "")
            ),
            "stage_focus": stage_hint,
            "contradiction_resolution": contradiction_resolution,
            "evidence": interpreted_evidence,
            "adaptation_mode": adaptation["mode"],
            "adaptation_instruction": adaptation["instruction"],
            "previous_outcome": (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {},
            "run_history_count": len(run_history),
            "learned_patterns": learned_patterns,
        }

    def _assess_signal_quality(
        self,
        inputs: List[RevenueWedgeInputRecord],
        extraction: RevenueSignalExtraction,
        summary: Dict[str, List[RevenueCluster]],
        extraction_source: str,
    ) -> Dict[str, Any]:
        total_text = " ".join(item.raw_text for item in inputs)
        alpha_tokens = re.findall(r"[a-zA-Z]{3,}", total_text)
        unique_alpha_tokens = {token.lower() for token in alpha_tokens}
        commercial_categories = [
            category for category in ("segments", "pains", "objections", "conversion_blockers", "buying_triggers")
            if summary.get(category)
        ]
        evidence_count = sum(len(item.evidence_quotes) for values in summary.values() for item in values)
        observation_count = len(extraction.observations)
        input_count = len(inputs)
        total_chars = len(_normalize_text(total_text))
        meaningful_input_count = sum(
            1 for item in inputs
            if len(re.findall(r"[a-zA-Z]{3,}", item.raw_text or "")) >= 8 or len(_normalize_text(item.raw_text)) >= 80
        )

        score = 0
        if input_count >= 2:
            score += 20
        elif input_count == 1:
            score += 8
        if meaningful_input_count >= 2:
            score += 20
        elif meaningful_input_count == 1:
            score += 8
        if total_chars >= 250:
            score += 18
        elif total_chars >= 120:
            score += 10
        if len(unique_alpha_tokens) >= 20:
            score += 16
        elif len(unique_alpha_tokens) >= 10:
            score += 8
        if len(commercial_categories) >= 3:
            score += 18
        elif len(commercial_categories) >= 2:
            score += 10
        if observation_count >= 6:
            score += 16
        elif observation_count >= 3:
            score += 8
        if evidence_count >= 4:
            score += 12
        elif evidence_count >= 2:
            score += 6
        if extraction_source == "fallback_heuristics":
            score -= 18

        insufficient_reasons = []
        if meaningful_input_count == 0:
            insufficient_reasons.append("The uploaded inputs do not contain enough readable commercial language yet.")
        if len(commercial_categories) < 2:
            insufficient_reasons.append("The engine could not find enough repeated commercial patterns across ICPs, pains, objections, or blockers.")
        if extraction_source == "fallback_heuristics":
            insufficient_reasons.append("The result would rely on fallback heuristics rather than reliable LLM extraction.")

        insufficient_signal = score < 45 or len(commercial_categories) < 2 or meaningful_input_count == 0
        if insufficient_signal and not insufficient_reasons:
            insufficient_reasons.append("There is not enough signal yet to make a trustworthy weekly wedge recommendation.")

        return {
            "score": max(0, min(100, score)),
            "insufficient_signal": insufficient_signal,
            "reasoning": insufficient_reasons[0] if insufficient_reasons else "Signal quality is sufficient for a weekly decision brief.",
            "details": insufficient_reasons,
            "extraction_source": extraction_source,
            "observation_count": observation_count,
            "commercial_categories": commercial_categories,
        }

    def _build_decision_brief(
        self,
        summary: Dict[str, List[RevenueCluster]],
        extraction: RevenueSignalExtraction,
        decision_context: Dict[str, Any],
        previous_run: Optional[Dict[str, Any]] = None,
    ):
        fallback = self._fallback_brief(summary, decision_context, previous_run)
        if not self.llm:
            return self._rewrite_for_humans(fallback, decision_context), "fallback_heuristics"

        parser = PydanticOutputParser(pydantic_object=RevenueWedgeDecisionBrief)
        compact_summary = {key: [item.model_dump() for item in value] for key, value in summary.items()}
        previous_text = json.dumps(previous_run or {}, ensure_ascii=True)[:2000]
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are HatchUp's Revenue Wedge Engine.
You are not a brainstorming assistant. You are forcing one decision for the next 7 days.

Hard rules:
- Output exactly one ICP, one core problem, and one decision.
- Every claim must be supported by the evidence bank. If you cannot support a claim, omit it.
- Every evidence.quote must be verbatim from the evidence bank.
- Interpret raw labels into natural operator language before writing.
- Never expose internal labels, extraction tokens, or awkward shorthand in the final answer.
- Use at most two short quotes for evidence, and never reuse raw quotes as landing page or outbound copy.
- Keep the core brief product-neutral. Do not mention HatchUp in the decision, why, execution plan, evidence, or assets.
- If you include product guidance, put it only in the optional how_to_use_hatchup field and keep it to 2-3 short lines.
- Do not use generic startup language such as \"improve landing page\", \"increase engagement\", or \"optimize funnel\".
- Write exact execution instructions and exact copy. No placeholders. No multiple options.
- Resolve contradictions explicitly and explain why one signal won.
- If the copy does not sound like something a real founder would ship this week, rewrite it.
- If your output can apply to any startup, it is wrong. Rewrite it.
- confidence_score must be 0-100.
Return valid JSON matching the schema.""",
                ),
                (
                    "user",
                    "Ranked signal summary:\n{summary}\n\nDecision context:\n{context}\n\nSynthesis notes:\n{notes}\n\nPrevious run context:\n{previous}\n\nGenerate the weekly decision brief.\n{format_instructions}",
                ),
            ]
        )
        chain = prompt | self.llm | parser
        try:
            brief = chain.invoke(
                {
                    "summary": json.dumps(compact_summary, ensure_ascii=True),
                    "context": json.dumps(decision_context, ensure_ascii=True),
                    "notes": json.dumps(extraction.synthesis_notes, ensure_ascii=True),
                    "previous": previous_text,
                    "format_instructions": parser.get_format_instructions(),
                }
            )
            if self._brief_is_generic(brief) or not self._brief_uses_context_evidence(brief, decision_context):
                return self._rewrite_for_humans(fallback, decision_context), "fallback_heuristics"
            return self._rewrite_for_humans(brief, decision_context), "llm_decision"
        except Exception:
            return self._rewrite_for_humans(fallback, decision_context), "fallback_heuristics"

    def _brief_is_generic(self, brief: RevenueWedgeDecisionBrief) -> bool:
        combined = " ".join(
            [
                brief.recommended_icp,
                brief.core_problem,
                brief.decision,
                brief.confidence_reasoning,
                brief.contradiction_resolution,
                " ".join(brief.this_week_execution or []),
                brief.assets.landing_page_headline,
                brief.assets.landing_page_subheadline,
                brief.assets.landing_page_cta,
                brief.assets.outbound_message,
                " ".join(brief.assets.sales_talk_track or []),
            ]
        ).lower()
        if any(phrase in combined for phrase in GENERIC_PHRASES):
            return True
        if PRODUCT_NAME.lower() in combined:
            return True
        return any(_sounds_like_raw_label(value) for value in (brief.recommended_icp, brief.core_problem, brief.decision))

    def _rewrite_for_humans(self, brief: RevenueWedgeDecisionBrief, decision_context: Dict[str, Any]) -> RevenueWedgeDecisionBrief:
        evidence_items = brief.evidence[:2]
        clean_icp = decision_context.get("recommended_icp") or brief.recommended_icp
        clean_problem = decision_context.get("core_problem") or brief.core_problem
        clean_trigger = decision_context.get("buying_trigger") or "the team has a near-term reason to act"
        trigger_clause = _trigger_to_clause(clean_trigger)
        landing_headline = _clean_copy("Give ops teams a workflow they can trust without adding more manual work")
        landing_subheadline = _clean_copy(
            f"Built for {clean_icp.lower()} that need to cut adoption risk and earn buyer trust faster when {trigger_clause}."
        )
        cta = "Book a focused workflow review"
        outbound = _clean_copy(
            f"Hi {{first_name}}, we keep seeing {clean_icp.lower()} hesitate when the workflow feels too risky to trust. "
            "There is usually a narrow workflow fix that removes that friction without adding more overhead. "
            "If this is active right now, I can walk you through the exact workflow in 15 minutes."
        )
        talk_track = [
            _clean_copy(f"Start with the pattern: teams like yours hesitate when {clean_problem.lower()}."),
            _clean_copy("Make the cost concrete: when confidence drops, rollout slows and internal approvals get harder."),
            _clean_copy(f"Ask one direct question: is this blocking adoption today, or is another issue showing up earlier in the process?"),
            _clean_copy(f"Close with one action: test a tighter workflow for {clean_icp.lower()} this week instead of expanding scope."),
        ]
        return RevenueWedgeDecisionBrief.model_validate(
            {
                **brief.model_dump(),
                "recommended_icp": clean_icp,
                "core_problem": clean_problem,
                "decision": _clean_copy(
                    f"Focus on {clean_icp.lower()} this week and anchor the message on one promise: teams can trust the workflow without adding more manual overhead."
                ),
                "this_week_execution": [
                    _clean_copy(f"Update the homepage hero to speak directly to {clean_icp.lower()} and the trust gap behind the current workflow."),
                    _clean_copy("Use the outbound message below only for accounts that are already feeling this pain in active buying conversations."),
                    _clean_copy("Run sales calls with the talk track below and log whether trust or workflow friction is the first objection that appears."),
                    _clean_copy("Review replies and call notes after seven days before widening the ICP or changing the promise."),
                ],
                "assets": {
                    "landing_page_headline": landing_headline,
                    "landing_page_subheadline": landing_subheadline,
                    "landing_page_cta": cta,
                    "outbound_message": outbound,
                    "sales_talk_track": talk_track,
                },
                "evidence": [item.model_dump() if hasattr(item, "model_dump") else item for item in evidence_items],
                "run_to_run_intelligence": {
                    "previous_run_id": "",
                    "what_changed": [],
                    "what_improved": [],
                    "what_failed": [],
                    "next_move": "",
                    "adaptation_reasoning": "",
                },
                "how_to_use_hatchup": [
                    "Use HatchUp to collect the next round of call notes and objections in one workspace.",
                    "Log replies, booked calls, closed deals, and the top objection so the next run adapts automatically.",
                ],
            }
        )

    def _brief_uses_context_evidence(self, brief: RevenueWedgeDecisionBrief, decision_context: Dict[str, Any]) -> bool:
        allowed_quotes = {item.get("quote") for item in (decision_context.get("evidence") or [])}
        if not brief.evidence:
            return False
        if not any(item.quote in allowed_quotes for item in brief.evidence):
            return False
        if brief.recommended_icp.strip().lower() != decision_context.get("recommended_icp", "").strip().lower():
            return False
        return len(brief.evidence) <= 2

    def _fallback_brief(
        self,
        summary: Dict[str, List[RevenueCluster]],
        decision_context: Dict[str, Any],
        previous_run: Optional[Dict[str, Any]] = None,
    ) -> RevenueWedgeDecisionBrief:
        icp = decision_context["recommended_icp"]
        problem = decision_context["core_problem"]
        trigger = decision_context["buying_trigger"]
        stage_focus = decision_context["stage_focus"]
        phrase = decision_context["language_anchor"]
        contradiction_resolution = decision_context["contradiction_resolution"]
        adaptation_instruction = decision_context.get("adaptation_instruction") or ""
        evidence_payload = decision_context.get("evidence") or []
        evidence = [RevenueEvidenceItem.model_validate(item) for item in evidence_payload[:4]]
        proof_quote = evidence[0].quote if evidence else problem
        secondary_quote = evidence[1].quote if len(evidence) > 1 else proof_quote

        comparison = "No previous run available yet."
        if previous_run and previous_run.get("decision_brief"):
            previous_icp = (((previous_run.get("decision_brief") or {}).get("recommended_icp")) or "").strip()
            if previous_icp and previous_icp != icp:
                comparison = f"The wedge shifted from {previous_icp} to {icp} because newer inputs created a stronger weighted pattern here."
            else:
                comparison = "The current run keeps the same wedge, but the evidence now points to a narrower execution move."
        if adaptation_instruction:
            comparison = _clean_copy(f"{comparison} {adaptation_instruction}")

        decision = f"Focus this week on {icp.lower()} and make the pitch about removing the risk behind {problem.lower()}."
        execution = [
            f"Replace the hero section with the headline below and use the first proof block to show why {problem.lower()} slows adoption.",
            f"Send the outbound message only to {icp.lower()} accounts that are visibly in {stage_focus} or under {trigger}.",
            f"Open every sales conversation with the buyer language around \"{phrase}\" and ask whether that is blocking a purchase right now.",
            f"Track replies, booked calls, and explicit rejections against the current problem statement for seven days before changing direction.",
        ]
        headline = f"Make your ops workflow easier to trust before buying stalls"
        subheadline = f"Built for {icp.lower()} that need to reduce adoption risk when {trigger}."
        cta = "See the workflow"
        outbound = (
            f"Hi {{first_name}}, we keep seeing {icp.lower()} teams hesitate when {problem.lower()}. "
            f"The fastest path is usually a tighter workflow that removes that friction before {trigger} turns into a stalled deal. "
            "If this is active for you right now, I can walk you through the workflow in 15 minutes."
        )
        talk_track = [
            f"Start with the pattern: teams like yours slow down when {problem.lower()}.",
            f"Name the cost: that drag shows up during {stage_focus} and makes rollout feel riskier than it should.",
            f"Probe with one question: is trust the real blocker here, or is another workflow issue showing up first?",
            f"Close tightly: if this is live now, test one focused workflow for {icp.lower()} this week instead of expanding scope.",
        ]

        confidence_base = 55
        top_segment = (summary.get("segments") or [None])[0]
        top_problem_list = (summary.get("pains") or []) + (summary.get("objections") or []) + (summary.get("conversion_blockers") or [])
        top_problem_cluster = top_problem_list[0] if top_problem_list else None
        if top_segment:
            confidence_base += min(18, top_segment.score // 6)
        if top_problem_cluster:
            confidence_base += min(18, top_problem_cluster.score // 6)

        return RevenueWedgeDecisionBrief.model_validate(
            {
                "recommended_icp": icp,
                "core_problem": problem,
                "decision": decision,
                "this_week_execution": execution,
                "assets": {
                    "landing_page_headline": headline,
                    "landing_page_subheadline": subheadline,
                    "landing_page_cta": cta,
                    "outbound_message": outbound,
                    "sales_talk_track": talk_track,
                },
                "confidence_score": min(95, max(58, confidence_base)),
                "confidence_reasoning": (
                    f"Confidence is based on repeated evidence for {icp} and {problem}, weighted toward lost deals, sales calls, CRM exports, "
                    "and the exact quotes surfaced in the selected evidence bank."
                ),
                "evidence": [item.model_dump() for item in evidence[:2]],
                "contradiction_resolution": contradiction_resolution,
                "comparison_to_last_run": comparison,
                "run_to_run_intelligence": {
                    "previous_run_id": (previous_run or {}).get("run_id") or "",
                    "what_changed": [],
                    "what_improved": [],
                    "what_failed": [],
                    "next_move": decision,
                    "adaptation_reasoning": adaptation_instruction,
                },
                "how_to_use_hatchup": [
                    "Use HatchUp to store this run, then log replies, calls, deals, and objections against the run ID.",
                    "Run it again after the next batch of conversations so the recommendation sharpens based on real outcomes.",
                ],
            }
        )
