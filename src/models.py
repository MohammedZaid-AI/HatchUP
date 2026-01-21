
from pydantic import BaseModel, Field
from typing import List, Optional

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
    neutral_assessment: str

class ExecutiveSummary(BaseModel):
    summary_bullet_points: List[str] = Field(description="5-7 bullet points summarizing the deal")
    decision_outlook: Optional[str] = Field(default="Neutral", description="Neutral outlook: Positive, Neutral, or Negative leanings based on data")
    confidence_score: Optional[int] = Field(default=50, description="A score from 0-100 indicating how well this startup aligns with current market trends and problem spaces.")
    market_alignment_reasoning: Optional[str] = Field(default="Market alignment data unavailable.", description="Explanation for the confidence score based on current market trends.")
