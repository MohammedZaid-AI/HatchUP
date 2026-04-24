import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.env_utils import normalize_secret
from src.talent_scout_models import InstagramEnrichment, TalentProfile, TalentScoutResponse, TalentSignals


class _LLMTalentAnalysis(BaseModel):
    inferred_role: str = Field(default="Unknown")
    niche: str = Field(default="general")
    summary: str = Field(default="No summary available.")


class _TTLCache:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._data: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if now > expires_at:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.time() + self.ttl_seconds, value)


class TalentScoutService:
    INSTAGRAM_KEYWORDS = {"startup", "growth", "saas", "branding", "ai", "design", "creator", "product", "marketing"}
    CREATOR_ROLE_TERMS = {"marketing", "marketer", "designer", "design", "brand", "creator", "content"}
    TECH_ROLE_TERMS = {"engineer", "developer", "backend", "frontend", "fullstack", "ml", "data", "ai"}

    def __init__(self) -> None:
        self.session = requests.Session()
        self.cache = _TTLCache(ttl_seconds=900)
        self.instagram_access_token = normalize_secret(os.environ.get("INSTAGRAM_ACCESS_TOKEN"))
        self.instagram_business_id = normalize_secret(os.environ.get("INSTAGRAM_BUSINESS_ID"))
        self.github_token = normalize_secret(os.environ.get("GITHUB_TOKEN"))
        self.twitter_bearer_token = normalize_secret(os.environ.get("TWITTER_BEARER_TOKEN") or os.environ.get("X_BEARER_TOKEN"))
        self.groq_api_key = normalize_secret(os.environ.get("GROQ_API_KEY"))
        self.groq_model_name = normalize_secret(os.environ.get("GROQ_MODEL_NAME")) or "openai/gpt-oss-20b"
        self._llm = None

    def discover(self, role: str) -> TalentScoutResponse:
        normalized_role = (role or "").strip()
        if not normalized_role:
            raise ValueError("role is required")

        cache_key = normalized_role.lower()
        cached_payload = self.cache.get(cache_key)
        if cached_payload:
            return TalentScoutResponse(**{**cached_payload, "cached": True})

        creator_mode = self._is_creator_mode(normalized_role)
        platform_status: Dict[str, str] = {}

        raw_candidates: List[Dict[str, Any]] = []
        github_candidates, github_status = self._search_github(normalized_role)
        raw_candidates.extend(github_candidates)
        platform_status["github"] = github_status

        twitter_candidates, twitter_status = self._search_twitter(normalized_role)
        raw_candidates.extend(twitter_candidates)
        platform_status["twitter"] = twitter_status

        kaggle_candidates, kaggle_status = self._search_kaggle(normalized_role)
        raw_candidates.extend(kaggle_candidates)
        platform_status["kaggle"] = kaggle_status

        huggingface_candidates, huggingface_status = self._search_huggingface(normalized_role)
        raw_candidates.extend(huggingface_candidates)
        platform_status["huggingface"] = huggingface_status

        linkedin_candidates, linkedin_status = self._search_linkedin(normalized_role)
        raw_candidates.extend(linkedin_candidates)
        platform_status["linkedin"] = linkedin_status

        devpost_candidates, devpost_status = self._search_devpost(normalized_role)
        raw_candidates.extend(devpost_candidates)
        platform_status["devpost"] = devpost_status

        merged_candidates = self._merge_candidates(raw_candidates)
        ranked_profiles = self._build_ranked_profiles(merged_candidates, normalized_role, creator_mode)
        top_candidates = ranked_profiles[:10]

        response_payload = {
            "role": normalized_role,
            "creator_mode": creator_mode,
            "top_candidates": [profile.model_dump() for profile in top_candidates],
            "platform_status": platform_status,
            "formatted_table": self._build_table(top_candidates),
            "cached": False,
        }
        self.cache.set(cache_key, response_payload)
        return TalentScoutResponse(**response_payload)

    def _is_creator_mode(self, role: str) -> bool:
        lowered = role.lower()
        return any(term in lowered for term in self.CREATOR_ROLE_TERMS)

    def _headers(self, auth_token: str = "") -> Dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "HatchUp-TalentScout/1.0"}
        if auth_token:
            headers["Authorization"] = auth_token
        return headers

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 20,
    ) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = self.session.request(method, url, headers=headers, params=params, timeout=timeout)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = min(5, int(retry_after)) if retry_after and retry_after.isdigit() else attempt + 1
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise RuntimeError(str(last_error) if last_error else "Unknown API request failure")

    def _search_github(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        query = f"{role} in:bio type:user"
        headers = self._headers(f"Bearer {self.github_token}" if self.github_token else "")
        try:
            search_payload = self._request_json(
                "GET",
                "https://api.github.com/search/users",
                headers=headers,
                params={"q": query, "per_page": 5},
            )
        except Exception as exc:
            return [], f"unavailable: {exc}"

        candidates: List[Dict[str, Any]] = []
        for item in search_payload.get("items", [])[:5]:
            username = item.get("login", "")
            if not username:
                continue
            try:
                user_payload = self._request_json("GET", f"https://api.github.com/users/{username}", headers=headers)
                repos_payload = self._request_json(
                    "GET",
                    f"https://api.github.com/users/{username}/repos",
                    headers=headers,
                    params={"sort": "updated", "per_page": 5},
                )
            except Exception:
                continue
            total_stars = sum(int(repo.get("stargazers_count") or 0) for repo in repos_payload or [])
            top_repo = max(repos_payload or [], key=lambda repo: int(repo.get("stargazers_count") or 0), default={})
            bio = user_payload.get("bio") or ""
            candidates.append(
                {
                    "name": user_payload.get("name") or username,
                    "username": username,
                    "platforms": ["github"],
                    "source_urls": {"github": user_payload.get("html_url") or item.get("html_url") or ""},
                    "bios": [bio],
                    "evidence": {
                        "github": f"{user_payload.get('public_repos', 0)} repos, {total_stars} stars, top repo {top_repo.get('name', 'n/a')}",
                    },
                    "metrics": {
                        "github_repos": int(user_payload.get("public_repos") or 0),
                        "github_followers": int(user_payload.get("followers") or 0),
                        "github_stars": total_stars,
                    },
                    "portfolio_urls": [value for value in [user_payload.get("blog")] if value],
                    "role_hint": bio or role,
                }
            )
        return candidates, "ok" if candidates else "no matching candidates returned"

    def _search_twitter(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        if not self.twitter_bearer_token:
            return [], "skipped: TWITTER_BEARER_TOKEN not configured"

        params = {
            "query": f'"{role}" -is:retweet lang:en',
            "max_results": 10,
            "expansions": "author_id",
            "tweet.fields": "created_at,public_metrics,text",
            "user.fields": "name,username,description,public_metrics",
        }
        headers = self._headers(f"Bearer {self.twitter_bearer_token}")
        try:
            payload = self._request_json("GET", "https://api.twitter.com/2/tweets/search/recent", headers=headers, params=params)
        except Exception as exc:
            return [], f"unavailable: {exc}"

        users = {user.get("id"): user for user in (payload.get("includes") or {}).get("users", [])}
        tweets_by_user: Dict[str, List[Dict[str, Any]]] = {}
        for tweet in payload.get("data", []) or []:
            tweets_by_user.setdefault(tweet.get("author_id", ""), []).append(tweet)

        candidates: List[Dict[str, Any]] = []
        for author_id, tweets in tweets_by_user.items():
            user = users.get(author_id) or {}
            username = user.get("username", "")
            if not username:
                continue
            bio = user.get("description") or ""
            niche_text = " ".join(tweet.get("text", "") for tweet in tweets[:3])
            public_metrics = user.get("public_metrics") or {}
            tweet_metrics = [
                (tweet.get("public_metrics") or {}).get("like_count", 0) + (tweet.get("public_metrics") or {}).get("retweet_count", 0)
                for tweet in tweets
            ]
            candidates.append(
                {
                    "name": user.get("name") or username,
                    "username": username,
                    "platforms": ["twitter"],
                    "source_urls": {"twitter": f"https://x.com/{username}"},
                    "bios": [bio, niche_text],
                    "evidence": {
                        "twitter": f"{len(tweets)} recent tweets matched query, {public_metrics.get('followers_count', 0)} followers",
                    },
                    "metrics": {
                        "twitter_followers": int(public_metrics.get("followers_count") or 0),
                        "twitter_tweets": len(tweets),
                        "twitter_engagement": sum(int(value or 0) for value in tweet_metrics),
                    },
                    "portfolio_urls": [],
                    "role_hint": bio or niche_text or role,
                }
            )
        return candidates, "ok" if candidates else "no matching candidates returned"

    def _search_kaggle(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        return [], "placeholder: Kaggle people search requires additional API credentials and normalization logic"

    def _search_huggingface(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        try:
            payload = self._request_json(
                "GET",
                "https://huggingface.co/api/users",
                params={"search": role, "limit": 5},
            )
        except Exception as exc:
            return [], f"unavailable: {exc}"

        candidates: List[Dict[str, Any]] = []
        for item in payload or []:
            username = item.get("name") or item.get("fullname") or ""
            if not username:
                continue
            profile_name = item.get("fullname") or username
            candidates.append(
                {
                    "name": profile_name,
                    "username": username,
                    "platforms": ["huggingface"],
                    "source_urls": {"huggingface": f"https://huggingface.co/{username}"},
                    "bios": [item.get("details") or "", item.get("type") or ""],
                    "evidence": {"portfolio": "Hugging Face profile found"},
                    "metrics": {"portfolio_signal": 45},
                    "portfolio_urls": [f"https://huggingface.co/{username}"],
                    "role_hint": role,
                }
            )
        return candidates, "ok" if candidates else "no matching candidates returned"

    def _search_linkedin(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        return [], "skipped: LinkedIn candidate search is not available without approved partner access"

    def _search_devpost(self, role: str) -> Tuple[List[Dict[str, Any]], str]:
        return [], "skipped: Devpost official candidate discovery API is not configured"

    def _merge_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for candidate in candidates:
            key = (candidate.get("username") or candidate.get("name") or "").strip().lower()
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    "name": candidate.get("name") or candidate.get("username") or "Unknown",
                    "username": candidate.get("username") or "",
                    "platforms": list(candidate.get("platforms") or []),
                    "source_urls": dict(candidate.get("source_urls") or {}),
                    "bios": list(candidate.get("bios") or []),
                    "evidence": dict(candidate.get("evidence") or {}),
                    "metrics": dict(candidate.get("metrics") or {}),
                    "portfolio_urls": list(candidate.get("portfolio_urls") or []),
                    "role_hint": candidate.get("role_hint") or "",
                }
                continue

            existing = merged[key]
            existing["platforms"] = sorted(set(existing["platforms"]) | set(candidate.get("platforms") or []))
            existing["source_urls"].update(candidate.get("source_urls") or {})
            existing["bios"].extend(candidate.get("bios") or [])
            existing["evidence"].update(candidate.get("evidence") or {})
            existing["portfolio_urls"].extend(candidate.get("portfolio_urls") or [])
            for metric_key, metric_value in (candidate.get("metrics") or {}).items():
                existing["metrics"][metric_key] = max(metric_value, existing["metrics"].get(metric_key, 0))
        return list(merged.values())

    def _build_ranked_profiles(self, candidates: List[Dict[str, Any]], role: str, creator_mode: bool) -> List[TalentProfile]:
        ranked_profiles: List[TalentProfile] = []
        for candidate in candidates:
            instagram = self._instagram_enrichment(candidate)
            llm_analysis = self._analyze_candidate(candidate, role, instagram)
            github_score = self._github_score(candidate.get("metrics") or {})
            twitter_score = self._twitter_score(candidate.get("metrics") or {}, candidate.get("bios") or [], role)
            instagram_score = self._instagram_score(instagram, role)
            portfolio_score = self._portfolio_score(candidate.get("portfolio_urls") or [], candidate.get("platforms") or [])
            final_score = self._composite_score(
                github_score=github_score,
                twitter_score=twitter_score,
                instagram_score=instagram_score,
                portfolio_score=portfolio_score,
                creator_mode=creator_mode,
            )
            signals = TalentSignals(
                github=f"GitHub score {github_score}/100 from repos, stars, and follower traction.",
                twitter=f"Twitter/X score {twitter_score}/100 from topical activity and audience fit.",
                instagram=f"Instagram score {instagram_score}/100 from follower quality, niche keywords, and post signals.",
                portfolio=f"Portfolio score {portfolio_score}/100 from external proof-of-work links and profile depth.",
            )
            ranked_profiles.append(
                TalentProfile(
                    name=candidate.get("name") or candidate.get("username") or "Unknown",
                    username=candidate.get("username") or "",
                    role=llm_analysis.inferred_role or role,
                    summary=llm_analysis.summary,
                    niche=llm_analysis.niche,
                    platforms=sorted(set((candidate.get("platforms") or []) + (["instagram"] if instagram.available else []))),
                    score=final_score,
                    signals=signals,
                    source_urls=candidate.get("source_urls") or {},
                    metrics={
                        **(candidate.get("metrics") or {}),
                        "github_score": github_score,
                        "twitter_signal": twitter_score,
                        "instagram_signal": instagram_score,
                        "portfolio_signal": portfolio_score,
                    },
                    instagram=instagram,
                    creator_mode=creator_mode,
                )
            )
        return sorted(ranked_profiles, key=lambda profile: profile.score, reverse=True)

    def _instagram_enrichment(self, candidate: Dict[str, Any]) -> InstagramEnrichment:
        handle = self._guess_instagram_handle(candidate)
        if not handle:
            return InstagramEnrichment(error="instagram handle not inferred")
        if not self.instagram_access_token or not self.instagram_business_id:
            return InstagramEnrichment(instagram_handle=handle, error="Instagram Graph API credentials not configured")

        fields = (
            f"business_discovery.username({handle})"
            "{username,followers_count,media_count,media.limit(5){caption,comments_count,like_count,timestamp,permalink}}"
        )
        try:
            payload = self._request_json(
                "GET",
                f"https://graph.facebook.com/v18.0/{self.instagram_business_id}",
                params={"fields": fields, "access_token": self.instagram_access_token},
            )
        except Exception as exc:
            return InstagramEnrichment(instagram_handle=handle, error=f"Instagram unavailable: {exc}")

        data = payload.get("business_discovery") or {}
        if not data:
            return InstagramEnrichment(instagram_handle=handle, error="Instagram business discovery returned no profile")

        posts = data.get("media", {}).get("data", []) or []
        captions = [post.get("caption", "") for post in posts]
        caption_text = " ".join(captions).lower()
        matched_keywords = sorted({keyword for keyword in self.INSTAGRAM_KEYWORDS if keyword in caption_text})
        avg_engagement = 0.0
        if posts:
            avg_engagement = sum(
                int(post.get("like_count") or 0) + int(post.get("comments_count") or 0)
                for post in posts
            ) / len(posts)
        engagement_signal = "high" if avg_engagement >= 300 else "medium" if avg_engagement >= 75 else "low"
        content_type = self._content_type_from_text(caption_text)
        return InstagramEnrichment(
            instagram_handle=data.get("username") or handle,
            followers=int(data.get("followers_count") or 0),
            media_count=int(data.get("media_count") or 0),
            content_type=content_type,
            engagement_signal=engagement_signal,
            keywords=matched_keywords,
            recent_posts=[
                {
                    "caption": post.get("caption") or "",
                    "hashtags": re.findall(r"#(\w+)", post.get("caption") or ""),
                    "likes": int(post.get("like_count") or 0),
                    "comments": int(post.get("comments_count") or 0),
                    "timestamp": post.get("timestamp") or "",
                    "permalink": post.get("permalink") or "",
                }
                for post in posts[:5]
            ],
            available=True,
        )

    def _guess_instagram_handle(self, candidate: Dict[str, Any]) -> str:
        username = re.sub(r"[^A-Za-z0-9._]", "", candidate.get("username") or "")
        bios = " ".join(candidate.get("bios") or [])
        explicit_match = re.search(r"(?:instagram\.com/|@)([A-Za-z0-9._]{3,30})", bios, re.IGNORECASE)
        if explicit_match:
            return explicit_match.group(1)
        return username

    def _content_type_from_text(self, text: str) -> str:
        if any(term in text for term in ("growth", "marketing", "brand", "launch", "copy")):
            return "marketing"
        if any(term in text for term in ("design", "ui", "ux", "visual", "branding")):
            return "design"
        if any(term in text for term in ("code", "developer", "engineering", "ai", "saas")):
            return "technical"
        return "unknown"

    def _github_score(self, metrics: Dict[str, Any]) -> int:
        repos = int(metrics.get("github_repos") or 0)
        stars = int(metrics.get("github_stars") or 0)
        followers = int(metrics.get("github_followers") or 0)
        raw = min(100, repos * 4 + min(40, math.log1p(max(stars, 0)) * 10) + min(20, math.log1p(max(followers, 0)) * 6))
        return int(round(raw))

    def _twitter_score(self, metrics: Dict[str, Any], bios: List[str], role: str) -> int:
        followers = int(metrics.get("twitter_followers") or 0)
        activity = int(metrics.get("twitter_tweets") or 0)
        engagement = int(metrics.get("twitter_engagement") or 0)
        role_terms = self._keyword_overlap(" ".join(bios), role)
        raw = min(100, min(35, math.log1p(max(followers, 0)) * 6) + activity * 5 + min(35, math.log1p(max(engagement, 0)) * 8) + role_terms * 10)
        return int(round(raw))

    def _instagram_score(self, instagram: InstagramEnrichment, role: str) -> int:
        followers = instagram.followers
        relevance = self._keyword_overlap(" ".join(instagram.keywords + [instagram.content_type]), role)
        engagement_bonus = {"low": 10, "medium": 22, "high": 35}.get(instagram.engagement_signal, 0)
        raw = min(100, min(40, math.log1p(max(followers, 0)) * 8) + relevance * 15 + engagement_bonus)
        return int(round(raw))

    def _portfolio_score(self, portfolio_urls: List[str], platforms: List[str]) -> int:
        raw = 15
        raw += min(35, len([url for url in portfolio_urls if url]) * 15)
        raw += min(30, len(platforms) * 8)
        if any(platform in {"huggingface", "devpost", "kaggle"} for platform in platforms):
            raw += 20
        return min(100, raw)

    def _composite_score(
        self,
        *,
        github_score: int,
        twitter_score: int,
        instagram_score: int,
        portfolio_score: int,
        creator_mode: bool,
    ) -> float:
        if creator_mode:
            score = (
                github_score * 0.2
                + twitter_score * 0.2
                + instagram_score * 0.4
                + portfolio_score * 0.2
            )
        else:
            score = (
                github_score * 0.4
                + twitter_score * 0.2
                + instagram_score * 0.2
                + portfolio_score * 0.2
            )
        return round(min(100, score), 2)

    def _keyword_overlap(self, text: str, role: str) -> int:
        haystack = set(re.findall(r"[a-z0-9\+]+", (text or "").lower()))
        needles = set(re.findall(r"[a-z0-9\+]+", (role or "").lower()))
        return len(haystack & needles)

    def _analyze_candidate(self, candidate: Dict[str, Any], role: str, instagram: InstagramEnrichment) -> _LLMTalentAnalysis:
        profile_text = json.dumps(
            {
                "target_role": role,
                "name": candidate.get("name"),
                "username": candidate.get("username"),
                "platforms": candidate.get("platforms"),
                "bios": candidate.get("bios"),
                "evidence": candidate.get("evidence"),
                "instagram": instagram.model_dump(),
            },
            ensure_ascii=True,
        )
        if not self.groq_api_key:
            return self._heuristic_analysis(candidate, role, instagram)

        try:
            if self._llm is None:
                from langchain_groq import ChatGroq

                self._llm = ChatGroq(
                    temperature=0,
                    model_name=self.groq_model_name,
                    groq_api_key=self.groq_api_key,
                )
            parser = PydanticOutputParser(pydantic_object=_LLMTalentAnalysis)
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a recruiter-grade talent intelligence analyst. Return concise, factual JSON only.",
                    ),
                    (
                        "user",
                        "Analyze this candidate for the target role.\n{profile}\n\n"
                        "Infer the best-fit role, extract the dominant niche like AI, SaaS, Web3, design, or growth, "
                        "and write a one-sentence summary.\n{format_instructions}",
                    ),
                ]
            )
            chain = prompt | self._llm | parser
            return chain.invoke({"profile": profile_text, "format_instructions": parser.get_format_instructions()})
        except Exception:
            return self._heuristic_analysis(candidate, role, instagram)

    def _heuristic_analysis(self, candidate: Dict[str, Any], role: str, instagram: InstagramEnrichment) -> _LLMTalentAnalysis:
        text = " ".join(candidate.get("bios") or []).lower()
        niche = "AI" if "ai" in text else "SaaS" if "saas" in text else "Web3" if "web3" in text else "growth" if "growth" in text else "general"
        inferred_role = role.title()
        if any(term in text for term in ("frontend", "react", "ui")):
            inferred_role = "Frontend Developer"
        elif any(term in text for term in ("backend", "python", "api")):
            inferred_role = "Backend Developer"
        elif any(term in text for term in ("growth", "marketing", "brand")):
            inferred_role = "Growth Marketer"
        elif any(term in text for term in ("design", "ux", "branding")):
            inferred_role = "Product Designer"

        instagram_phrase = ""
        if instagram.available:
            instagram_phrase = f" with {instagram.engagement_signal} Instagram engagement and {instagram.content_type}-leaning content"
        summary = (
            f"Top {niche} {inferred_role.lower()} candidate with evidence across {', '.join(candidate.get('platforms') or ['public profiles'])}"
            f"{instagram_phrase}."
        )
        return _LLMTalentAnalysis(inferred_role=inferred_role, niche=niche, summary=summary)

    def _build_table(self, profiles: List[TalentProfile]) -> List[Dict[str, Any]]:
        return [
            {
                "rank": index + 1,
                "name": profile.name,
                "username": profile.username,
                "role": profile.role,
                "score": profile.score,
                "platforms": ", ".join(profile.platforms),
                "niche": profile.niche,
            }
            for index, profile in enumerate(profiles)
        ]
