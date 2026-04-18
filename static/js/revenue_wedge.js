(function () {
    const state = {
        workspace: null,
        loading: false,
        savingInput: false,
        running: false,
        loggingRunId: "",
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function buildHeaders() {
        return {
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {}),
        };
    }

    function buildJsonHeaders() {
        return {
            "Content-Type": "application/json",
            ...buildHeaders(),
        };
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function setFeedback(message, tone) {
        const feedbackEl = byId("revenue-input-feedback");
        if (!feedbackEl) return;
        feedbackEl.textContent = message || "";
        feedbackEl.dataset.tone = tone || "neutral";
    }

    function setInputFormBusy(isBusy) {
        state.savingInput = isBusy;
        const form = byId("revenue-input-form");
        if (!form) return;
        Array.from(form.elements).forEach((element) => {
            element.disabled = isBusy;
        });
    }

    function setRunBusy(isBusy) {
        state.running = isBusy;
        const button = byId("revenue-run-button");
        if (!button) return;
        const inputCount = ((state.workspace && state.workspace.inputs) || []).length;
        button.disabled = isBusy || inputCount === 0;
        button.textContent = isBusy ? "Generating..." : "Generate Weekly Decision";
    }

    function renderInputs() {
        const container = byId("revenue-inputs-list");
        const runButton = byId("revenue-run-button");
        const metaEl = byId("revenue-inputs-meta");
        if (!container) return;
        const inputs = (state.workspace && state.workspace.inputs) || [];
        if (runButton && !state.running) {
            runButton.disabled = inputs.length === 0;
        }
        if (metaEl) {
            metaEl.textContent = inputs.length === 0
                ? "No saved inputs yet."
                : `${inputs.length} founder input${inputs.length === 1 ? "" : "s"} saved to this workspace.`;
        }
        if (!inputs.length) {
            container.innerHTML = `
                <div class="founder-empty-state">
                    <h4>No founder inputs yet</h4>
                    <p>Add at least one sales, customer, or GTM input to run the engine.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = inputs.map((item) => `
            <article class="revenue-input-item">
                <div class="revenue-input-item-top">
                    <div>
                        <div class="revenue-input-meta-row">
                            <span class="revenue-input-tag">${escapeHtml(item.tag)}</span>
                            <span class="revenue-input-source">${escapeHtml(item.source_type)}</span>
                        </div>
                        <h4>${escapeHtml(item.title)}</h4>
                        <p>${escapeHtml(item.excerpt)}</p>
                    </div>
                    <button class="btn-reset revenue-delete-btn" type="button" data-input-id="${escapeHtml(item.input_id)}">Remove</button>
                </div>
            </article>
        `).join("");
    }

    function renderOutput() {
        const outputEl = byId("revenue-output-state");
        const metaEl = byId("revenue-run-meta");
        const sourceEl = byId("revenue-source-meta");
        const confidenceEl = byId("revenue-confidence-pill");
        if (!outputEl || !metaEl || !confidenceEl || !sourceEl) return;

        const latestRun = state.workspace && state.workspace.latest_run;
        if (!latestRun) {
            metaEl.textContent = "Run the engine to get one operator-grade recommendation.";
            sourceEl.textContent = "";
            confidenceEl.hidden = true;
            outputEl.innerHTML = `
                <div class="founder-empty-state">
                    <h4>One clear wedge, not a dashboard</h4>
                    <p>The output will force one ICP, one core problem, one decision, and ready-to-use execution assets.</p>
                </div>
            `;
            return;
        }

        const signalQuality = latestRun.signal_quality || {};
        const generationSource = latestRun.generation_source || "unknown";
        const sourceLabel = generationSource === "llm_decision"
            ? "Generated from LLM extraction + decision synthesis."
            : generationSource === "llm_extraction"
                ? "Generated from LLM extraction."
                : "Generated from fallback heuristics.";

        const brief = latestRun.decision_brief;
        metaEl.textContent = `Latest run: ${new Date(latestRun.created_at).toLocaleString()}`;
        sourceEl.textContent = `${sourceLabel} Signal quality ${signalQuality.score || "--"}.`;
        confidenceEl.hidden = false;
        confidenceEl.textContent = signalQuality.insufficient_signal
            ? `Low Signal ${escapeHtml(signalQuality.score || "--")}`
            : `Confidence ${escapeHtml((brief && brief.confidence_score) || signalQuality.score || "--")}`;

        if (signalQuality.insufficient_signal || !brief) {
            outputEl.innerHTML = `
                <div class="founder-empty-state revenue-low-signal-state">
                    <h4>You're one step away from your first decision</h4>
                    <p>${escapeHtml(signalQuality.reasoning || "Add one more strong commercial pattern and the engine can force a weekly decision.")}</p>
                    <p class="revenue-inline-label">Progress status</p>
                    <ul class="founder-list founder-tight-list">
                        ${((signalQuality.progress_status || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
                    </ul>
                    <p class="revenue-inline-label">What's missing</p>
                    <ul class="founder-list founder-tight-list">
                        ${((signalQuality.missing_pieces || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
                    </ul>
                    <p class="revenue-inline-label">To unlock your first decision</p>
                    <ul class="founder-list founder-tight-list">
                        ${((signalQuality.minimum_requirements || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
                    </ul>
                    <p class="revenue-inline-label">Copy-paste template</p>
                    <div class="founder-list founder-tight-list">
                        ${((signalQuality.copy_paste_templates || []).map((item) => `<pre class="revenue-template-block">${escapeHtml(item)}</pre>`).join(""))}
                    </div>
                    <p class="revenue-inline-label">Good input examples</p>
                    <ul class="founder-list founder-tight-list">
                        ${((signalQuality.good_input_examples || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
                    </ul>
                    <p class="revenue-inline-label">Once you add that, you'll get</p>
                    <ul class="founder-list founder-tight-list">
                        ${((signalQuality.what_happens_next || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
                    </ul>
                </div>
            `;
            return;
        }

        outputEl.innerHTML = `
            <section class="revenue-brief-section">
                <p class="revenue-brief-kicker">Recommended ICP</p>
                <h2>${escapeHtml(brief.recommended_icp)}</h2>
                <p class="revenue-brief-support">${escapeHtml(brief.confidence_reasoning)}</p>
            </section>

            <section class="revenue-brief-grid">
                <article class="revenue-brief-card">
                    <h3>Core Problem</h3>
                    <p>${escapeHtml(brief.core_problem || "")}</p>
                </article>
                <article class="revenue-brief-card">
                    <h3>Decision</h3>
                    <p>${escapeHtml(brief.decision || "")}</p>
                </article>
            </section>

            <section class="revenue-brief-card">
                <h3>This Week Execution</h3>
                <ul class="founder-list founder-tight-list">
                    ${(brief.this_week_execution || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
            </section>

            <section class="revenue-brief-card">
                <h3>Decision Pressure</h3>
                <p>${escapeHtml(brief.contradiction_resolution || "")}</p>
            </section>

            <section class="revenue-brief-card">
                <h3>Run-to-Run Intelligence</h3>
                <p class="revenue-inline-label">What changed</p>
                <ul class="founder-list founder-tight-list">
                    ${(((brief.run_to_run_intelligence || {}).what_changed) || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>No previous run to compare yet.</li>"}
                </ul>
                <p class="revenue-inline-label">What improved</p>
                <ul class="founder-list founder-tight-list">
                    ${(((brief.run_to_run_intelligence || {}).what_improved) || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>No improvement signal logged yet.</li>"}
                </ul>
                <p class="revenue-inline-label">What failed</p>
                <ul class="founder-list founder-tight-list">
                    ${(((brief.run_to_run_intelligence || {}).what_failed) || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>No failure pattern logged yet.</li>"}
                </ul>
                <p class="revenue-inline-label">Next move</p>
                <p>${escapeHtml(((brief.run_to_run_intelligence || {}).next_move) || "")}</p>
            </section>

            <section class="revenue-brief-card">
                <h3>Evidence</h3>
                <ul class="founder-list founder-tight-list">
                    ${(brief.evidence || []).map((item) => `
                        <li>
                            <strong>"${escapeHtml(item.quote || "")}"</strong><br />
                            <span>${escapeHtml(item.why_it_matters || "")}</span>
                        </li>
                    `).join("")}
                </ul>
                <p class="revenue-inline-label">Run-to-run comparison</p>
                <p>${escapeHtml(brief.comparison_to_last_run || "No comparison available yet.")}</p>
            </section>

            <section class="revenue-brief-card">
                <h3>Assets</h3>
                <details class="revenue-asset-panel" open>
                    <summary>Landing page copy</summary>
                    <pre>${escapeHtml((brief.assets || {}).landing_page_headline || "")}

${escapeHtml((brief.assets || {}).landing_page_subheadline || "")}

${escapeHtml((brief.assets || {}).landing_page_cta || "")}</pre>
                </details>
                <details class="revenue-asset-panel">
                    <summary>Outbound message</summary>
                    <pre>${escapeHtml((brief.assets || {}).outbound_message || "")}</pre>
                </details>
                <details class="revenue-asset-panel">
                    <summary>Sales talk track</summary>
                    <ul class="founder-list founder-tight-list">
                        ${(((brief.assets || {}).sales_talk_track) || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                    </ul>
                </details>
            </section>

            ${(((brief.how_to_use_hatchup) || []).length ? `
            <section class="revenue-brief-card">
                <h3>How to use HatchUp for this</h3>
                <ul class="founder-list founder-tight-list">
                    ${(brief.how_to_use_hatchup || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
            </section>
            ` : "")}
        `;
    }

    function renderRuns() {
        const runsEl = byId("revenue-runs-list");
        if (!runsEl) return;
        const runs = (state.workspace && state.workspace.runs) || [];
        if (!runs.length) {
            runsEl.innerHTML = `<p class="founder-muted">No runs yet.</p>`;
            return;
        }

        runsEl.innerHTML = runs.map((run) => {
            const brief = run.decision_brief || {};
            const resultLog = run.outcome_log || {};
            const signalQuality = run.signal_quality || {};
            const logging = state.loggingRunId === run.run_id;
            const canLogResult = !signalQuality.insufficient_signal;
            return `
                <article class="revenue-run-item">
                    <div class="revenue-run-head">
                        <div>
                            <strong>${escapeHtml(brief.recommended_icp || "Signal check only")}</strong>
                            <p>${escapeHtml(new Date(run.created_at).toLocaleString())}</p>
                        </div>
                        <span class="revenue-run-confidence">${escapeHtml(signalQuality.insufficient_signal ? `Low ${signalQuality.score || "--"}` : (brief.confidence_score || signalQuality.score || "--"))}</span>
                    </div>
                    <p class="revenue-run-summary">${escapeHtml(signalQuality.insufficient_signal ? (signalQuality.reasoning || "Not enough signal yet.") : (brief.decision || ((brief.this_week_execution || [])[0] || "No action recorded.")))}</p>
                    ${canLogResult ? `
                    <form class="revenue-run-result-form" data-run-id="${escapeHtml(run.run_id)}">
                        <label>Experiment result</label>
                        <select name="outcome" class="chat-input revenue-mini-input">
                            <option value="improved" ${resultLog.outcome === "improved" ? "selected" : ""}>improved</option>
                            <option value="flat" ${resultLog.outcome === "flat" ? "selected" : ""}>flat</option>
                            <option value="worse" ${resultLog.outcome === "worse" ? "selected" : ""}>worse</option>
                        </select>
                        <input name="replies" class="chat-input revenue-mini-input" type="number" min="0" placeholder="Replies" value="${escapeHtml(resultLog.replies || 0)}" />
                        <input name="calls_booked" class="chat-input revenue-mini-input" type="number" min="0" placeholder="Calls booked" value="${escapeHtml(resultLog.calls_booked || 0)}" />
                        <input name="deals_closed" class="chat-input revenue-mini-input" type="number" min="0" placeholder="Deals closed" value="${escapeHtml(resultLog.deals_closed || 0)}" />
                        <input name="top_objection" class="chat-input revenue-mini-input" type="text" placeholder="Top objection" value="${escapeHtml(resultLog.top_objection || "")}" />
                        <input name="metric_delta" class="chat-input revenue-mini-input" type="text" placeholder="e.g. reply rate +18%" value="${escapeHtml(resultLog.metric_delta || "")}" />
                        <textarea name="notes" class="data-input revenue-run-notes" placeholder="What actually happened?">${escapeHtml(resultLog.notes || "")}</textarea>
                        <button class="btn" type="submit" ${logging ? "disabled" : ""}>${logging ? "Saving..." : "Log Result"}</button>
                    </form>
                    ` : `<p class="revenue-inline-label">No experiment logging for this run because the engine intentionally stopped at signal validation.</p>`}
                </article>
            `;
        }).join("");
    }

    function renderWorkspace() {
        renderInputs();
        renderOutput();
        renderRuns();
    }

    async function fetchWorkspace() {
        const response = await fetch("/api/founder/revenue-wedge/workspace", {
            method: "GET",
            headers: buildHeaders(),
            credentials: "same-origin",
            cache: "no-store",
        });
        if (!response.ok) throw new Error(await response.text());
        state.workspace = await response.json();
        renderWorkspace();
    }

    async function handleInputSubmit(event) {
        event.preventDefault();
        if (state.savingInput) return;
        const form = event.currentTarget;
        const fileInput = byId("revenue-input-file");
        const textInput = byId("revenue-input-text");
        if (!form || (!fileInput.files.length && !(textInput.value || "").trim())) {
            setFeedback("Upload a supported file or paste founder notes first.", "error");
            return;
        }

        const formData = new FormData(form);
        setInputFormBusy(true);
        setFeedback("Saving input...", "neutral");
        try {
            const response = await fetch("/api/founder/revenue-wedge/input", {
                method: "POST",
                headers: buildHeaders(),
                credentials: "same-origin",
                body: formData,
            });
            if (!response.ok) {
                let message = await response.text();
                try {
                    const payload = JSON.parse(message);
                    if (Array.isArray(payload.detail)) {
                        message = payload.detail.map((item) => item.msg).join(", ");
                    } else {
                        message = payload.detail || message;
                    }
                } catch (_) {
                    // Keep plain text fallback.
                }
                throw new Error(message);
            }
            state.workspace = await response.json();
            form.reset();
            setFeedback("Input added to the founder workspace.", "success");
            renderWorkspace();
        } catch (error) {
            setFeedback(error.message || "Failed to save founder input.", "error");
        } finally {
            setInputFormBusy(false);
        }
    }

    async function handleInputDelete(event) {
        const button = event.target.closest("[data-input-id]");
        if (!button) return;
        const inputId = button.getAttribute("data-input-id");
        if (!inputId) return;
        button.disabled = true;
        try {
            const response = await fetch(`/api/founder/revenue-wedge/input/${encodeURIComponent(inputId)}`, {
                method: "DELETE",
                headers: buildHeaders(),
                credentials: "same-origin",
            });
            if (!response.ok) throw new Error(await response.text());
            state.workspace = await response.json();
            renderWorkspace();
        } catch (error) {
            setFeedback(error.message || "Failed to remove founder input.", "error");
        } finally {
            button.disabled = false;
        }
    }

    async function handleRun() {
        if (state.running) return;
        const inputCount = ((state.workspace && state.workspace.inputs) || []).length;
        if (inputCount === 0) {
            setFeedback("Add and save at least one founder input before generating a decision brief.", "error");
            return;
        }
        setRunBusy(true);
        setFeedback("Generating your weekly decision brief...", "neutral");
        try {
            const response = await fetch("/api/founder/revenue-wedge/run", {
                method: "POST",
                headers: buildJsonHeaders(),
                credentials: "same-origin",
                body: JSON.stringify({}),
            });
            if (!response.ok) {
                let message = await response.text();
                try {
                    const payload = JSON.parse(message);
                    message = payload.detail || message;
                } catch (_) {
                    // Keep plain text fallback.
                }
                throw new Error(message);
            }
            state.workspace = await response.json();
            setFeedback("Weekly decision brief generated.", "success");
            renderWorkspace();
        } catch (error) {
            setFeedback(error.message || "Revenue Wedge Engine failed.", "error");
        } finally {
            setRunBusy(false);
        }
    }

    async function handleRunResultSubmit(event) {
        const form = event.target.closest(".revenue-run-result-form");
        if (!form) return;
        event.preventDefault();
        const runId = form.getAttribute("data-run-id");
        if (!runId) return;

        state.loggingRunId = runId;
        renderRuns();
        try {
            const payload = {
                outcome: form.outcome.value,
                replies: Number(form.replies.value || 0),
                calls_booked: Number(form.calls_booked.value || 0),
                deals_closed: Number(form.deals_closed.value || 0),
                top_objection: form.top_objection.value,
                metric_delta: form.metric_delta.value,
                notes: form.notes.value,
            };
            const response = await fetch(`/api/founder/revenue-wedge/run/${encodeURIComponent(runId)}/result`, {
                method: "POST",
                headers: buildJsonHeaders(),
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error(await response.text());
            state.workspace = await response.json();
            state.loggingRunId = "";
            setFeedback("Experiment result logged.", "success");
            renderWorkspace();
        } catch (error) {
            setFeedback(error.message || "Failed to log experiment result.", "error");
            state.loggingRunId = "";
            renderRuns();
            return;
        }
    }

    function bindEvents() {
        const form = byId("revenue-input-form");
        const runButton = byId("revenue-run-button");
        const inputsList = byId("revenue-inputs-list");
        const runsList = byId("revenue-runs-list");
        if (form) form.addEventListener("submit", handleInputSubmit);
        if (runButton) runButton.addEventListener("click", handleRun);
        if (inputsList) inputsList.addEventListener("click", handleInputDelete);
        if (runsList) runsList.addEventListener("submit", handleRunResultSubmit);
    }

    window.addEventListener("DOMContentLoaded", () => {
        bindEvents();
        setRunBusy(false);
        void fetchWorkspace().catch((error) => {
            setFeedback(error.message || "Failed to load revenue wedge workspace.", "error");
        });
    });
})();
