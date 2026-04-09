(function () {
    const MOCK_PROFILES = [
        {
            name: "Aarav Menon",
            role: "Backend Engineer",
            source: "GitHub",
            location: "Bengaluru / Remote",
            summary: "Built AI agent orchestration tools, Python backends, and internal developer systems for startup teams.",
            tags: ["backend", "python", "ai", "agents", "infra"],
        },
        {
            name: "Nisha Rao",
            role: "Growth Marketer",
            source: "Twitter",
            location: "Mumbai / Remote",
            summary: "Known for early-stage growth experiments, launch strategy, and founder-led distribution playbooks.",
            tags: ["growth", "marketing", "early-stage", "distribution", "launch"],
        },
        {
            name: "Sara Kim",
            role: "AI Product Engineer",
            source: "GitHub",
            location: "Singapore / Remote",
            summary: "Ships AI prototypes fast and bridges product thinking with LLM-powered workflows and agent UX.",
            tags: ["engineer", "ai", "agents", "llm", "product"],
        },
        {
            name: "Mateo Alvarez",
            role: "Creator Growth Operator",
            source: "Newsletter",
            location: "Remote",
            summary: "Builds audience growth loops for startups through content, creator partnerships, and launch sequencing.",
            tags: ["creator", "growth", "audience", "content", "distribution"],
        },
        {
            name: "Leah Okafor",
            role: "Product Marketer",
            source: "Personal Website",
            location: "London / Remote",
            summary: "Works with seed-stage startups on positioning, messaging, lifecycle strategy, and launch readiness.",
            tags: ["marketing", "positioning", "product", "startup", "lifecycle"],
        },
        {
            name: "Kian D'Souza",
            role: "Developer Tools Engineer",
            source: "GitHub",
            location: "Remote",
            summary: "Strong in APIs, platform tooling, and backend systems for product teams that move quickly.",
            tags: ["developer", "backend", "api", "platform", "golang"],
        },
    ];

    function tokenize(value) {
        return String(value || "")
            .toLowerCase()
            .match(/[a-z0-9\-\+]+/g) || [];
    }

    function scoreProfile(query, profile) {
        const queryTokens = tokenize(query);
        const profileText = [
            profile.name,
            profile.role,
            profile.source,
            profile.location,
            profile.summary,
            (profile.tags || []).join(" "),
        ].join(" ");
        const haystack = new Set(tokenize(profileText));
        const matches = queryTokens.filter((token) => haystack.has(token));
        const score = matches.length * 10 + ((profile.tags || []).some((tag) => queryTokens.includes(tag)) ? 8 : 0);
        return {
            ...profile,
            score,
            matchedTerms: Array.from(new Set(matches)).slice(0, 4),
        };
    }

    function searchProfiles(query) {
        const normalized = String(query || "").trim();
        if (!normalized) return [];
        return MOCK_PROFILES
            .map((profile) => scoreProfile(normalized, profile))
            .filter((profile) => profile.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 5);
    }

    window.TalentScout = {
        searchProfiles,
    };
})();
