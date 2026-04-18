
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class SectionAnalysis(BaseModel):
    content: str = Field(description="extracted content for this section")
    status: str = Field(description="present, missing, or unclear")
    notes: Optional[str] = Field(description="analyst notes on quality or specificity")

class PitchDeckData(BaseModel):
    startup_name: str = Field(description="Name of the startup")
    problem: str = Field(description="The problem statement")
    solution: str = Field(description="The proposed solution")
    product: str = Field(description="Details about the product")
    market_tam: str = Field(description="Market size and TAM analysis")
    business_model: str = Field(description="How they make money")
    traction_metrics: str = Field(description="Current traction, revenue, users, etc.")
    team: str = Field(description="Key team members and backgrounds")
    competitive_landscape: str = Field(description="Competitors and differentiation")
    funding_ask_stage: str = Field(description="Amount raising and current stage (e.g., Pre-Seed, Seed)")
    
    missing_sections: List[str] = Field(description="List of standard sections that are completely missing")
    weak_signals: List[str] = Field(description="Areas where the deck is vague or unconvincing")
    red_flags: List[str] = Field(description="Major concerns or risks identified")

class InvestmentMemo(BaseModel):
    company_overview: str
    problem_solution_clarity: str
    market_opportunity: str
    product_differentiation: str
    traction_metrics_analysis: str
    team_assessment: str
    risks_concerns: List[str]
    open_questions: List[str]
    neutral_assessment: Optional[str] = Field(default="No specific assessment provided.", description="Final verdict")

class ExecutiveSummary(BaseModel):
    summary_bullet_points: List[str] = Field(description="5-7 bullet points summarizing the deal")
    decision_outlook: Optional[str] = Field(default="Neutral", description="Neutral outlook: Positive, Neutral, or Negative leanings based on data")
    confidence_score: Optional[int] = Field(default=50, description="A score from 0-100 indicating how well this startup aligns with current market trends and problem spaces.")
    market_alignment_reasoning: Optional[str] = Field(default="Market alignment data unavailable.", description="Explanation for the confidence score based on current market trends.")


class RevenueObservation(BaseModel):
    input_id: str = Field(description="Source input id")
    source_tag: str = Field(description="Tagged source type such as sales_call or lost_deal")
    category: str = Field(description="One of segment, pain, objection, trigger, blocker, feature_request, urgency, language, stage")
    label: str = Field(description="Canonical short label, 2-6 words")
    supporting_quote: str = Field(description="Short supporting phrase or quote from the source")
    stage: Optional[str] = Field(default="unknown", description="Pipeline stage such as awareness, evaluation, proposal, onboarding, renewal, or unknown")
    impact_direction: str = Field(description="positive, negative, or neutral")


class RevenueSignalExtraction(BaseModel):
    observations: List[RevenueObservation] = Field(description="Normalized observations extracted from all uploaded inputs")
    synthesis_notes: List[str] = Field(description="Short notes about meaningful patterns seen across the data")


class RevenueCluster(BaseModel):
    category: str
    label: str
    score: int
    frequency: int
    weighted_frequency: int
    revenue_impact: int
    conversion_signal: int
    outcome_score: int
    won_signal_score: int = 0
    lost_signal_score: int = 0
    sources: List[str]
    evidence_quotes: List[str]
    stages: List[str]

class RevenueEvidenceItem(BaseModel):
    quote: str
    source_tags: List[str]
    signal: str
    why_it_matters: str


class RevenueWedgeAssets(BaseModel):
    landing_page_headline: str
    landing_page_subheadline: str
    landing_page_cta: str
    outbound_message: str
    sales_talk_track: List[str]


class RevenueWedgeDecisionBrief(BaseModel):
    recommended_icp: str
    core_problem: str
    decision: str
    this_week_execution: List[str]
    assets: RevenueWedgeAssets
    confidence_score: int = Field(description="0-100 confidence score")
    confidence_reasoning: str
    evidence: List[RevenueEvidenceItem]
    contradiction_resolution: str
    comparison_to_last_run: str
    run_to_run_intelligence: "RevenueRunComparison"
    how_to_use_hatchup: List[str]


class RevenueRunOutcome(BaseModel):
    outcome: str = "unknown"
    replies: int = 0
    calls_booked: int = 0
    deals_closed: int = 0
    top_objection: str = ""
    metric_delta: str = ""
    notes: str = ""
    logged_at: Optional[str] = None


class RevenueRunComparison(BaseModel):
    previous_run_id: str = ""
    what_changed: List[str]
    what_improved: List[str]
    what_failed: List[str]
    next_move: str
    adaptation_reasoning: str
    previous_hypothesis: str = ""
    new_hypothesis: str = ""
    alternative_hypotheses: List[str] = []
    exploration_mode: bool = False


class RevenueLearnedPattern(BaseModel):
    best_icp: str = ""
    recurring_objections: List[str]
    winning_messages: List[str]
    last_adaptation: str = ""
    strongest_problem: str = ""
    winning_pattern_summary: str = ""


class RevenueWedgeInputRecord(BaseModel):
    input_id: str
    title: str
    tag: str
    source_type: str
    filename: Optional[str] = None
    content_type: str
    raw_text: str
    excerpt: str
    created_at: str
    updated_at: str


class RevenueWedgeRunRecord(BaseModel):
    run_id: str
    created_at: str
    input_ids: List[str]
    signals: Dict[str, List[RevenueCluster]]
    decision_brief: RevenueWedgeDecisionBrief
    snapshot: Dict[str, object]
    outcome_log: Optional[RevenueRunOutcome] = None
    comparison: Optional[RevenueRunComparison] = None
