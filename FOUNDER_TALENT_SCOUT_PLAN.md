# Founder Talent Scout
# Founder Talent Scout

## Product Goal
Build an AI-native talent discovery assistant inside Founder Mode that helps founders find high-signal people outside traditional resume-first platforms.

## MVP Positioning
The first version should answer a founder query like:

- `Find me a backend engineer who has worked on AI agents`
- `Find a growth hacker experienced in early-stage startups`

The MVP should return:

- ranked candidate recommendations
- short profile summaries
- proof-of-work signals
- credibility and startup-fit scores
- a suggested outreach opener

## Why It Can Beat LinkedIn
- LinkedIn is optimized for self-description. Talent Scout is optimized for public evidence.
- LinkedIn search is title-heavy. Talent Scout can rank by projects, contributions, discussions, and writing.
- LinkedIn underweights startup intensity. Talent Scout can explicitly score speed, ownership, and zero-to-one fit.

## Data Sources
- GitHub: repos, commits, starred projects, issue and PR discussions, language mix, maintainer behavior
- X: topic clusters, thread quality, relevant followers, founder interactions, consistency of expertise
- Personal websites: portfolio depth, case studies, launch logs, technical writing
- Newsletters and creator channels: audience trust, niche authority, recurring insight quality
- Indie communities: Hacker News, Product Hunt, Indie Hackers, dev forums, niche Slack or Discord communities

## Core Signals
- Skill relevance: overlap with the founder query and desired capabilities
- Proof-of-work quality: shipped projects, repo depth, launch evidence, case studies
- Credibility: trusted interactions, follower quality, backlinks, peer references, OSS trust
- Startup fit: breadth, speed, ambiguity tolerance, early-stage experience, ownership patterns
- Freshness: recent activity and current engagement

## Ranking Stack
Use a two-stage system:

1. Retrieval
- hybrid keyword + embedding retrieval across normalized candidate profiles
- query expansion for synonyms like `growth hacker`, `demand gen`, `product marketer`

2. Ranking
- weighted model with:
  - relevance: 35-45%
  - proof-of-work: 20-25%
  - startup fit: 15-25%
  - credibility: 10-20%
  - freshness: 5-10%

Production ranking can move from hand-tuned weights to learned ranking based on founder saves, replies, interviews, and hires.

## AI Architecture
- ingestion workers pull structured public data from approved APIs and crawlers
- profile normalizer merges identities across platforms into one candidate graph
- embeddings store supports semantic retrieval on skills, projects, and work style
- LLM layer summarizes profiles, explains ranking, and drafts outreach messages
- feedback loop stores founder actions to improve ranking over time

## Recommended Stack
- FastAPI for orchestration and internal APIs
- Postgres or Supabase for normalized profiles and events
- pgvector or a vector DB for embeddings
- queue workers for ingestion and enrichment
- an LLM for summarization and query interpretation
- a smaller scoring service for deterministic ranking features

## UX Inside Founder Mode
- single search box for natural-language hiring intent
- filter row for role, geography, seniority, platform, startup stage, and remote preference
- ranked results with:
  - summary
  - match score
  - credibility score
  - startup fit score
  - evidence snippets
  - outreach opener
- save, shortlist, and compare actions
- feedback controls like `good match`, `too senior`, `wrong skill`, `not startup fit`

## Practical MVP Roadmap
### Phase 1
- static candidate knowledge base or curated pilot dataset
- query parsing
- deterministic ranking
- LLM summaries and outreach generation
- shortlist UI inside Founder Mode

### Phase 2
- GitHub ingestion
- X ingestion
- personal website enrichment
- candidate deduping and embeddings

### Phase 3
- feedback-trained ranking
- auto-refresh candidate graph
- warm intro discovery and CRM sync

## Success Metrics
- time to first high-quality shortlist
- shortlist save rate
- outreach send rate
- reply rate
- founder-rated relevance
- eventual interview and hire conversion
