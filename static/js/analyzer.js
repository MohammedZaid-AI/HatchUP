const fileInput = document.getElementById('file-input');
const dropZone = document.getElementById('drop-zone');
const loadingOverlay = document.getElementById('loading-overlay');
const resultsContainer = document.getElementById('results-container');
const loadingText = document.getElementById('loading-text');

if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#4a6cfa';
    });
    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#cbd5e1';
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#cbd5e1';
        const files = e.dataTransfer.files;
        if (files.length) handleFile(files[0]);
    });
}

if (fileInput) {
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) handleFile(e.target.files[0]);
    });
}

window.addEventListener('DOMContentLoaded', async () => {
    try {
        await window.refreshAnalysisWorkspace();
    } catch (error) {
        console.error('Workspace refresh failed', error);
    }
    const active = window.getActiveAnalysis();
    if (active && active.deck) {
        if (dropZone) dropZone.style.display = 'none';
        renderResults({
            data: active.deck,
            memo: active.memo || {},
            summary: active.insights || {}
        });
    }
});

async function handleFile(file) {
    if (!file) return;
    if (dropZone) dropZone.style.display = 'none';
    if (loadingOverlay) loadingOverlay.style.display = 'block';

    try {
        const formData = new FormData();
        formData.append('file', file);

        if (loadingText) loadingText.innerText = 'Reading & Analyzing Pitch Deck...';
        const analyzeRes = await fetch('/api/analyze', {
            method: 'POST',
            headers: window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {},
            body: formData
        });
        if (!analyzeRes.ok) throw new Error(await analyzeRes.text());
        const analyzePayload = await analyzeRes.json();
        const deckData = analyzePayload.deck || analyzePayload;

        if (loadingText) loadingText.innerText = 'Drafting Investment Memo...';
        const memoRes = await fetch('/api/generate_memo', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
            },
            body: JSON.stringify(deckData)
        });
        if (!memoRes.ok) throw new Error(await memoRes.text());
        const memoData = await memoRes.json();

        await window.refreshAnalysisWorkspace();
        renderResults({
            data: deckData,
            memo: memoData.memo || {},
            summary: memoData.summary || {}
        });
    } catch (err) {
        console.error(err);
        alert('Analysis Failed: ' + err.message);
        window.location.reload();
    }
}

function getCurrentAnalysisState() {
    const active = window.getActiveAnalysis();
    if (!active || !active.deck) return null;
    return {
        data: active.deck,
        memo: active.memo || {},
        summary: active.insights || {}
    };
}

function renderResults(res) {
    if (loadingOverlay) loadingOverlay.style.display = 'none';
    if (resultsContainer) resultsContainer.style.display = 'block';

    const data = res.data || {};
    const summary = res.summary || {};
    const memo = res.memo || {};

    const sName = document.getElementById('startup-name');
    if (sName) sName.innerText = data.startup_name || 'Startup';
    const sStage = document.getElementById('funding-stage');
    if (sStage) sStage.innerText = data.funding_ask_stage || 'Unknown Stage';

    const verdict = document.getElementById('outlook-verdict');
    if (verdict) {
        verdict.innerText = summary.decision_outlook || 'Pending';
        verdict.className = 'verdict';
        const lower = (summary.decision_outlook || '').toLowerCase();
        if (lower.includes('positive')) verdict.style.color = 'green';
        else if (lower.includes('negative')) verdict.style.color = 'red';
        else verdict.style.color = 'gray';
    }

    const reasoning = document.getElementById('outlook-reasoning');
    if (reasoning) reasoning.innerText = summary.market_alignment_reasoning || 'Generate memo to see detailed reasoning.';

    const list = document.getElementById('summary-highlights');
    if (list) {
        list.innerHTML = '';
        (summary.summary_bullet_points || []).forEach((pt) => {
            const li = document.createElement('li');
            li.innerText = pt;
            list.appendChild(li);
        });
    }

    const setText = (id, txt) => {
        const el = document.getElementById(id);
        if (el) el.value = txt || '';
    };

    setText('data-problem', data.problem);
    setText('data-solution', data.solution);
    setText('data-product', data.product);
    setText('data-market', data.market_tam);
    setText('data-traction', data.traction_metrics);
    setText('data-team', data.team);

    const fillList = (id, items) => {
        const ul = document.getElementById(id);
        if (!ul) return;
        ul.innerHTML = '';
        (items || []).forEach((item) => {
            const li = document.createElement('li');
            li.innerText = item;
            ul.appendChild(li);
        });
    };
    fillList('list-red-flags', data.red_flags);
    fillList('list-weak-signals', data.weak_signals);
    fillList('list-missing', data.missing_sections);

    const memoDiv = document.getElementById('memo-content');
    if (memoDiv) {
        const formatField = (val) => {
            if (Array.isArray(val)) return '<ul>' + val.map((v) => `<li>${v}</li>`).join('') + '</ul>';
            return `<p>${val || 'Not generated yet.'}</p>`;
        };
        memoDiv.innerHTML = `
            <h3>Company Overview</h3>${formatField(memo.company_overview)}
            <h3>Problem & Solution Clarity</h3>${formatField(memo.problem_solution_clarity)}
            <h3>Market Opportunity</h3>${formatField(memo.market_opportunity)}
            <h3>Product Differentiation</h3>${formatField(memo.product_differentiation)}
            <h3>Traction</h3>${formatField(memo.traction_metrics_analysis)}
            <h3>Team</h3>${formatField(memo.team_assessment)}
            <h3>Risks</h3>${formatField(memo.risks_concerns)}
            <h3>Assessment</h3>${formatField(memo.neutral_assessment)}
        `;
    }

    setupTabs();
}

