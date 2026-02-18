const fileInput = document.getElementById('file-input');
const dropZone = document.getElementById('drop-zone');
const loadingOverlay = document.getElementById('loading-overlay');
const uploadContainer = document.getElementById('upload-container');
const resultsContainer = document.getElementById('results-container');
const loadingText = document.getElementById('loading-text');

// Drag & Drop Handling
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

// Check for existing data on load
// Check for existing data on load
window.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem('hatchup_analysis');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            if (data && data.data) {
                // Determine if we should show results
                // Hide drop zone, show results
                document.getElementById('drop-zone').style.display = 'none';
                renderResults(data);
            }
        } catch (e) {
            console.error("Error loading saved analysis", e);
        }
    }
});

function resetAnalysis() {
    if (confirm("Start a new analysis? This will clear current data.")) {
        localStorage.removeItem('hatchup_analysis');
        // Also clear chat histories as they are related to this startup?
        // User asked to preserve chat context, but if we start *new* analysis, maybe we should clear chat?
        // Usually "New Analysis" implies fresh start. Let's clear deep research context at least since it depends on the deck.
        // HatchUp Chat (general) can stay.
        localStorage.removeItem('hatchup_deep_research_history');
        location.reload();
    }
}

async function handleFile(file) {
    if (!file) return;

    // UI Update
    document.getElementById('drop-zone').style.display = 'none';
    loadingOverlay.style.display = 'block';

    try {
        const formData = new FormData();
        formData.append('file', file);

        // 1. Analyze
        loadingText.innerText = "Reading & Analyzing Pitch Deck...";
        const analyzeRes = await fetch('/api/analyze', { method: 'POST', body: formData });

        if (!analyzeRes.ok) throw new Error(await analyzeRes.text());
        const deckData = await analyzeRes.json();

        // 2. Generate Memo
        loadingText.innerText = "Drafting Investment Memo...";
        const memoRes = await fetch('/api/generate_memo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(deckData)
        });

        if (!memoRes.ok) throw new Error(await memoRes.text());
        const memoData = await memoRes.json(); // {memo, summary}

        const fullData = {
            data: deckData,
            memo: memoData.memo,
            summary: memoData.summary
        };

        localStorage.setItem('hatchup_analysis', JSON.stringify(fullData));
        renderResults(fullData);

    } catch (err) {
        console.error(err);
        alert("Analysis Failed: " + err.message);
        location.reload();
    }
}

function renderResults(res) {
    loadingOverlay.style.display = 'none';
    resultsContainer.style.display = 'block';

    const data = res.data;
    const memo = res.memo;
    const summary = res.summary;

    // Header
    const sName = document.getElementById('startup-name');
    if (sName) sName.innerText = data.startup_name;

    const sStage = document.getElementById('funding-stage');
    if (sStage) sStage.innerText = data.funding_ask_stage || "Unknown Stage";

    // Summary Tab
    const verdict = document.getElementById('outlook-verdict');
    if (verdict) {
        verdict.innerText = summary.decision_outlook;
        verdict.className = 'verdict'; // Reset
        const lower = summary.decision_outlook.toLowerCase();
        if (lower.includes('positive')) verdict.style.color = 'green';
        else if (lower.includes('negative')) verdict.style.color = 'red';
        else verdict.style.color = 'gray';
    }

    const reasoning = document.getElementById('outlook-reasoning');
    if (reasoning) reasoning.innerText = summary.market_alignment_reasoning;

    const list = document.getElementById('summary-highlights');
    if (list) {
        list.innerHTML = "";
        summary.summary_bullet_points.forEach(pt => {
            const li = document.createElement('li');
            li.innerText = pt;
            list.appendChild(li);
        });
    }

    // Data Tab - UPDATED to use .value for Textarea
    const setText = (id, txt) => {
        const el = document.getElementById(id);
        if (el) el.value = txt || ""; // Use value for textarea
    };

    setText('data-problem', data.problem);
    setText('data-solution', data.solution);
    setText('data-product', data.product);
    setText('data-market', data.market_tam);
    setText('data-traction', data.traction_metrics);
    setText('data-team', data.team);

    // Risks Tab
    const fillList = (id, items) => {
        const ul = document.getElementById(id);
        if (!ul) return;
        ul.innerHTML = "";
        (items || []).forEach(i => {
            const li = document.createElement('li');
            li.innerText = i;
            ul.appendChild(li);
        });
    };
    fillList('list-red-flags', data.red_flags);
    fillList('list-weak-signals', data.weak_signals);
    fillList('list-missing', data.missing_sections);

    // Memo Tab
    const memoDiv = document.getElementById('memo-content');
    if (memoDiv) {
        const formatField = (val) => {
            if (Array.isArray(val)) return '<ul>' + val.map(v => `<li>${v}</li>`).join('') + '</ul>';
            return `<p>${val}</p>`;
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

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            contents.forEach(c => c.style.display = 'none');

            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            document.getElementById(targetId).style.display = 'block';
        });
    });
}

// NEW: Regenerate Memo from Edited Data
async function regenerateMemo() {
    const state = JSON.parse(localStorage.getItem('hatchup_analysis'));
    if (!state) return alert("No analysis data available.");

    loadingOverlay.style.display = 'block';
    loadingText.innerText = "Regenerating Investment Memo from edits...";

    try {
        // Gather data from textareas
        const getValue = (id) => document.getElementById(id).value;

        const updatedData = {
            ...state.data,
            problem: getValue('data-problem'),
            solution: getValue('data-solution'),
            product: getValue('data-product'),
            market_tam: getValue('data-market'),
            traction_metrics: getValue('data-traction'),
            team: getValue('data-team')
            // Note: Lists (red_flags) are not currently editable in this UI
        };

        const memoRes = await fetch('/api/generate_memo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedData)
        });

        if (!memoRes.ok) throw new Error(await memoRes.text());
        const memoData = await memoRes.json();

        const fullData = {
            data: updatedData,
            memo: memoData.memo,
            summary: memoData.summary
        };

        localStorage.setItem('hatchup_analysis', JSON.stringify(fullData));
        renderResults(fullData);
        alert("Memo Regenerated!");

    } catch (err) {
        alert("Error regenerating: " + err.message);
        loadingOverlay.style.display = 'none';
        // Reload page to restore state if needed? No, just keep UI.
    }
}

// Downloads
async function downloadExcel() {
    const state = JSON.parse(localStorage.getItem('hatchup_analysis'));
    if (!state) return alert("No data to download");

    const res = await fetch('/api/export/excel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.data)
    });
    triggerDownload(res, `${state.data.startup_name}_data.xlsx`);
}

async function downloadMemoText() {
    const state = JSON.parse(localStorage.getItem('hatchup_analysis'));
    if (!state) return alert("No data");

    const res = await fetch('/api/export/text_memo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memo: state.memo, startup_name: state.data.startup_name })
    });
    triggerDownload(res, `${state.data.startup_name}_memo.txt`);
}

async function downloadMemoPDF() {
    const state = JSON.parse(localStorage.getItem('hatchup_analysis'));
    if (!state) return alert("No data");

    const res = await fetch('/api/export/pdf_memo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memo: state.memo, startup_name: state.data.startup_name })
    });
    triggerDownload(res, `${state.data.startup_name}_memo.pdf`);
}

async function triggerDownload(res, filename) {
    if (!res.ok) return alert("Download failed");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
