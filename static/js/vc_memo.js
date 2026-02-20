const MEMO_STORAGE_KEY = 'hatchup_analysis';
let memoState = null;

window.addEventListener('DOMContentLoaded', () => {
    const stateStr = localStorage.getItem(MEMO_STORAGE_KEY);
    if (!stateStr) {
        showMemoEmptyState();
        return;
    }

    try {
        memoState = JSON.parse(stateStr);
    } catch (error) {
        console.error('Invalid memo state', error);
        showMemoEmptyState();
        return;
    }

    if (!memoState || !memoState.data) {
        showMemoEmptyState();
        return;
    }

    showMemoEditor();
    hydrateFields(memoState.data);
    renderMemo(memoState.memo);
});

function showMemoEmptyState() {
    const emptyState = document.getElementById('memo-empty-state');
    const editor = document.getElementById('memo-editor');
    if (emptyState) emptyState.style.display = 'block';
    if (editor) editor.style.display = 'none';
}

function showMemoEditor() {
    const emptyState = document.getElementById('memo-empty-state');
    const editor = document.getElementById('memo-editor');
    if (emptyState) emptyState.style.display = 'none';
    if (editor) editor.style.display = 'block';
}

function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value || '';
}

function hydrateFields(data) {
    const startupName = document.getElementById('memo-startup-name');
    const stage = document.getElementById('memo-funding-stage');

    if (startupName) startupName.innerText = data.startup_name || 'Startup';
    if (stage) stage.innerText = data.funding_ask_stage || 'Unknown Stage';

    setValue('memo-problem', data.problem);
    setValue('memo-solution', data.solution);
    setValue('memo-product', data.product);
    setValue('memo-market', data.market_tam);
    setValue('memo-traction', data.traction_metrics);
    setValue('memo-team', data.team);
}

function readUpdatedData() {
    return {
        ...memoState.data,
        problem: document.getElementById('memo-problem').value,
        solution: document.getElementById('memo-solution').value,
        product: document.getElementById('memo-product').value,
        market_tam: document.getElementById('memo-market').value,
        traction_metrics: document.getElementById('memo-traction').value,
        team: document.getElementById('memo-team').value
    };
}

window.regenerateManualMemo = async function () {
    if (!memoState || !memoState.data) {
        showMemoEmptyState();
        return;
    }

    try {
        const updatedData = readUpdatedData();
        const response = await fetch('/api/generate_memo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedData)
        });

        if (!response.ok) throw new Error(await response.text());
        const memoData = await response.json();

        memoState = {
            data: updatedData,
            memo: memoData.memo,
            summary: memoData.summary
        };

        localStorage.setItem(MEMO_STORAGE_KEY, JSON.stringify(memoState));
        renderMemo(memoState.memo);
        alert('Memo regenerated successfully.');
    } catch (error) {
        alert('Failed to regenerate memo: ' + error.message);
    }
};

function renderMemo(memo) {
    const memoDiv = document.getElementById('manual-memo-content');
    if (!memoDiv) return;
    if (!memo) {
        memoDiv.innerHTML = '<p>No memo generated yet.</p>';
        return;
    }

    const formatField = (value) => {
        if (Array.isArray(value)) {
            return '<ul>' + value.map((item) => `<li>${item}</li>`).join('') + '</ul>';
        }
        return `<p>${value || ''}</p>`;
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
};

window.downloadMemoText = async function () {
    if (!memoState || !memoState.memo) return alert('No memo data available.');
    const res = await fetch('/api/export/text_memo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memo: memoState.memo, startup_name: memoState.data.startup_name })
    });
    triggerDownload(res, `${memoState.data.startup_name}_memo.txt`);
};

window.downloadMemoPDF = async function () {
    if (!memoState || !memoState.memo) return alert('No memo data available.');
    const res = await fetch('/api/export/pdf_memo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memo: memoState.memo, startup_name: memoState.data.startup_name })
    });
    triggerDownload(res, `${memoState.data.startup_name}_memo.pdf`);
};

async function triggerDownload(response, filename) {
    if (!response.ok) return alert('Download failed.');
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
