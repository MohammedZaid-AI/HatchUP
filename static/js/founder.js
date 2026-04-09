const founderQueryInput = document.getElementById("founder-query-input");
const founderQueryButton = document.getElementById("founder-query-button");
const founderResultsList = document.getElementById("founder-results-list");
const founderSearchStatus = document.getElementById("founder-search-status");
const founderArchitecturePanel = document.getElementById("founder-architecture-panel");

function founderHeaders() {
    return {
        "Content-Type": "application/json",
        ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {}),
    };
}

function setFounderBusy(isBusy) {
    if (founderQueryInput) founderQueryInput.disabled = isBusy;
    if (founderQueryButton) founderQueryButton.disabled = isBusy;
}

function renderFounderResults(items) {
    if (!founderResultsList) return;
    if (!Array.isArray(items) || !items.length) {
        founderResultsList.innerHTML = `
            <div class="founder-empty-state">
                <h4>No strong matches found</h4>
                <p>Try broadening the role, removing one constraint, or searching by outcomes instead of titles.</p>
            </div>
        `;
        return;
    }

    founderResultsList.innerHTML = items.map((candidate, index) => {
        const tags = Array.isArray(candidate.tags) ? candidate.tags : [];
        const reasons = Array.isArray(candidate.why_matched) ? candidate.why_matched : [];
        return `
            <article class="founder-result-card">
                <div class="founder-result-top">
                    <div>
                        <div class="founder-rank-line">
                            <span class="founder-rank-badge">#${index + 1}</span>
                            <span class="founder-platform-pill">${candidate.primary_platform || "Mixed"}</span>
                        </div>
                        <h4>${candidate.name || "Unknown Candidate"}</h4>
                        <p class="founder-role-line">${candidate.role || ""} · ${candidate.location || "Remote-friendly"}</p>
                    </div>
                    <div class="founder-score-stack">
                        <strong>${candidate.match_score || 0}</strong>
                        <span>match</span>
                    </div>
                </div>

                <p class="founder-summary">${candidate.summary || ""}</p>

                <div class="founder-score-row">
                    <div class="founder-score-pill">Credibility ${candidate.credibility_score || 0}</div>
                    <div class="founder-score-pill">Startup Fit ${candidate.startup_fit_score || 0}</div>
                </div>

                <div class="founder-tag-row">
                    ${tags.map((tag) => `<span class="founder-tag">${tag}</span>`).join("")}
                </div>

                <div class="founder-evidence-block">
                    <p class="founder-evidence-title">Why matched</p>
                    <ul class="founder-list founder-tight-list">
                        ${reasons.map((reason) => `<li>${reason}</li>`).join("")}
                    </ul>
                </div>

                <div class="founder-outreach-block">
                    <p class="founder-evidence-title">Suggested outreach</p>
                    <p>${candidate.outreach_message || ""}</p>
                </div>
            </article>
        `;
    }).join("");
}

function renderFounderArchitecture(data) {
    if (!founderArchitecturePanel) return;
    const architecture = data && data.architecture ? data.architecture : {};
    const signals = Array.isArray(architecture.signals) ? architecture.signals : [];
    const sources = Array.isArray(architecture.data_sources) ? architecture.data_sources : [];
    const stages = Array.isArray(architecture.pipeline) ? architecture.pipeline : [];
    const githubWarning = data && data.github_warning ? String(data.github_warning) : "";
    const dataSource = data && data.data_source ? String(data.data_source) : "unknown";

    founderArchitecturePanel.innerHTML = `
        <div class="founder-architecture-group">
            <h4>Current Source</h4>
            <p>${dataSource === "github_live" ? "Live GitHub retrieval is active for this search." : "Using curated fallback data for this search."}</p>
            ${githubWarning ? `<p class="founder-warning-text">GitHub note: ${githubWarning}</p>` : ""}
        </div>
        <div class="founder-architecture-group">
            <h4>Scoring Strategy</h4>
            <p>${architecture.scoring_summary || ""}</p>
        </div>
        <div class="founder-architecture-group">
            <h4>Signals Used</h4>
            <ul class="founder-list founder-tight-list">
                ${signals.map((item) => `<li>${item}</li>`).join("")}
            </ul>
        </div>
        <div class="founder-architecture-group">
            <h4>Data Sources</h4>
            <ul class="founder-list founder-tight-list">
                ${sources.map((item) => `<li>${item}</li>`).join("")}
            </ul>
        </div>
        <div class="founder-architecture-group">
            <h4>MVP Pipeline</h4>
            <ol class="founder-list founder-tight-list founder-ordered-list">
                ${stages.map((item) => `<li>${item}</li>`).join("")}
            </ol>
        </div>
    `;
}

window.setFounderQuery = function (query) {
    if (!founderQueryInput) return;
    founderQueryInput.value = query;
    founderQueryInput.focus();
};

window.runFounderSearch = async function () {
    if (!founderQueryInput) return;
    const query = founderQueryInput.value.trim();
    if (!query) return;

    setFounderBusy(true);
    if (founderSearchStatus) {
        founderSearchStatus.textContent = "Scoring public proof-of-work, relevance, and startup fit...";
    }
    if (founderResultsList) {
        founderResultsList.innerHTML = `
            <div class="founder-loading-state">
                <div class="spinner"></div>
                <p>Scanning signals and ranking candidates for this founder brief.</p>
            </div>
        `;
    }

    try {
        const res = await fetch("/api/founder/talent-scout/search", {
            method: "POST",
            headers: founderHeaders(),
            body: JSON.stringify({ query }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        renderFounderResults(data.candidates || []);
        renderFounderArchitecture(data);
        if (founderSearchStatus) {
            const sourceLabel = data && data.data_source === "github_live" ? "Live GitHub" : "Curated fallback";
            founderSearchStatus.textContent = `${data.search_summary || "Ranked candidates generated."} Source: ${sourceLabel}.`;
        }
    } catch (error) {
        if (founderResultsList) {
            founderResultsList.innerHTML = `
                <div class="founder-empty-state">
                    <h4>Search failed</h4>
                    <p>${error.message}</p>
                </div>
            `;
        }
        if (founderSearchStatus) {
            founderSearchStatus.textContent = "Unable to complete the scout search.";
        }
    } finally {
        setFounderBusy(false);
    }
};
