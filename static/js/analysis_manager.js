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

function renderPastAnalyses() {
    const panel = document.getElementById('past-analyses-panel');
    const list = document.getElementById('past-analyses-list');
    const modeToggle = document.getElementById('mode-toggle');
    const mode = modeToggle ? (modeToggle.dataset.activeMode || 'vc') : (localStorage.getItem('hatchup_mode') || 'vc');
    if (!panel || !list) return;
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
    if (!res.ok) throw new Error('Failed to load analyses');
    hatchupWorkspace = await res.json();
    persistWorkspace();
    renderPastAnalyses();
    return hatchupWorkspace;
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
        hatchupWorkspace = {
            active_analysis_id: payload.active_analysis_id,
            active_analysis: payload.analysis,
            analyses: []
        };
        persistWorkspace();
        renderPastAnalyses();

        await window.refreshAnalysisWorkspace();
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
    await window.refreshAnalysisWorkspace();
    window.location.reload();
};

window.addEventListener('DOMContentLoaded', async () => {
    try {
        await window.refreshAnalysisWorkspace();
    } catch (error) {
        console.error('Workspace bootstrap failed', error);
        renderPastAnalyses();
    }
});
