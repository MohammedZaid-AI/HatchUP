const ANALYSIS_WORKSPACE_KEY = 'hatchup_workspace_cache';
const LEGACY_ANALYSIS_KEY = 'hatchup_analysis';
const LEGACY_RESEARCH_KEY = 'hatchup_deep_research_history';
let hatchupWorkspace = null;

function persistWorkspace() {
    if (hatchupWorkspace) {
        localStorage.setItem(ANALYSIS_WORKSPACE_KEY, JSON.stringify(hatchupWorkspace));
    }
}

function getCachedWorkspace() {
    if (hatchupWorkspace) return hatchupWorkspace;
    const raw = localStorage.getItem(ANALYSIS_WORKSPACE_KEY);
    if (!raw) return null;
    try {
        hatchupWorkspace = JSON.parse(raw);
    } catch (error) {
        console.error('Invalid workspace cache', error);
        hatchupWorkspace = null;
    }
    return hatchupWorkspace;
}

function hasUsableActiveAnalysis(workspace) {
    if (!workspace || !workspace.active_analysis_id) return false;
    return !!workspace.active_analysis;
}

function upsertAnalysisListItem(workspace, analysisId, title) {
    if (!workspace) return;
    if (!Array.isArray(workspace.analyses)) workspace.analyses = [];
    const index = workspace.analyses.findIndex((item) => item.analysis_id === analysisId);
    const nextItem = { analysis_id: analysisId, title: title || 'Untitled Analysis' };
    if (index >= 0) {
        workspace.analyses[index] = { ...workspace.analyses[index], ...nextItem };
    } else {
        workspace.analyses.unshift(nextItem);
    }
}

function renderPastAnalyses() {
    const panel = document.getElementById('past-analyses-panel');
    const list = document.getElementById('past-analyses-list');
    const modeState = window.HatchupAppState || null;
    const modeLoading = modeState && modeState.isModeLoading ? modeState.isModeLoading() : false;
    const mode = modeState && modeState.getMode ? modeState.getMode() : 'vc';
    if (!panel || !list) return;
    if (modeLoading) {
        panel.style.display = 'none';
        return;
    }
    if (mode !== 'vc') {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = 'block';

    const workspace = getCachedWorkspace();
    const analyses = (workspace && workspace.analyses) || [];
    const activeId = workspace && workspace.active_analysis_id;
    list.innerHTML = '';

    if (!analyses.length) {
        const empty = document.createElement('div');
        empty.className = 'past-analysis-empty';
        empty.innerText = 'No analyses yet.';
        list.appendChild(empty);
        return;
    }

    analyses.forEach((item) => {
        const button = document.createElement('button');
        button.className = 'past-analysis-item';
        if (item.analysis_id === activeId) {
            button.classList.add('active');
        }
        const title = item.startup_name || item.title || 'Untitled Analysis';
        button.innerHTML = `<span class="past-analysis-title">${title}</span>`;
        button.addEventListener('click', () => window.switchActiveAnalysis(item.analysis_id));
        list.appendChild(button);
    });
}

window.refreshAnalysisWorkspace = async function () {
    const res = await fetch('/api/session/analyses', {
        headers: window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {},
        credentials: 'same-origin',
        cache: 'no-store'
    });
    if (res.status === 401) {
        window.location.href = '/';
        throw new Error('Authentication required');
    }
    if (!res.ok) throw new Error('Failed to load analyses');
    hatchupWorkspace = await res.json();
    persistWorkspace();
    renderPastAnalyses();
    return hatchupWorkspace;
};

window.ensureAnalysisWorkspace = async function ({ force = false } = {}) {
    const cached = getCachedWorkspace();
    if (!force && hasUsableActiveAnalysis(cached)) {
        renderPastAnalyses();
        return cached;
    }
    return window.refreshAnalysisWorkspace();
};

window.getAnalysisWorkspace = function () {
    return getCachedWorkspace();
};

window.getActiveAnalysisId = function () {
    const workspace = getCachedWorkspace();
    return workspace ? workspace.active_analysis_id : null;
};

window.getActiveAnalysis = function () {
    const workspace = getCachedWorkspace();
    if (!workspace) return null;
    return workspace.active_analysis || null;
};

window.setActiveAnalysisCache = function ({ analysisId, analysis, title } = {}) {
    if (!analysisId) return;
    const workspace = getCachedWorkspace() || { analyses: [] };
    workspace.active_analysis_id = analysisId;
    if (analysis) {
        workspace.active_analysis = analysis;
    } else if (!workspace.active_analysis) {
        workspace.active_analysis = {};
    }
    upsertAnalysisListItem(workspace, analysisId, title);
    hatchupWorkspace = workspace;
    persistWorkspace();
    renderPastAnalyses();
};

window.startNewAnalysis = async function () {
    try {
        const res = await fetch('/api/session/analysis/new', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
            },
            credentials: 'same-origin',
            cache: 'no-store'
        });
        if (!res.ok) {
            const text = await res.text();
            throw new Error(text || 'Failed to create new analysis');
        }

        const payload = await res.json();
        // Clear any legacy single-session caches so Research/Memo always reset with new analysis.
        localStorage.removeItem(LEGACY_ANALYSIS_KEY);
        localStorage.removeItem(LEGACY_RESEARCH_KEY);
        window.setActiveAnalysisCache({
            analysisId: payload.active_analysis_id,
            analysis: payload.analysis,
            title: 'Untitled Analysis'
        });
        window.location.href = '/vc/deck-analyzer?fresh=1';
    } catch (error) {
        console.error('New analysis failed', error);
        alert('Failed to start new analysis. Please try again.');
    }
};

window.switchActiveAnalysis = async function (analysisId) {
    if (!analysisId) return;
    const res = await fetch('/api/session/analysis/activate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
        },
        credentials: 'same-origin',
        cache: 'no-store',
        body: JSON.stringify({ analysis_id: analysisId })
    });
    if (!res.ok) {
        const text = await res.text();
        alert(`Failed to switch analysis: ${text}`);
        return;
    }
    const payload = await res.json();
    const startupName = payload.analysis && payload.analysis.deck ? payload.analysis.deck.startup_name : '';
    window.setActiveAnalysisCache({
        analysisId: payload.active_analysis_id,
        analysis: payload.analysis,
        title: startupName || 'Untitled Analysis'
    });
    window.location.reload();
};

window.addEventListener('DOMContentLoaded', async () => {
    const cached = getCachedWorkspace();
    renderPastAnalyses();
    if (window.HatchupAppState && window.HatchupAppState.subscribeMode) {
        window.HatchupAppState.subscribeMode(() => renderPastAnalyses());
    }
    if (hasUsableActiveAnalysis(cached)) return;
    try {
        await window.refreshAnalysisWorkspace();
    } catch (error) {
        console.error('Workspace bootstrap failed', error);
    }
});
