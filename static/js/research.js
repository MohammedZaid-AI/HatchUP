const messagesDiv = document.getElementById('chat-messages');
const input = document.getElementById('chat-input');
const researchEmptyState = document.getElementById('research-empty-state');
const researchContent = document.getElementById('research-content');

let chatHistory = [];
let hasAnalysis = false;
let activeDeck = null;
let activeMemo = {};
let analysisLoading = true;

function showResearchLoading() {
    if (researchEmptyState) researchEmptyState.style.display = 'none';
    if (researchContent) researchContent.style.display = 'none';
}

function syncResearchCache() {
    if (!window.setActiveAnalysisCache) return;
    const analysisId = window.getActiveAnalysisId ? window.getActiveAnalysisId() : null;
    if (!analysisId) return;
    const current = window.getActiveAnalysis ? (window.getActiveAnalysis() || {}) : {};
    window.setActiveAnalysisCache({
        analysisId,
        analysis: {
            ...current,
            deck: activeDeck,
            memo: activeMemo,
            research: chatHistory
        },
        title: activeDeck && activeDeck.startup_name ? activeDeck.startup_name : 'Untitled Analysis'
    });
}

function showResearchEmptyState() {
    if (analysisLoading) return;
    if (researchEmptyState) researchEmptyState.style.display = 'block';
    if (researchContent) researchContent.style.display = 'none';
}

function showResearchContent() {
    if (researchEmptyState) researchEmptyState.style.display = 'none';
    if (researchContent) researchContent.style.display = 'block';
}

async function persistResearch() {
    syncResearchCache();
    try {
        await fetch('/api/session/analysis/research', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
            },
            credentials: 'same-origin',
            body: JSON.stringify({ messages: chatHistory })
        });
    } catch (error) {
        console.error('Failed to persist research history', error);
    }
}

async function loadActiveAnalysis() {
    try {
        if (window.ensureAnalysisWorkspace) {
            await window.ensureAnalysisWorkspace();
        } else {
            await window.refreshAnalysisWorkspace();
        }
        const active = window.getActiveAnalysis();
        if (!active || !active.deck) return null;
        return active;
    } catch (error) {
        console.error('Failed to load active analysis', error);
        return null;
    }
}

window.addEventListener('DOMContentLoaded', async () => {
    showResearchLoading();
    const active = await loadActiveAnalysis();
    analysisLoading = false;
    if (!active) {
        showResearchEmptyState();
        return;
    }

    hasAnalysis = true;
    activeDeck = active.deck;
    activeMemo = active.memo || {};
    showResearchContent();

    const saved = active.research || [];
    if (saved.length > 0) {
        messagesDiv.innerHTML = '';
        chatHistory = [];
        saved.forEach((msg) => appendMessage(msg.role, msg.content, false, false));
        syncResearchCache();
    }
});

window.askQuery = function (q) {
    input.value = q;
    window.sendMessage();
};

window.sendMessage = async function () {
    if (!hasAnalysis) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    appendMessage('user', text, false, true);
    const thinkingId = appendMessage('assistant', 'Thinking...', true, false);

    try {
        const payload = {
            messages: chatHistory,
            data: activeDeck,
            memo: activeMemo
        };
        const res = await fetch('/api/chat/research', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {})
            },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();
        appendMessage('assistant', data.response, false, true);
    } catch (err) {
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) {
            thinkingEl.innerText = 'Error: ' + err.message;
            thinkingEl.style.color = 'red';
        }
    }
};

window.clearChat = async function () {
    if (!hasAnalysis) return;
    const confirmed = confirm('Clear chat history for this analysis?');
    if (!confirmed) return;
    chatHistory = [];
    await persistResearch();
    window.location.reload();
};

function appendMessage(role, content, isTemporary = false, persist = true) {
    const div = document.createElement('div');
    div.className = `message msg-${role}`;
    div.innerHTML = marked.parse(content);
    const id = `msg-${Date.now()}-${Math.random()}`;
    div.id = id;
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    if (!isTemporary) {
        chatHistory.push({ role, content });
        syncResearchCache();
        if (persist) {
            persistResearch();
        }
    }
    return id;
}