function setupTabs() {
    const buttons = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');
    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            buttons.forEach((b) => b.classList.remove('active'));
            contents.forEach((c) => {
                c.style.display = 'none';
                c.classList.remove('active');
            });
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            const target = document.getElementById(targetId);
            if (target) {
                target.style.display = 'block';
                target.classList.add('active');
            }
        });
    });
}

window.regenerateMemo = async function () {
    const state = getCurrentAnalysisState();
    if (!state) return alert('No analysis data available.');

    if (loadingOverlay) loadingOverlay.style.display = 'block';
    if (loadingText) loadingText.innerText = 'Regenerating Investment Memo from edits...';

    try {
        const getValue = (id) => {
            const el = document.getElementById(id);
            return el ? el.value : '';
        };
        const updatedData = {
            ...state.data,
            problem: getValue('data-problem'),
            solution: getValue('data-solution'),
            product: getValue('data-product'),
            market_tam: getValue('data-market'),
            traction_metrics: getValue('data-traction'),
            team: getValue('data-team')
        };

        const memoRes = await fetch('/api/generate_memo', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
            },
            body: JSON.stringify(updatedData)
        });
        if (!memoRes.ok) throw new Error(await memoRes.text());
        const memoData = await memoRes.json();

        await window.refreshAnalysisWorkspace();
        renderResults({
            data: updatedData,
            memo: memoData.memo,
            summary: memoData.summary
        });
        alert('Memo Regenerated!');
    } catch (err) {
        alert('Error regenerating: ' + err.message);
        if (loadingOverlay) loadingOverlay.style.display = 'none';
    }
};

window.downloadExcel = async function () {
    const state = getCurrentAnalysisState();
    if (!state) return alert('No data to download');
    const res = await fetch('/api/export/excel', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
        },
        body: JSON.stringify(state.data)
    });
    triggerDownload(res, `${state.data.startup_name || 'startup'}_data.xlsx`);
};

window.downloadMemoText = async function () {
    const state = getCurrentAnalysisState();
    if (!state) return alert('No data');
    const res = await fetch('/api/export/text_memo', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
        },
        body: JSON.stringify({ memo: state.memo, startup_name: state.data.startup_name || 'startup' })
    });
    triggerDownload(res, `${state.data.startup_name || 'startup'}_memo.txt`);
};

window.downloadMemoPDF = async function () {
    const state = getCurrentAnalysisState();
    if (!state) return alert('No data');
    const res = await fetch('/api/export/pdf_memo', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
        },
        body: JSON.stringify({ memo: state.memo, startup_name: state.data.startup_name || 'startup' })
    });
    triggerDownload(res, `${state.data.startup_name || 'startup'}_memo.pdf`);
};

async function triggerDownload(res, filename) {
    if (!res.ok) return alert('Download failed');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
