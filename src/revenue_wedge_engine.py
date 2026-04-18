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

OUTCOME_WEIGHTS = {
    "won": 3.0,
    "lost": 1.5,
    "neutral": 1.0,
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

VAGUE_ASSET_PHRASES = (
    "improve workflow",
    "optimize decision making",
    "decision output",
    "operational drag",
    "lower-risk rollout logic",
    "simpler path to value",
    "workflow they can trust",
    "improve engagement",
    "optimize",
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

ALLOWED_HYPOTHESES = (
    "ICP too broad",
    "messaging unclear",
    "urgency too low",
    "wrong entry point (hiring vs growth)",
    "onboarding friction",
    "pricing mismatch",
)


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


def _classify_outcome(source_tag: str, quote: str) -> str:
    text = (quote or "").lower()
    if any(term in text for term in ("won", "closed won", "closed-won", "closed won", "renewed", "expanded")):
        return "won"
    if source_tag == "lost_deal" or any(
        term in text for term in ("lost", "churn", "stalled", "no decision", "blocked", "budget", "expensive")
    ):
        return "lost"
    return "neutral"


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
        return _normalize_icp_text("Revenue operations leaders at early-stage B2B SaaS teams")
    if "finance" in text:
        return _normalize_icp_text("Finance leads at small B2B software teams reviewing rollout risk")
    if "agency" in text:
        return _normalize_icp_text("Agency owners with lean delivery teams managing client-facing operations")
    if "founder" in text or "startup" in text:
        return _normalize_icp_text("Early-stage B2B SaaS founders making hands-on buying decisions")
    if "sales" in text:
        return _normalize_icp_text("Sales leaders at lean B2B teams trying to move deals without adding operational drag")
    return _normalize_icp_text(f"Operators in {stage_hint} who are close to the buying decision")


def _humanize_problem(label: str, evidence_quotes: List[str]) -> str:
    combined = f"{label} {' '.join(evidence_quotes)}".lower()
    if "accuracy" in combined or "trust" in combined or "unclear" in combined:
        return "Buyers do not clearly understand what the product does or why they should trust it in real decisions"
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
    text = _normalize_text(re.sub(r"\s+([,.;:!?])", r"\1", value or ""))
    text = re.sub(r"\b(.+?)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    words = text.split()
    deduped_words: List[str] = []
    for word in words:
        if deduped_words and deduped_words[-1].lower() == word.lower():
            continue
        deduped_words.append(word)
    return " ".join(deduped_words)


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


def _team_size_signal(quotes: List[str]) -> str:
    text = " ".join(quotes).lower()
    if re.search(r"\b([2-6])\s*-\s*([2-6])\b", text) or "small team" in text or "lean team" in text:
        return "small teams"
    return ""


def _metric_change_label(current: str, previous: str, field_name: str) -> str:
    if not current and not previous:
        return ""
    if current == previous:
        return f"{field_name} stayed the same"
    return f"{field_name} shifted from {previous or 'none'} to {current or 'none'}"


def _normalize_problem_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _semantic_cluster_label(category: str, label: str, quote: str = "") -> str:
    combined = _normalize_problem_text(f"{label} {quote}")
    if category == "objection":
        if any(term in combined for term in ("trust", "proof", "not sure", "unclear", "works", "value", "confidence", "accuracy")):
            return "trust / clarity issue"
        if any(term in combined for term in ("price", "pricing", "budget", "expensive", "justify")):
            return "pricing mismatch"
        if any(term in combined for term in ("integration", "security", "risk", "legal")):
            return "integration / risk concern"
    if category == "pain":
        if any(term in combined for term in ("manual", "spreadsheet", "cleanup", "messy", "workflow")):
            return "manual workflow friction"
        if any(term in combined for term in ("unclear", "trust", "proof", "value", "output")):
            return "trust / clarity issue"
    if category == "blocker":
        if any(term in combined for term in ("approval", "sign off", "signoff", "procurement")):
            return "approval delay"
        if any(term in combined for term in ("onboard", "setup", "implementation", "adopt")):
            return "onboarding friction"
    if category == "trigger":
        if any(term in combined for term in ("launch", "this week", "quota", "pipeline", "urgent", "renewal")):
            return "near-term urgency"
    if category == "segment":
        if any(term in combined for term in ("founder", "startup")):
            return "early-stage founders"
        if any(term in combined for term in ("revops", "revenue operations", "ops")):
            return "revops teams"
    return _normalize_text(label)


def _parse_structured_sections(raw_text: str) -> List[Dict[str, Any]]:
    text = raw_text or ""
    pattern = re.compile(r"===\s*([A-Z /_-]+?)\s*===")
    matches = list(pattern.finditer(text))
    sections: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        marker = _normalize_text(match.group(1)).upper()
        body = text[start:end].strip()
        fields = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = _normalize_text(key).lower()
            value = _normalize_text(value)
            if key:
                fields[key] = value
        mapped_source = ""
        if "SALES CALL" in marker:
            mapped_source = "sales_call"
        elif "CRM ENTRY" in marker or marker == "CRM":
            mapped_source = "crm_export"
        elif "SUPPORT" in marker:
            mapped_source = "support"
        sections.append(
            {
                "marker": marker,
                "mapped_source": mapped_source,
                "body": body,
                "fields": fields,
                "field_count": len([value for value in fields.values() if value]),
                "empty": not bool(_normalize_text(body)),
            }
        )
    return sections


def _has_repeated_tokens(value: str, window: int = 4) -> bool:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    if len(tokens) < 2:
        return False
    for index in range(1, len(tokens)):
        if tokens[index] == tokens[index - 1]:
            return True
    for size in range(2, min(window, len(tokens) // 2) + 1):
        for start in range(0, len(tokens) - (size * 2) + 1):
            if tokens[start:start + size] == tokens[start + size:start + (size * 2)]:
                return True
    return False


def _dedupe_repeated_phrases(value: str) -> str:
    text = _clean_copy(value)
    tokens = text.split()
    if len(tokens) < 2:
        return text
    rebuilt: List[str] = []
    index = 0
    while index < len(tokens):
        skipped = False
        max_size = min(6, (len(tokens) - index) // 2)
        for size in range(max_size, 1, -1):
            first = [token.lower() for token in tokens[index:index + size]]
            second = [token.lower() for token in tokens[index + size:index + (size * 2)]]
            if first == second:
                rebuilt.extend(tokens[index:index + size])
                index += size * 2
                skipped = True
                break
        if not skipped:
            if not rebuilt or rebuilt[-1].lower() != tokens[index].lower():
                rebuilt.append(tokens[index])
            index += 1
    return _clean_copy(" ".join(rebuilt))


def _normalize_icp_text(value: str, max_words: int = 18) -> str:
    text = _dedupe_repeated_phrases(value)
    text = re.sub(r"\s*\(\s*", " (", text)
    text = re.sub(r"\s*\)\s*", ") ", text)
    text = _clean_copy(text)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(",.;:") 
    text = re.sub(r"\bwith\s+with\b", "with", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthat\s+that\b", "that", text, flags=re.IGNORECASE)
    text = _clean_copy(text)
    if _has_repeated_tokens(text):
        compressed: List[str] = []
        seen_bigrams = set()
        raw_tokens = text.split()
        for idx, token in enumerate(raw_tokens):
            if compressed and compressed[-1].lower() == token.lower():
                continue
            bigram = " ".join(raw_tokens[idx:idx + 2]).lower()
            if idx < len(raw_tokens) - 1 and bigram in seen_bigrams:
                continue
            if idx < len(raw_tokens) - 1:
                seen_bigrams.add(bigram)
            compressed.append(token)
        text = _clean_copy(" ".join(compressed[:max_words]))
    return text


def _limit_words(value: str, max_words: int) -> str:
    words = _clean_copy(value).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",.;:")


def _founder_line(value: str, max_words: int = 12) -> str:
    text = _dedupe_repeated_phrases(value)
    text = re.sub(r"\b(improve|optimize|enhance|leverage|streamline)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -,.")
    return _limit_words(text, max_words)


def _asset_copy_is_usable(value: str) -> bool:
    text = _clean_copy(value).lower()
    if not text:
        return False
    if any(phrase in text for phrase in VAGUE_ASSET_PHRASES):
        return False
    if len(text.split()) > 18:
        return False
    return not _has_repeated_tokens(text)


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
        comparison = self._build_run_comparison(previous_run, None, run_history or [], learned_patterns or {})
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
        if result := brief.model_dump():
            if quality.get("moderate_signal_pass") and 50 <= int(quality.get("score") or 0) <= 70:
                result["confidence_score"] = min(int(result.get("confidence_score") or 65), 68)
                result["confidence_reasoning"] = _clean_copy(
                    f"{result.get('confidence_reasoning') or ''} This is enough signal to act, but confidence is lower because the pattern is moderate rather than overwhelming."
                )
                brief = RevenueWedgeDecisionBrief.model_validate(result)
        comparison = self._build_run_comparison(previous_run, brief.model_dump(), run_history or [], learned_patterns or {})
        brief = RevenueWedgeDecisionBrief.model_validate(
            {
                **brief.model_dump(),
                "comparison_to_last_run": brief.comparison_to_last_run or comparison.get("adaptation_reasoning"),
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
- Prioritize signals tied to buyer outcomes, especially patterns in won deals and then lost deals.
- Treat objections like trust, hesitation, and risk as symptoms unless the quote clearly states the deeper operational problem.
- When you see evidence that buyers understood value, output, ICP fit, or decision speed in a won deal, preserve that signal.
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
            label = _normalize_text(
                _semantic_cluster_label(
                    data.get("category") or "pain",
                    data.get("label") or "",
                    data.get("supporting_quote") or "",
                )
            )
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
                    "won_signal_score": 0.0,
                    "lost_signal_score": 0.0,
                    "symptom_penalty": 0.0,
                    "sources": set(),
                    "evidence_quotes": [],
                    "stages": set(),
                }
            source_tag = data.get("source_tag") or "customer_interview"
            weight = SOURCE_WEIGHTS.get(source_tag, 2)
            stage = data.get("stage") or "unknown"
            stage_weight = STAGE_WEIGHTS.get(stage, 1)
            quote = data.get("supporting_quote") or ""
            outcome_score = _score_outcome(source_tag, quote)
            outcome = _classify_outcome(source_tag, quote)
            outcome_multiplier = OUTCOME_WEIGHTS.get(outcome, 1.0)
            weighted_signal = weight * outcome_multiplier
            groups[key]["frequency"] += 1
            groups[key]["weighted_frequency"] += weighted_signal
            groups[key]["outcome_score"] += outcome_score
            if data.get("impact_direction") == "negative":
                groups[key]["negative_weight"] += weighted_signal + stage_weight
            elif data.get("impact_direction") == "positive":
                groups[key]["positive_weight"] += weighted_signal + stage_weight
            if outcome == "won":
                groups[key]["won_signal_score"] += weighted_signal + max(0, stage_weight - 1)
            elif outcome == "lost":
                groups[key]["lost_signal_score"] += weighted_signal + stage_weight
            if data.get("category") == "objection":
                groups[key]["symptom_penalty"] += 10
            groups[key]["sources"].add(source_tag)
            groups[key]["stages"].add(stage)
            quote = _clip(quote, 140)
            if quote and quote not in groups[key]["evidence_quotes"]:
                groups[key]["evidence_quotes"].append(quote)

        cluster_map: Dict[str, List[RevenueCluster]] = defaultdict(list)
        for payload in groups.values():
            revenue_impact = min(
                100,
                payload["won_signal_score"] * 10
                + payload["lost_signal_score"] * 5
                + payload["weighted_frequency"] * 4
                + payload["outcome_score"],
            )
            conversion_signal = min(
                100,
                max(
                    0,
                    20 + payload["won_signal_score"] * 8 + payload["positive_weight"] * 3 + payload["outcome_score"] - payload["negative_weight"],
                ),
            )
            score = min(
                100,
                payload["won_signal_score"] * 14
                + payload["lost_signal_score"] * 6
                + payload["weighted_frequency"] * 3
                + payload["frequency"] * 5
                + payload["outcome_score"]
                + max(payload["negative_weight"], payload["positive_weight"]),
            )
            if payload["category"] == "objection":
                score = max(0, score - payload["symptom_penalty"])
            cluster_map[payload["category"]].append(
                RevenueCluster(
                    category=payload["category"],
                    label=payload["label"],
                    score=int(round(score)),
                    frequency=payload["frequency"],
                    weighted_frequency=int(round(payload["weighted_frequency"])),
                    revenue_impact=int(round(revenue_impact)),
                    conversion_signal=int(round(conversion_signal)),
                    outcome_score=payload["outcome_score"],
                    won_signal_score=int(round(payload["won_signal_score"])),
                    lost_signal_score=int(round(payload["lost_signal_score"])),
                    sources=sorted(payload["sources"]),
                    evidence_quotes=payload["evidence_quotes"][:4],
                    stages=sorted(payload["stages"]),
                )
            )

        for category in cluster_map:
            cluster_map[category] = sorted(
                cluster_map[category],
                key=lambda item: (item.won_signal_score, item.score, item.outcome_score, item.frequency, item.revenue_impact),
                reverse=True,
            )[:6]
        return dict(cluster_map)

    def _rank_problem_clusters(self, summary: Dict[str, List[RevenueCluster]]) -> List[RevenueCluster]:
        weighted: List[tuple[int, RevenueCluster]] = []
        for cluster in summary.get("pains") or []:
            weighted.append((3, cluster))
        for cluster in summary.get("conversion_blockers") or []:
            weighted.append((2, cluster))
        for cluster in summary.get("objections") or []:
            weighted.append((1, cluster))
        weighted.sort(
            key=lambda item: (
                item[0],
                item[1].won_signal_score,
                item[1].score,
                item[1].lost_signal_score,
                item[1].frequency,
            ),
            reverse=True,
        )
        return [cluster for _priority, cluster in weighted]

    def _derive_core_problem(
        self,
        chosen_segment: Optional[RevenueCluster],
        problems: List[RevenueCluster],
        learned_patterns: Dict[str, Any],
    ) -> str:
        combined = " ".join(
            [cluster.label for cluster in problems[:4]] + [quote for cluster in problems[:4] for quote in cluster.evidence_quotes[:2]]
        ).lower()
        segment_text = ((chosen_segment.label if chosen_segment else "") + " " + " ".join(chosen_segment.evidence_quotes if chosen_segment else [])).lower()
        if any(term in combined for term in ("trust", "accuracy", "risk", "unclear", "hesitate", "confidence", "output", "value")):
            if any(term in segment_text for term in ("founder", "startup")):
                return "Founders don't clearly understand what the product does and how it helps them make decisions"
            return "Buyers do not clearly understand what the product does, what output they will get, and why it helps them make a real decision"
        if any(term in combined for term in ("manual", "cleanup", "spreadsheet", "workflow", "messy")):
            team_signal = _team_size_signal([quote for cluster in problems[:4] for quote in cluster.evidence_quotes[:2]])
            if team_signal:
                return "Small teams need a decision-ready workflow, but the product still requires too much interpretation before they can act"
            return "Buyers still have to do too much manual interpretation before the workflow feels safe to adopt"
        strongest_problem = (learned_patterns.get("strongest_problem") or "").strip()
        if strongest_problem and not _sounds_like_raw_label(strongest_problem):
            return strongest_problem
        return _humanize_problem(problems[0].label, problems[0].evidence_quotes) if problems else "The buyer still cannot see the value clearly enough to act"

    def _build_winning_pattern(
        self,
        summary: Dict[str, List[RevenueCluster]],
        chosen_segment: Optional[RevenueCluster],
    ) -> Dict[str, str]:
        winning_quotes = []
        for category in ("segments", "pains", "buying_triggers", "conversion_blockers"):
            for cluster in summary.get(category) or []:
                if cluster.won_signal_score > 0:
                    winning_quotes.extend(cluster.evidence_quotes[:2])
        winning_text = " ".join(winning_quotes).lower()
        team_shape = "small teams" if (_team_size_signal(winning_quotes) or any(term in winning_text for term in ("lean team", "small team"))) else ""
        decision_speed = "fast decisions" if any(term in winning_text for term in ("fast", "quick", "same day", "this week", "immediately")) else ""
        value_clarity = "clear value" if any(term in winning_text for term in ("clear", "understood", "value", "decision", "output")) else ""
        parts = [part for part in (team_shape, decision_speed, value_clarity) if part]
        return {
            "summary": ", ".join(parts[:3]),
            "primary_signal": chosen_segment.label if chosen_segment else "",
        }

    def _core_problem_explains_outcomes(
        self,
        core_problem: str,
        summary: Dict[str, List[RevenueCluster]],
    ) -> bool:
        won_present = any(
            cluster.won_signal_score > 0
            for category in ("segments", "pains", "buying_triggers", "conversion_blockers")
            for cluster in (summary.get(category) or [])
        )
        lost_present = any(
            cluster.lost_signal_score > 0
            for category in ("pains", "objections", "conversion_blockers")
            for cluster in (summary.get(category) or [])
        )
        if not won_present or not lost_present:
            return True
        lowered = core_problem.lower()
        if any(phrase in lowered for phrase in ("trust issue", "hesitation", "objection", "risk") if "understand" not in lowered):
            return False
        return any(term in lowered for term in ("understand", "clear", "value", "output", "decision", "workflow"))

    def _has_measurable_improvement(self, outcome: Dict[str, Any]) -> bool:
        replies = int(outcome.get("replies") or 0)
        calls_booked = int(outcome.get("calls_booked") or 0)
        deals_closed = int(outcome.get("deals_closed") or 0)
        return replies > 0 or calls_booked > 0 or deals_closed > 0

    def _build_hypothesis_from_cluster(self, cluster: RevenueCluster) -> str:
        combined = f"{cluster.label} {' '.join(cluster.evidence_quotes)}".lower()
        if any(term in combined for term in ("onboard", "setup", "implementation", "rollout", "adopt")):
            return "onboarding friction"
        if any(term in combined for term in ("urgent", "asap", "this week", "now", "pipeline", "quota", "launch")):
            return "urgency too low"
        if any(term in combined for term in ("budget", "expensive", "price", "pricing")):
            return "pricing mismatch"
        if any(term in combined for term in ("hiring", "hire", "growth", "pipeline generation", "distribution", "acquisition")):
            return "wrong entry point (hiring vs growth)"
        if any(term in combined for term in ("founder", "revops", "finance", "sales", "agency", "team", "segment")):
            return "ICP too broad"
        if any(term in combined for term in ("manual", "workflow", "cleanup", "spreadsheet", "messy")):
            return "onboarding friction"
        if any(term in combined for term in ("trust", "accuracy", "risk", "unclear", "value", "output")):
            return "messaging unclear"
        return "messaging unclear"

    def _canonicalize_hypothesis(self, hypothesis: str) -> str:
        text = _normalize_problem_text(hypothesis)
        if any(term in text for term in ("icp", "too broad", "wrong buyer", "buyer subset", "segment")):
            return "ICP too broad"
        if any(term in text for term in ("messaging", "understand", "unclear", "value", "output", "trust", "clarity")):
            return "messaging unclear"
        if any(term in text for term in ("urgency", "urgent", "deadline", "pipeline", "quota", "launch", "this week")):
            return "urgency too low"
        if any(term in text for term in ("entry point", "hiring", "growth")):
            return "wrong entry point (hiring vs growth)"
        if any(term in text for term in ("onboarding", "first use", "first-use", "setup", "implementation", "rollout", "adopt")):
            return "onboarding friction"
        if any(term in text for term in ("pricing", "price", "budget", "justify")):
            return "pricing mismatch"
        return "messaging unclear"

    def _generate_alternative_hypotheses(
        self,
        summary: Dict[str, List[RevenueCluster]],
        current_problem: str,
        previous_hypothesis: str = "",
    ) -> List[str]:
        candidates: List[str] = []
        ordered_clusters = self._rank_problem_clusters(summary)
        ordered_clusters += summary.get("buying_triggers") or []
        ordered_clusters += summary.get("segments") or []
        seen = {
            _normalize_problem_text(self._canonicalize_hypothesis(current_problem)),
            _normalize_problem_text(self._canonicalize_hypothesis(previous_hypothesis)),
        }
        for cluster in ordered_clusters:
            hypothesis = self._canonicalize_hypothesis(self._build_hypothesis_from_cluster(cluster))
            normalized = _normalize_problem_text(hypothesis)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(hypothesis)
            if len(candidates) >= 3:
                break
        for hypothesis in ALLOWED_HYPOTHESES:
            normalized = _normalize_problem_text(hypothesis)
            if normalized not in seen:
                candidates.append(hypothesis)
                seen.add(normalized)
            if len(candidates) >= 3:
                break
        return candidates[:3]

    def _analyze_hypothesis_history(
        self,
        run_history: List[Dict[str, Any]],
        previous_run: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        history = list(run_history or [])
        if previous_run and previous_run.get("run_id") and not any(run.get("run_id") == previous_run.get("run_id") for run in history):
            history.append(previous_run)
        history = [run for run in history if run.get("decision_brief")]
        if not history:
            return {
                "consecutive_no_improvement": 0,
                "same_problem_streak": 0,
                "exploration_required": False,
                "previous_hypothesis": "",
            }

        consecutive_no_improvement = 0
        for run in reversed(history):
            outcome = run.get("outcome_log") or run.get("result_log") or {}
            if self._has_measurable_improvement(outcome):
                break
            consecutive_no_improvement += 1

        previous_hypothesis = ((history[-1].get("decision_brief") or {}).get("core_problem") or "").strip()
        same_problem_streak = 0
        if previous_hypothesis:
            normalized_previous = _normalize_problem_text(previous_hypothesis)
            for run in reversed(history):
                problem = (((run.get("decision_brief") or {}).get("core_problem")) or "").strip()
                if _normalize_problem_text(problem) != normalized_previous:
                    break
                outcome = run.get("outcome_log") or run.get("result_log") or {}
                if self._has_measurable_improvement(outcome):
                    break
                same_problem_streak += 1

        return {
            "consecutive_no_improvement": consecutive_no_improvement,
            "same_problem_streak": same_problem_streak,
            "exploration_required": consecutive_no_improvement >= 2 or same_problem_streak >= 2,
            "previous_hypothesis": previous_hypothesis,
        }

    def _hypothesis_type(self, hypothesis: str) -> str:
        canonical = self._canonicalize_hypothesis(hypothesis)
        text = canonical.lower()
        if "icp too broad" == text:
            return "icp"
        if "onboarding friction" == text:
            return "onboarding"
        if "urgency too low" == text:
            return "urgency"
        if "pricing mismatch" == text:
            return "pricing"
        if "wrong entry point (hiring vs growth)" == text:
            return "entry_point"
        return "messaging"

    def _narrow_icp_for_exploration(
        self,
        current_icp: str,
        winning_pattern_summary: str,
        previous_icp: str,
    ) -> str:
        base = (current_icp or previous_icp or "Early-stage buyers").strip()
        pattern = (winning_pattern_summary or "").lower()
        if "small teams" in pattern and "small-team" not in base.lower():
            narrowed = f"{base} with 2-6 person teams"
        elif "fast decisions" in pattern and "fast decision" not in base.lower():
            narrowed = f"{base} making fast buying decisions"
        elif "clear value" in pattern and "clear value" not in base.lower():
            narrowed = f"{base} already searching for clear decision value"
        else:
            narrowed = f"{base} with urgent, hands-on buying ownership"
        if previous_icp and narrowed.strip().lower() == previous_icp.strip().lower():
            narrowed = f"{base} excluding slow multi-stakeholder accounts"
        return _normalize_icp_text(narrowed)

    def _exploration_variant(
        self,
        decision_context: Dict[str, Any],
        previous_run: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        hypothesis = (decision_context.get("core_problem") or "").strip()
        hypothesis_type = self._hypothesis_type(hypothesis)
        current_icp = (decision_context.get("recommended_icp") or "").strip()
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        previous_icp = (previous_brief.get("recommended_icp") or "").strip()
        previous_problem = (previous_brief.get("core_problem") or "").strip()
        phrase = decision_context.get("language_anchor") or "the current workflow"
        trigger = decision_context.get("buying_trigger") or "the next buying decision"
        winning_pattern_summary = decision_context.get("winning_pattern_summary") or ""

        variant = {
            "recommended_icp": current_icp,
            "headline": "See what to fix this week",
            "subheadline": _founder_line(f"For {current_icp.lower()} that need a clear next move before {trigger}.", 14),
            "outbound": (
                _founder_line(
                    f"Hi {{first_name}}, teams like yours stall because of {hypothesis.lower()}. If this is live now, I can show the fix in 15 minutes.",
                    18,
                )
            ),
            "talk_track": [
                _founder_line(f"We think the real problem is {hypothesis.lower()}.", 12),
                _founder_line(f"What is blocking movement right now around {phrase}?", 12),
                _founder_line("Test one change this week and track what moves.", 11),
            ],
            "execution": [
                f"Update the homepage hero to test the hypothesis that {hypothesis.lower()}.",
                "Use the outbound message below only on active buying conversations that match this test.",
                f"Run calls with the talk track below and log whether the new hypothesis explains the stall around {phrase}.",
                "Measure replies, calls, and explicit objections for seven days before changing another variable.",
            ],
            "decision": f"Previous hypothesis: {previous_problem or 'none recorded'}. No improvement observed. New hypothesis: {hypothesis}. Testing this this week with the same ICP.",
            "measurement": "Measure replies, booked calls, and whether the new hypothesis is named before the old one in active conversations.",
            "hypothesis_type": hypothesis_type,
        }

        if hypothesis_type == "icp":
            narrowed_icp = self._narrow_icp_for_exploration(current_icp, winning_pattern_summary, previous_icp)
            variant.update(
                {
                    "recommended_icp": narrowed_icp,
                    "headline": _founder_line(f"Built for {narrowed_icp.lower()}", 10),
                    "subheadline": _founder_line(f"Not for every team. For buyers who need a fast answer before {trigger}.", 14),
                    "outbound": (
                        _founder_line(
                            f"Hi {{first_name}}, we are only talking to {narrowed_icp.lower()} this week. If you own the decision, I can show the workflow.",
                            18,
                        )
                    ),
                    "talk_track": [
                        _founder_line(f"This is for {narrowed_icp.lower()}.", 10),
                        _founder_line("Do you own this decision yourself?", 8),
                        _founder_line(f"Is {phrase} painful enough to fix now?", 10),
                    ],
                    "execution": [
                        f"Narrow the target list to {narrowed_icp.lower()} and exclude broader segments from this week's test.",
                        f"Replace the homepage hero so it speaks only to {narrowed_icp.lower()}.",
                        "Use outbound only for that narrowed subset and log disqualified accounts separately.",
                        "Measure reply rate, call rate, and disqualification rate versus the broader ICP.",
                    ],
                    "decision": f"Previous hypothesis: {previous_problem or 'none recorded'}. No improvement observed. New hypothesis: {hypothesis}. Testing this this week by narrowing the ICP to {narrowed_icp}.",
                    "measurement": "Measure narrowed-subset replies, booked calls, and disqualification rate against the previous broader ICP.",
                }
            )
        elif hypothesis_type == "onboarding":
            variant.update(
                {
                    "headline": "See your first win fast",
                    "subheadline": _founder_line(f"For {current_icp.lower()} that need to see value in the first session.", 14),
                    "outbound": (
                        _founder_line(
                            f"Hi {{first_name}}, deals slow down when buyers cannot see the first win after setup. I can show that path in 15 minutes.",
                            18,
                        )
                    ),
                    "talk_track": [
                        _founder_line("Start with the first win, not the full product.", 11),
                        _founder_line("What should you see in the first session?", 10),
                        _founder_line("Show the shortest path to that result.", 9),
                    ],
                    "execution": [
                        "Rewrite the hero and proof section around the first useful outcome after setup.",
                        "Send onboarding-focused outbound that highlights first-use clarity instead of broad product value.",
                        "Run calls that walk through the first-use path and log where buyer confidence drops.",
                        "Measure whether buyers can repeat the first-win outcome back in their own words.",
                    ],
                    "measurement": "Measure whether buyers can describe the first win, plus replies and booked calls from onboarding-focused messaging.",
                }
            )
        elif hypothesis_type == "urgency":
            variant.update(
                {
                    "headline": "Fix this before the week slips",
                    "subheadline": _founder_line(f"For {current_icp.lower()} that need a reason to act before {trigger}.", 14),
                    "outbound": (
                        _founder_line(
                            f"Hi {{first_name}}, this may not feel urgent enough yet. If you need to act before {trigger}, I can show the path.",
                            18,
                        )
                    ),
                    "talk_track": [
                        _founder_line("Lead with the decision that has to happen now.", 11),
                        _founder_line("What breaks if this waits another week?", 9),
                        _founder_line("Tie the pitch to this week's deadline.", 9),
                    ],
                    "execution": [
                        "Rewrite the hero around a near-term decision and the cost of waiting.",
                        "Send urgency-led outbound that references this week's decision window.",
                        "Run calls that ask buyers to name the deadline or event that makes action necessary now.",
                        "Measure reply quality, booked calls, and whether urgency is acknowledged explicitly.",
                    ],
                    "measurement": "Measure whether buyers name a deadline, event, or near-term decision, plus replies and booked calls.",
                }
            )
        elif hypothesis_type == "pricing":
            variant.update(
                {
                    "headline": "Make the price easy to defend",
                    "subheadline": _founder_line(f"For {current_icp.lower()} that need proof before paying.", 12),
                    "outbound": (
                        _founder_line(
                            f"Hi {{first_name}}, if price is the blocker, I can show the proof buyers use to justify it.",
                            17,
                        )
                    ),
                    "talk_track": [
                        _founder_line("Start with proof, not features.", 6),
                        _founder_line("What proof would make this price feel safe?", 9),
                        _founder_line("Show the smallest step that pays back fast.", 9),
                    ],
                    "execution": [
                        "Rewrite the hero and proof section around lower-risk rollout and clearer value exchange.",
                        "Send pricing-angle outbound focused on justification, not product breadth.",
                        "Run calls that ask what proof would make the current price easier to defend.",
                        "Measure whether buyers move from price objections to proof-oriented questions.",
                    ],
                    "measurement": "Measure proof-oriented responses, reduced price-first objections, plus replies and calls.",
                }
            )
        elif hypothesis_type == "entry_point":
            variant.update(
                {
                    "headline": "Start with the problem they feel now",
                    "subheadline": _founder_line(f"For {current_icp.lower()} focused on growth, not hiring, right now.", 13),
                    "outbound": (
                        _founder_line(
                            f"Hi {{first_name}}, if growth matters more than hiring right now, I can show the workflow from that angle.",
                            18,
                        )
                    ),
                    "talk_track": [
                        _founder_line("Ask if growth or hiring is the real priority.", 10),
                        _founder_line("Do not lead with the wrong use case.", 8),
                        _founder_line("Pitch the entry point that matters this week.", 9),
                    ],
                    "execution": [
                        "Rewrite the hero so it leads with the growth entry point instead of the hiring angle.",
                        "Send outbound that tests growth-first language before reusing hiring-oriented copy.",
                        "Run calls that explicitly ask whether hiring or growth is the urgent entry point.",
                        "Measure which entry point creates more replies and better call conversion this week.",
                    ],
                    "measurement": "Measure replies and call conversion for growth-first versus hiring-first entry points.",
                }
            )
        return variant

    def _brief_has_observable_change(
        self,
        brief: RevenueWedgeDecisionBrief,
        previous_run: Optional[Dict[str, Any]],
    ) -> bool:
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        if not previous_brief:
            return True
        changed = 0
        if _normalize_icp_text(brief.recommended_icp).strip().lower() != _normalize_icp_text(previous_brief.get("recommended_icp") or "").strip().lower():
            changed += 1
        if (brief.decision or "").strip().lower() != (previous_brief.get("decision") or "").strip().lower():
            changed += 1
        if " ".join(brief.this_week_execution or []).strip().lower() != " ".join(previous_brief.get("this_week_execution") or []).strip().lower():
            changed += 1
        previous_assets = previous_brief.get("assets") or {}
        current_asset_text = " ".join(
            [
                brief.assets.landing_page_headline,
                brief.assets.landing_page_subheadline,
                brief.assets.outbound_message,
                " ".join(brief.assets.sales_talk_track or []),
            ]
        ).strip().lower()
        previous_asset_text = " ".join(
            [
                previous_assets.get("landing_page_headline") or "",
                previous_assets.get("landing_page_subheadline") or "",
                previous_assets.get("outbound_message") or "",
                " ".join(previous_assets.get("sales_talk_track") or []),
            ]
        ).strip().lower()
        if current_asset_text != previous_asset_text:
            changed += 1
        icp_changed = _normalize_icp_text(brief.recommended_icp).strip().lower() != _normalize_icp_text(previous_brief.get("recommended_icp") or "").strip().lower()
        if icp_changed and current_asset_text == previous_asset_text:
            return False
        return changed >= 1

    def _measure_change_is_testable(self, brief: RevenueWedgeDecisionBrief) -> bool:
        combined = " ".join([brief.decision] + (brief.this_week_execution or []) + [brief.comparison_to_last_run]).lower()
        return any(term in combined for term in ("measure", "log", "track", "reply", "call", "objection", "disqual", "deadline"))

    def _assets_sound_human(self, brief: RevenueWedgeDecisionBrief) -> bool:
        asset_lines = [
            brief.assets.landing_page_headline,
            brief.assets.landing_page_subheadline,
            brief.assets.landing_page_cta,
            brief.assets.outbound_message,
            *(brief.assets.sales_talk_track or []),
        ]
        if len(brief.assets.sales_talk_track or []) > 3:
            return False
        return all(_asset_copy_is_usable(line) for line in asset_lines)

    def _build_signal_collection_guidance(self) -> Dict[str, Any]:
        return {
            "required_data_types": [
                "Sales call notes with buyer pain, objections, and next-step outcome",
                "CRM exports with won/lost reason, buyer type, and deal stage",
                "Support threads or onboarding complaints that show repeated friction",
            ],
            "good_input_examples": [
                "Sales call: Founder said, 'I still can't tell what to fix first this week,' and the deal stalled after the demo.",
                "CRM note: Lost deal to no decision. Buyer liked the idea but could not justify the price before sign-off.",
                "Support thread: Three users from small teams asked the same setup question in their first week.",
            ],
            "samples_needed": [
                "At least 3 sales calls or founder interviews",
                "At least 3 CRM won/lost notes",
                "At least 2 support or onboarding threads",
            ],
            "minimum_requirements": [
                "3 sales calls",
                "2 CRM entries with won or lost outcome",
                "1 repeated objection across sources",
            ],
            "copy_paste_templates": [
                "=== SALES CALL ===\nCustomer:\nBuyer type:\nMain problem:\nObjection:\nOutcome:\nNext step:",
                "=== CRM ENTRY ===\nCompany:\nStage:\nWon or lost:\nReason:\nBuyer type:\nDecision timing:",
                "=== SUPPORT OR ONBOARDING ===\nCustomer:\nWhat they got stuck on:\nExact words used:\nHow often this happened:\nOutcome:",
            ],
            "what_happens_next": [
                "Exact ICP",
                "What is blocking deals",
                "What to fix this week",
            ],
        }

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
        run_history: List[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        previous_outcome = (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {}
        replies = int(previous_outcome.get("replies") or 0)
        calls_booked = int(previous_outcome.get("calls_booked") or 0)
        deals_closed = int(previous_outcome.get("deals_closed") or 0)
        hypothesis_history = self._analyze_hypothesis_history(run_history, previous_run)

        if hypothesis_history["exploration_required"] and previous_brief:
            return {
                "mode": "explore",
                "instruction": "No improvement has been observed across recent runs. Keep the ICP stable, choose one new root-cause hypothesis from the current evidence, and test only that change this week.",
                "exploration_required": True,
                "previous_hypothesis": hypothesis_history["previous_hypothesis"],
                "consecutive_no_improvement": hypothesis_history["consecutive_no_improvement"],
                "same_problem_streak": hypothesis_history["same_problem_streak"],
            }

        if replies > 0 and calls_booked == 0 and deals_closed == 0:
            return {
                "mode": "go_deeper",
                "instruction": "Replies improved, but conversions did not. Keep the ICP tight and move the recommendation deeper into pricing, proof, onboarding, or rollout risk.",
                "exploration_required": False,
                "previous_hypothesis": previous_brief.get("core_problem") or "",
                "consecutive_no_improvement": 0,
                "same_problem_streak": 0,
            }
        if replies == 0 and calls_booked == 0 and deals_closed == 0 and previous_brief:
            return {
                "mode": "pivot",
                "instruction": "The last run did not create measurable movement. Pivot either the core problem or the ICP instead of repeating the same wedge.",
                "exploration_required": False,
                "previous_hypothesis": previous_brief.get("core_problem") or "",
                "consecutive_no_improvement": 1,
                "same_problem_streak": 1,
            }
        if calls_booked > 0 or deals_closed > 0:
            return {
                "mode": "double_down",
                "instruction": "The last run produced downstream movement. Double down on the same ICP and sharpen the message that already worked.",
                "exploration_required": False,
                "previous_hypothesis": previous_brief.get("core_problem") or "",
                "consecutive_no_improvement": 0,
                "same_problem_streak": 0,
            }
        if learned_patterns.get("best_icp"):
            winning_pattern_summary = (learned_patterns.get("winning_pattern_summary") or "").strip()
            return {
                "mode": "memory_bias",
                "instruction": _clean_copy(
                    f"Past results suggest {learned_patterns.get('best_icp')} has been the strongest ICP so far. "
                    f"{winning_pattern_summary or 'Keep weighting patterns from winning deals above repeated objections.'} "
                    "Only move away if the new evidence is clearly stronger."
                ),
                "exploration_required": False,
                "previous_hypothesis": previous_brief.get("core_problem") or "",
                "consecutive_no_improvement": 0,
                "same_problem_streak": 0,
            }
        return {
            "mode": "neutral",
            "instruction": "No strong prior outcome signal exists yet. Use the freshest evidence, but note what needs to be learned next.",
            "exploration_required": False,
            "previous_hypothesis": previous_brief.get("core_problem") or "",
            "consecutive_no_improvement": 0,
            "same_problem_streak": 0,
        }

    def _build_run_comparison(
        self,
        previous_run: Optional[Dict[str, Any]],
        current_brief: Optional[Dict[str, Any]],
        run_history: List[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        previous_brief = (previous_run or {}).get("decision_brief") or {}
        previous_outcome = (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {}
        adaptation = self._build_adaptation_signal(previous_run, run_history, learned_patterns)
        if not previous_brief:
            return {
                "previous_run_id": "",
                "what_changed": ["This is the first tracked Revenue Wedge run, so future runs will compare against it."],
                "what_improved": [],
                "what_failed": [],
                "next_move": (current_brief or {}).get("decision") or "Log outcomes from this run so the engine can adapt next time.",
                "adaptation_reasoning": adaptation["instruction"],
                "previous_hypothesis": "",
                "new_hypothesis": (current_brief or {}).get("core_problem") or "",
                "alternative_hypotheses": [],
                "exploration_mode": False,
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

        previous_hypothesis = previous_brief.get("core_problem", "")
        new_hypothesis = (current_brief or {}).get("core_problem") or previous_hypothesis
        alternative_hypotheses = ((current_brief or {}).get("run_to_run_intelligence") or {}).get("alternative_hypotheses") or []
        exploration_mode = bool(((current_brief or {}).get("run_to_run_intelligence") or {}).get("exploration_mode"))

        return {
            "previous_run_id": (previous_run or {}).get("run_id") or "",
            "what_changed": what_changed,
            "what_improved": what_improved,
            "what_failed": what_failed,
            "next_move": (current_brief or {}).get("decision") or adaptation["instruction"],
            "adaptation_reasoning": adaptation["instruction"],
            "previous_hypothesis": previous_hypothesis,
            "new_hypothesis": new_hypothesis,
            "alternative_hypotheses": alternative_hypotheses[:3],
            "exploration_mode": exploration_mode,
        }

    def _build_decision_context(
        self,
        summary: Dict[str, List[RevenueCluster]],
        previous_run: Optional[Dict[str, Any]],
        run_history: List[Dict[str, Any]],
        learned_patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        segments = summary.get("segments") or []
        problems = self._rank_problem_clusters(summary)
        triggers = summary.get("buying_triggers") or []
        language = summary.get("customer_language") or []
        stages = summary.get("stage_signals") or []

        chosen_segment = sorted(
            segments,
            key=lambda item: (item.won_signal_score, item.score, item.outcome_score, item.frequency),
            reverse=True,
        )[0] if segments else None
        chosen_problem = problems[0] if problems else None
        chosen_trigger = sorted(
            triggers,
            key=lambda item: (item.won_signal_score, item.score, item.outcome_score, item.frequency),
            reverse=True,
        )[0] if triggers else None
        chosen_language = language[0] if language else None
        chosen_stage = stages[0] if stages else None
        stage_hint = chosen_stage.label if chosen_stage else "evaluation"
        winning_pattern = self._build_winning_pattern(summary, chosen_segment)

        contradiction_note = "No major contradiction detected in the current inputs."
        if len(segments) > 1 and segments[0].score - segments[1].score <= 8:
            contradiction_note = (
                f"Two ICPs surfaced, but {segments[0].label} outranked {segments[1].label} once won-deal evidence and revenue impact were combined, "
                "so the engine is forcing focus instead of splitting effort."
            )
        elif len(problems) > 1 and problems[0].score - problems[1].score <= 8:
            contradiction_note = (
                f"Several issues appeared, but {problems[0].label} beat {problems[1].label} after weighting what works in won deals above repeated objections."
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

        adaptation = self._build_adaptation_signal(previous_run, run_history, learned_patterns)
        raw_interpreted_icp = _humanize_segment(
            chosen_segment.label if chosen_segment else "",
            chosen_segment.evidence_quotes if chosen_segment else [],
            stage_hint,
        )
        interpreted_icp = raw_interpreted_icp
        if adaptation.get("mode") == "explore":
            previous_icp = (((previous_run or {}).get("decision_brief") or {}).get("recommended_icp") or "").strip()
            if previous_icp:
                interpreted_icp = previous_icp
        interpreted_problem = self._canonicalize_hypothesis(self._derive_core_problem(chosen_segment, problems, learned_patterns))
        previous_hypothesis = adaptation.get("previous_hypothesis") or (((previous_run or {}).get("decision_brief") or {}).get("core_problem") or "")
        alternative_hypotheses = self._generate_alternative_hypotheses(summary, interpreted_problem, previous_hypothesis)
        if adaptation.get("mode") == "explore" and alternative_hypotheses:
            interpreted_problem = alternative_hypotheses[0]
            if self._hypothesis_type(interpreted_problem) == "icp":
                interpreted_icp = self._narrow_icp_for_exploration(
                    interpreted_icp,
                    winning_pattern.get("summary") or learned_patterns.get("winning_pattern_summary") or "",
                    (((previous_run or {}).get("decision_brief") or {}).get("recommended_icp") or ""),
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
            "recommended_icp": _normalize_icp_text(interpreted_icp),
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
            "previous_run": previous_run or {},
            "previous_outcome": (previous_run or {}).get("outcome_log") or (previous_run or {}).get("result_log") or {},
            "run_history_count": len(run_history),
            "learned_patterns": learned_patterns,
            "winning_pattern_summary": winning_pattern.get("summary") or learned_patterns.get("winning_pattern_summary") or "",
            "previous_hypothesis": previous_hypothesis,
            "previous_icp": (((previous_run or {}).get("decision_brief") or {}).get("recommended_icp") or ""),
            "alternative_hypotheses": alternative_hypotheses[:3],
            "exploration_mode": adaptation.get("mode") == "explore",
            "stability_rule": "Keep the ICP stable and test only one new root problem this week." if adaptation.get("mode") == "explore" else "",
            "consecutive_no_improvement": adaptation.get("consecutive_no_improvement", 0),
            "same_problem_streak": adaptation.get("same_problem_streak", 0),
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
        structured_sections = [section for item in inputs for section in _parse_structured_sections(item.raw_text)]
        structured_source_types = {section["mapped_source"] for section in structured_sections if section.get("mapped_source")}
        source_types_present = {item.tag for item in inputs if item.tag} | structured_source_types
        repeated_clusters = [
            cluster
            for category in ("segments", "pains", "objections", "conversion_blockers", "buying_triggers")
            for cluster in (summary.get(category) or [])
            if cluster.frequency >= 2
        ]
        repeated_cross_source_clusters = [cluster for cluster in repeated_clusters if len(cluster.sources) >= 2]
        outcome_linked_clusters = [
            cluster for cluster in repeated_cross_source_clusters
            if cluster.won_signal_score > 0 or cluster.lost_signal_score > 0
        ]
        outcome_coverage = {
            outcome
            for cluster in repeated_cross_source_clusters
            for outcome, score in (("won", cluster.won_signal_score), ("lost", cluster.lost_signal_score))
            if score > 0
        }
        repeated_objections = [cluster for cluster in (summary.get("objections") or []) if cluster.frequency >= 2]
        consistent_icp = bool(summary.get("segments")) and (summary.get("segments")[0].frequency >= 1)
        partial_signal_pass = (
            consistent_icp
            and len(repeated_objections) >= 1
            and "won" in outcome_coverage
            and "lost" in outcome_coverage
            and len(source_types_present) >= 2
        )
        guidance = self._build_signal_collection_guidance()
        progress_status = []
        missing_pieces = []
        has_won_and_lost = "won" in outcome_coverage and "lost" in outcome_coverage

        if "crm_export" in source_types_present or "lost_deal" in source_types_present:
            progress_status.append("You already have CRM-style outcome data.")
        if "sales_call" in source_types_present or "customer_interview" in source_types_present:
            progress_status.append("You already have sales conversation data.")
        if "support" in source_types_present:
            progress_status.append("You already have support or onboarding friction data.")
        if repeated_clusters:
            progress_status.append(f"You already have {len(repeated_clusters)} repeated commercial signal(s).")
        if outcome_coverage:
            progress_status.append(f"You already have outcome coverage for: {', '.join(sorted(outcome_coverage))}.")
        if not progress_status:
            progress_status.append("You have started the workspace, but the engine cannot see a usable commercial pattern yet.")

        if ("crm_export" in source_types_present or "lost_deal" in source_types_present) and not (
            "sales_call" in source_types_present or "customer_interview" in source_types_present
        ):
            missing_pieces.append("You have CRM data, but no sales conversations yet.")
        if ("sales_call" in source_types_present or "customer_interview" in source_types_present) and not (
            "crm_export" in source_types_present or "lost_deal" in source_types_present
        ):
            missing_pieces.append("You have sales conversations, but no CRM won/lost outcomes yet.")
        if summary.get("objections") and not outcome_coverage:
            missing_pieces.append("You have objections, but no outcomes tied to won or lost deals yet.")
        if len(repeated_cross_source_clusters) < 2:
            missing_pieces.append("You do not have 2-3 repeated signals showing up across different sources yet.")
        if "support" not in source_types_present:
            missing_pieces.append("You do not have support or onboarding friction yet, which helps confirm what happens after the pitch.")
        if not missing_pieces:
            missing_pieces.append("Add one more cross-source pattern tied to a won or lost outcome to unlock the first decision.")

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
        if len(source_types_present) >= 3:
            score += 14
        elif len(source_types_present) >= 2:
            score += 8
        if len(repeated_cross_source_clusters) >= 3:
            score += 16
        elif len(repeated_cross_source_clusters) >= 2:
            score += 8
        elif len(repeated_cross_source_clusters) >= 1:
            score += 4
        if len(outcome_linked_clusters) >= 2:
            score += 14
        elif len(outcome_linked_clusters) >= 1:
            score += 6
        if partial_signal_pass:
            score += 12
        if extraction_source == "fallback_heuristics":
            score -= 18

        decision_score = 0
        if len(repeated_clusters) >= 2:
            decision_score += 1
        if len(source_types_present) >= 2:
            decision_score += 1
        if has_won_and_lost:
            decision_score += 1
        if partial_signal_pass:
            decision_score = max(decision_score, 2)

        insufficient_reasons = []
        if meaningful_input_count == 0:
            insufficient_reasons.append("The uploaded inputs do not contain enough readable commercial language yet.")
        if len(commercial_categories) < 2:
            insufficient_reasons.append("The engine could not find enough repeated commercial patterns across ICPs, pains, objections, or blockers.")
        if len(repeated_clusters) == 0:
            insufficient_reasons.append("The engine cannot see repeated commercial patterns yet.")
        if len(source_types_present) < 2:
            insufficient_reasons.append("The current input is too narrow. Add at least two source types such as sales calls plus CRM notes or support threads.")
        if not outcome_coverage and not partial_signal_pass:
            insufficient_reasons.append("The current inputs do not tie repeated signals to won or lost outcomes yet.")
        if structured_sections and any(section["empty"] or section["field_count"] == 0 for section in structured_sections):
            insufficient_reasons.append("Some structured sections were detected but have empty fields. Fill the marker templates before rerunning.")
        if extraction_source == "fallback_heuristics":
            insufficient_reasons.append("The result would rely on fallback heuristics rather than reliable LLM extraction.")

        strong_signal_pass = decision_score >= 3
        moderate_signal_pass = decision_score >= 2

        insufficient_signal = meaningful_input_count == 0 or len(source_types_present) < 2 or len(repeated_clusters) == 0
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
            "repeated_signal_count": len(repeated_clusters),
            "repeated_cross_source_count": len(repeated_cross_source_clusters),
            "outcome_linked_count": len(outcome_linked_clusters),
            "partial_signal_pass": partial_signal_pass,
            "moderate_signal_pass": moderate_signal_pass,
            "decision_score": decision_score,
            "has_won_and_lost": has_won_and_lost,
            "source_types_present": sorted(source_types_present),
            "outcome_coverage": sorted(outcome_coverage),
            "required_data_types": guidance["required_data_types"],
            "good_input_examples": guidance["good_input_examples"],
            "samples_needed": guidance["samples_needed"],
            "minimum_requirements": guidance["minimum_requirements"],
            "copy_paste_templates": guidance["copy_paste_templates"],
            "what_happens_next": guidance["what_happens_next"],
            "progress_status": progress_status,
            "missing_pieces": missing_pieces,
            "debug": {
                "extracted_signals": [
                    {
                        "category": (item.model_dump() if hasattr(item, "model_dump") else item).get("category"),
                        "label": (item.model_dump() if hasattr(item, "model_dump") else item).get("label"),
                        "source_tag": (item.model_dump() if hasattr(item, "model_dump") else item).get("source_tag"),
                    }
                    for item in (extraction.observations or [])[:20]
                ],
                "clusters_detected": {
                    category: [
                        {
                            "label": cluster.label,
                            "frequency": cluster.frequency,
                            "sources": cluster.sources,
                            "won_signal_score": cluster.won_signal_score,
                            "lost_signal_score": cluster.lost_signal_score,
                        }
                        for cluster in (summary.get(category) or [])[:8]
                    ]
                    for category in ("segments", "pains", "objections", "conversion_blockers", "buying_triggers")
                },
                "structured_sections": [
                    {
                        "marker": section["marker"],
                        "mapped_source": section["mapped_source"],
                        "field_count": section["field_count"],
                        "empty": section["empty"],
                    }
                    for section in structured_sections
                ],
                "repeated_signals_count": len(repeated_clusters),
                "source_types_count": len(source_types_present),
                "final_decision_score": decision_score,
                "final_quality_score": max(0, min(100, score)),
            },
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
- Weight won-deal patterns at 3.0, lost-deal patterns at 1.5, and neutral evidence at 1.0.
- Use patterns from won deals as the primary signal for ICP, pain, and decision speed.
- Treat objections like trust, hesitation, and risk as symptoms, then name the deeper root problem.
- If recent runs show no improvement for two consecutive runs, enter exploration mode.
- In exploration mode, keep the ICP stable unless it is clearly wrong, generate 2-3 alternative root-cause hypotheses from the evidence, and choose exactly one new hypothesis to test this week.
- Do not repeat the same core problem more than two runs in a row without measurable improvement.
- Never expose internal labels, extraction tokens, or awkward shorthand in the final answer.
- Use at most two short quotes for evidence, and never reuse raw quotes as landing page or outbound copy.
- Keep the core brief product-neutral. Do not mention HatchUp in the decision, why, execution plan, evidence, or assets.
- If you include product guidance, put it only in the optional how_to_use_hatchup field and keep it to 2-3 short lines.
- Do not use generic startup language such as \"improve landing page\", \"increase engagement\", or \"optimize funnel\".
- Write exact execution instructions and exact copy. No placeholders. No multiple options.
- Resolve contradictions explicitly and explain why one signal won.
- Before finalizing, check whether the core problem explains both the won-deal pattern and the lost-deal pattern. If not, rewrite it.
- Make the run feel evolutionary. Clearly state the previous hypothesis, the lack of improvement, the new hypothesis, and that this week is a test when exploration mode is active.
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
            rewritten = self._rewrite_for_humans(brief, decision_context)
            if (
                self._brief_is_generic(rewritten)
                or not self._brief_uses_context_evidence(rewritten, decision_context)
                or not self._core_problem_explains_outcomes(rewritten.core_problem, summary)
                or not self._brief_has_observable_change(rewritten, previous_run)
                or not self._measure_change_is_testable(rewritten)
                or not self._assets_sound_human(rewritten)
            ):
                repaired = self._rewrite_for_humans(fallback, decision_context)
                if (
                    not self._brief_has_observable_change(repaired, previous_run)
                    or not self._measure_change_is_testable(repaired)
                    or not self._assets_sound_human(repaired)
                ):
                    return repaired, "fallback_heuristics"
                return repaired, "fallback_heuristics"
            return rewritten, "llm_decision"
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
        if _has_repeated_tokens(brief.recommended_icp):
            return True
        if len((brief.recommended_icp or "").split()) > 20:
            return True
        return any(_sounds_like_raw_label(value) for value in (brief.recommended_icp, brief.core_problem, brief.decision))

    def _rewrite_for_humans(self, brief: RevenueWedgeDecisionBrief, decision_context: Dict[str, Any]) -> RevenueWedgeDecisionBrief:
        evidence_items = brief.evidence[:2]
        clean_icp = decision_context.get("recommended_icp") or brief.recommended_icp
        clean_problem = decision_context.get("core_problem") or brief.core_problem
        clean_trigger = decision_context.get("buying_trigger") or "the team has a near-term reason to act"
        trigger_clause = _trigger_to_clause(clean_trigger)
        previous_hypothesis = (decision_context.get("previous_hypothesis") or "").strip()
        alternative_hypotheses = decision_context.get("alternative_hypotheses") or []
        exploration_mode = bool(decision_context.get("exploration_mode"))
        previous_run = decision_context.get("previous_run") or {}
        variation = self._exploration_variant(decision_context, previous_run) if exploration_mode else {}
        if exploration_mode:
            clean_icp = variation.get("recommended_icp") or clean_icp
        clean_icp = _normalize_icp_text(clean_icp)
        landing_headline = "Know what to fix this week"
        landing_subheadline = _clean_copy(
            _founder_line(f"For {clean_icp.lower()} that need a clear next step before {trigger_clause}.", 14)
        )
        cta = "See the fix"
        outbound = _clean_copy(
            _founder_line(
                f"Hi {{first_name}}, if deals are stalling, I can show why and what to change this week.",
                16,
            )
        )
        talk_track = [
            _founder_line(f"The real problem is {clean_problem.lower()}.", 11),
            _founder_line("What is actually blocking the deal right now?", 9),
            _founder_line("Pick one fix and test it this week.", 9),
        ]
        comparison_to_last_run = brief.comparison_to_last_run
        if exploration_mode:
            landing_headline = _clean_copy(variation.get("headline") or landing_headline)
            landing_subheadline = _clean_copy(variation.get("subheadline") or landing_subheadline)
            outbound = _clean_copy(variation.get("outbound") or outbound)
            talk_track = [_clean_copy(item) for item in (variation.get("talk_track") or talk_track)]
            comparison_seed = variation.get("decision") or (
                f"Previous hypothesis: {previous_hypothesis or 'none recorded'}. "
                f"No improvement observed. New hypothesis: {clean_problem}. Testing this this week."
            )
            comparison_to_last_run = _clean_copy(
                f"{comparison_seed} "
                f"Alternative hypotheses considered: {', '.join(alternative_hypotheses[:3])}."
            )
        return RevenueWedgeDecisionBrief.model_validate(
            {
                **brief.model_dump(),
                "recommended_icp": clean_icp,
                "core_problem": clean_problem,
                "decision": _clean_copy(
                    (
                        variation.get("decision")
                        if exploration_mode and previous_hypothesis
                        else f"Focus on {clean_icp.lower()} this week and anchor the message on one promise: buyers will understand exactly what the product does, what output they get, and how it helps them decide."
                    )
                ),
                "this_week_execution": [
                    *[
                        _clean_copy(item)
                        for item in (
                            variation.get("execution")
                            if exploration_mode
                            else [
                                f"Update the homepage hero to speak directly to {clean_icp.lower()} and make the decision output concrete in the first screen.",
                                "Use the outbound message below only for active deals with this problem.",
                                "Run sales calls with the talk track below and log what breaks first.",
                                "Review replies and call notes after seven days before widening the ICP or changing the promise.",
                            ]
                        )
                    ],
                ],
                "assets": {
                    "landing_page_headline": landing_headline,
                    "landing_page_subheadline": landing_subheadline,
                    "landing_page_cta": cta,
                    "outbound_message": outbound,
                    "sales_talk_track": talk_track,
                },
                "evidence": [item.model_dump() if hasattr(item, "model_dump") else item for item in evidence_items],
                "comparison_to_last_run": comparison_to_last_run,
                "run_to_run_intelligence": {
                    **(brief.run_to_run_intelligence.model_dump() if hasattr(brief.run_to_run_intelligence, "model_dump") else {}),
                    "previous_hypothesis": previous_hypothesis,
                    "new_hypothesis": clean_problem,
                    "alternative_hypotheses": alternative_hypotheses[:3],
                    "exploration_mode": exploration_mode,
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
        if _normalize_icp_text(brief.recommended_icp).strip().lower() != _normalize_icp_text(decision_context.get("recommended_icp", "")).strip().lower():
            return False
        if _has_repeated_tokens(brief.recommended_icp):
            return False
        if len((brief.recommended_icp or "").split()) > 20:
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
        previous_hypothesis = (decision_context.get("previous_hypothesis") or "").strip()
        alternative_hypotheses = decision_context.get("alternative_hypotheses") or []
        exploration_mode = bool(decision_context.get("exploration_mode"))
        variation = self._exploration_variant(decision_context, previous_run) if exploration_mode else {}
        if exploration_mode:
            icp = variation.get("recommended_icp") or icp
        icp = _normalize_icp_text(icp)
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
        if exploration_mode:
            comparison = _clean_copy(
                variation.get("decision")
                or f"Previous hypothesis: {previous_hypothesis or 'none recorded'}. No improvement observed. New hypothesis: {problem}. Testing this this week."
            )

        decision = f"Focus this week on {icp.lower()} and make the pitch about removing the risk behind {problem.lower()}."
        if "understand" in problem.lower() or "output" in problem.lower():
            decision = (
                f"Focus this week on {icp.lower()} and make the pitch about showing exactly what the product does, "
                "what output it produces, and how that improves a live decision."
            )
        if exploration_mode and previous_hypothesis:
            decision = variation.get("decision") or decision
        execution = [
            _clean_copy(item)
            for item in (
                variation.get("execution")
                if exploration_mode
                else [
                    f"Replace the hero section with the headline below and say exactly what to fix this week.",
                    f"Send the outbound message only to {icp.lower()} accounts that are visibly in {stage_focus} or under {trigger}.",
                    f"Open every sales conversation with \"{phrase}\" and ask what is blocking the deal right now.",
                    f"Track replies, booked calls, and explicit rejections against the current problem statement for seven days before changing direction.",
                ]
            )
        ]
        headline = variation.get("headline") or "See why deals are failing"
        subheadline = variation.get("subheadline") or _founder_line(f"For {icp.lower()} that need to know what to fix before {trigger}.", 14)
        cta = "See the fix"
        outbound = variation.get("outbound") or (
            _founder_line(
                f"Hi {{first_name}}, if deals are slowing down because {problem.lower()}, I can show what to change this week.",
                18,
            )
        )
        talk_track = variation.get("talk_track") or [
            _founder_line(f"Teams like yours slow down when {problem.lower()}.", 11),
            _founder_line("What is breaking the deal right now?", 7),
            _founder_line("Test one fix this week, not five.", 8),
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
                    f"Confidence is based on repeated evidence for {icp} and {problem}, weighted first toward won-deal patterns, then lost deals, sales calls, CRM exports, "
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
                    "previous_hypothesis": previous_hypothesis,
                    "new_hypothesis": problem,
                    "alternative_hypotheses": alternative_hypotheses[:3],
                    "exploration_mode": exploration_mode,
                },
                "how_to_use_hatchup": [
                    "Use HatchUp to store this run, then log replies, calls, deals, and objections against the run ID.",
                    "Run it again after the next batch of conversations so the recommendation sharpens based on real outcomes.",
                ],
            }
        )
