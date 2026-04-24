from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TalentScoutRequest(BaseModel):
    role: str = Field(description="Role or hiring intent, such as growth marketer or frontend developer.")


class InstagramEnrichment(BaseModel):
    instagram_handle: str = ""
    followers: int = 0
    media_count: int = 0
    content_type: str = "unknown"
    engagement_signal: str = "low"
    keywords: List[str] = []
    recent_posts: List[Dict[str, Any]] = []
    available: bool = False
    error: Optional[str] = None


class TalentSignals(BaseModel):
    github: str = ""
    twitter: str = ""
    instagram: str = ""
    portfolio: str = ""


class TalentProfile(BaseModel):
    name: str
    username: str
    role: str
    summary: str
    niche: str = "general"
    platforms: List[str]
    score: float = 0.0
    signals: TalentSignals
    source_urls: Dict[str, str] = {}
    metrics: Dict[str, Any] = {}
    instagram: InstagramEnrichment = Field(default_factory=InstagramEnrichment)
    creator_mode: bool = False


class TalentScoutResponse(BaseModel):
    role: str
    creator_mode: bool
    top_candidates: List[TalentProfile]
    platform_status: Dict[str, str]
    formatted_table: List[Dict[str, Any]]
    cached: bool = False
