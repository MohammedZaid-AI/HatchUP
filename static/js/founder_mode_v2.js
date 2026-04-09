(function () {
    function byId(id) {
        return document.getElementById(id);
    }

    function buildHeaders() {
        return {
            "Content-Type": "application/json",
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {}),
        };
    }

    function renderInitialState(resultsEl, statusEl) {
        if (statusEl) {
            statusEl.textContent = "Type a query and search to see matching Talent Scout profiles.";
        }
        if (resultsEl) {
            resultsEl.innerHTML = `
                <div class="founder-empty-state">
                    <h4>Talent Scout is ready</h4>
                    <p>Search for engineers and operators by skill, role, or startup need.</p>
                </div>
            `;
        }
    }

    function renderLoadingState(resultsEl, statusEl, query) {
        if (statusEl) {
            statusEl.textContent = `Searching for matches related to "${query}"...`;
        }
        if (resultsEl) {
            resultsEl.innerHTML = `
                <div class="founder-loading-state">
                    <div class="spinner"></div>
                    <p>Talent Scout is ranking profiles for this founder brief.</p>
                </div>
            `;
        }
    }

    function renderEmptyState(resultsEl, statusEl, query) {
        if (statusEl) {
            statusEl.textContent = `No Talent Scout matches found for "${query}".`;
        }
        if (resultsEl) {
            resultsEl.innerHTML = `
                <div class="founder-empty-state">
                    <h4>No results found</h4>
                    <p>Try a broader search like "backend engineer", "growth marketer", or "AI product builder".</p>
                </div>
            `;
        }
    }

    function renderFailureState(resultsEl, statusEl, message) {
        if (statusEl) {
            statusEl.textContent = "Live Talent Scout search is unavailable right now.";
        }
        if (resultsEl) {
            resultsEl.innerHTML = `
                <div class="founder-empty-state">
                    <h4>Live search unavailable</h4>
                    <p>${message}</p>
                </div>
            `;
        }
    }

    function renderResults(resultsEl, statusEl, query, items) {
        if (statusEl) {
            statusEl.textContent = `Showing ${items.length} Talent Scout result${items.length === 1 ? "" : "s"} for "${query}".`;
        }
        resultsEl.innerHTML = items.map((candidate, index) => `
            <article class="founder-result-card">
                <div class="founder-result-top">
                    <div>
                        <div class="founder-rank-line">
                            <span class="founder-rank-badge">#${index + 1}</span>
                            <span class="founder-platform-pill">${candidate.primary_platform || candidate.source || "Web"}</span>
                        </div>
                        <h4>${candidate.name}</h4>
                        <p class="founder-role-line">${candidate.role} - ${candidate.location || "Remote-friendly"}</p>
                    </div>
                    <div class="founder-score-stack">
                        <strong>${candidate.match_score || candidate.score || 0}</strong>
                        <span>match</span>
                    </div>
                </div>

                <p class="founder-summary">${candidate.summary}</p>

                <div class="founder-tag-row">
                    ${(candidate.tags || []).map((tag) => `<span class="founder-tag">${tag}</span>`).join("")}
                </div>

                <div class="founder-evidence-block">
                    <p class="founder-evidence-title">Why matched</p>
                    <ul class="founder-list founder-tight-list">
                        <li>Role fit: ${candidate.role}</li>
                        <li>Source signal: ${candidate.primary_platform || candidate.source || "Web"}</li>
                        <li>Matched terms: ${(candidate.matchedTerms || []).join(", ") || "broad startup relevance"}</li>
                    </ul>
                </div>
            </article>
        `).join("");
    }

    function initializeFounderMode() {
        const inputEl = byId("founder-query-input");
        const searchButtonEl = byId("founder-query-button");
        const runButtonEl = byId("founder-run-scout-button");
        const resultsEl = byId("founder-results-list");
        const statusEl = byId("founder-search-status");
        const chipEls = document.querySelectorAll(".founder-chip-button");

        if (!inputEl || !searchButtonEl || !runButtonEl || !resultsEl || !statusEl || !window.TalentScout) {
            return;
        }

        function setBusy(isBusy) {
            inputEl.disabled = isBusy;
            searchButtonEl.disabled = isBusy;
            runButtonEl.disabled = isBusy;
        }

        function runSearch() {
            const query = inputEl.value.trim();
            if (!query) {
                renderInitialState(resultsEl, statusEl);
                return;
            }

            setBusy(true);
            renderLoadingState(resultsEl, statusEl, query);

            window.fetch("/api/founder/talent-scout/search", {
                method: "POST",
                headers: buildHeaders(),
                body: JSON.stringify({ query }),
            })
                .then(async (response) => {
                    if (!response.ok) {
                        throw new Error(await response.text());
                    }
                    return response.json();
                })
                .then((data) => {
                    const results = Array.isArray(data.candidates) ? data.candidates : [];
                    if (!results.length) {
                        renderEmptyState(resultsEl, statusEl, query);
                        return;
                    }
                    renderResults(resultsEl, statusEl, query, results);
                    if (statusEl) {
                        const source = data.data_source === "multi_source_live"
                            ? "Live GitHub + X + Kaggle + SerpAPI + Reddit"
                            : "Live sources unavailable";
                        statusEl.textContent = `Showing ${results.length} Talent Scout results for "${query}". Source: ${source}.`;
                    }
                })
                .catch((error) => {
                    renderFailureState(
                        resultsEl,
                        statusEl,
                        `The search request failed before live sources could return results. ${error && error.message ? error.message : ""}`.trim()
                    );
                })
                .finally(() => {
                    setBusy(false);
                });
        }

        chipEls.forEach((chipEl) => {
            chipEl.addEventListener("click", () => {
                inputEl.value = chipEl.getAttribute("data-founder-query") || "";
                runSearch();
            });
        });

        searchButtonEl.addEventListener("click", runSearch);
        runButtonEl.addEventListener("click", runSearch);
        inputEl.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                runSearch();
            }
        });

        renderInitialState(resultsEl, statusEl);
    }

    window.addEventListener("DOMContentLoaded", initializeFounderMode);
})();
