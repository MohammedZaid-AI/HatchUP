const messagesDiv = document.getElementById('chat-messages');
const input = document.getElementById('chat-input');
const researchEmptyState = document.getElementById('research-empty-state');
const researchContent = document.getElementById('research-content');
let chatHistory = []; // {role: str, content: str}
let hasNormalizedAnalysis = false;
let normalizedData = null;
let normalizedMemo = {};

// Unique Key for Deep Research Storage
// Note: Ideally we should use the startup name as part of the key if we want multiple contexts.
// But current requirement implies simpler "don't lose context".
const STORAGE_KEY = 'hatchup_deep_research_history';

function showResearchEmptyState() {
    if (researchEmptyState) researchEmptyState.style.display = 'block';
    if (researchContent) researchContent.style.display = 'none';
}

function showResearchContent() {
    if (researchEmptyState) researchEmptyState.style.display = 'none';
    if (researchContent) researchContent.style.display = 'block';
}

async function loadAnalysisFromSourceOfTruth() {
    try {
        const res = await fetch('/api/session/analysis', {
            credentials: 'same-origin',
            headers: window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {}
        });
        if (!res.ok) throw new Error('Failed to load session analysis');

        const payload = await res.json();
        const analysis = payload.analysis;
        if (payload.has_analysis && analysis && analysis.data) {
            hasNormalizedAnalysis = true;
            normalizedData = analysis.data;
            normalizedMemo = analysis.memo || {};
            // Keep local cache aligned with backend store.
            localStorage.setItem('hatchup_analysis', JSON.stringify({
                data: normalizedData,
                memo: normalizedMemo,
                summary: analysis.summary || {},
            }));
            return;
        }
    } catch (error) {
        console.error('Session analysis lookup failed, trying local fallback', error);
    }

    // Local fallback for older sessions.
    const stateStr = localStorage.getItem('hatchup_analysis');
    let fallbackState = null;
    try {
        fallbackState = stateStr ? JSON.parse(stateStr) : null;
    } catch (error) {
        console.error('Invalid hatchup_analysis in localStorage', error);
        fallbackState = null;
    }

    if (fallbackState && fallbackState.data) {
        hasNormalizedAnalysis = true;
        normalizedData = fallbackState.data;
        normalizedMemo = fallbackState.memo || {};
    }
}

// Initialize from History
window.addEventListener('DOMContentLoaded', async () => {
    await loadAnalysisFromSourceOfTruth();
    if (!hasNormalizedAnalysis) {
        showResearchEmptyState();
        return;
    }
    showResearchContent();

    // Check if we have history for this specific startup? 
    // Ideally we should namespace by startup name, but for now single session persistence is fine.

    // Clear default welcome message if we have history
    console.log("Loading history...");
    const saved = localStorage.getItem(STORAGE_KEY);

    if (saved) {
        try {
            const hist = JSON.parse(saved);
            if (hist && hist.length > 0) {
                messagesDiv.innerHTML = ""; // process clean slate
                chatHistory = []; // helper appendMessage will re-push 

                hist.forEach(msg => {
                    // Pass false for saveToStorage so we don't re-trigger localStorage writes during load
                    appendMessage(msg.role, msg.content, false, false);
                });
            }
        } catch (e) { console.error("Error parsing history", e); }
    }
});

// Helper to fill input from chips
window.askQuery = function (q) {
    input.value = q;
    sendMessage();
}

window.sendMessage = async function () {
    if (!hasNormalizedAnalysis) return;

    const text = input.value.trim();
    if (!text) return;

    // UI: Add User Message
    input.value = "";
    appendMessage("user", text, false, true);

    // UI: Add Thinking Placeholder
    const thinkingId = appendMessage("assistant", "Thinking...", true, false);

    try {
        const payload = {
            messages: chatHistory, // Send full history
            data: normalizedData,
            memo: normalizedMemo
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

        // Remove thinking
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();

        // Add Actual Response
        appendMessage("assistant", data.response, false, true);

    } catch (err) {
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) {
            thinkingEl.innerText = "Error: " + err.message;
            thinkingEl.style.color = 'red';
        }
    }
}

// Function to clear chat
window.clearChat = function () {
    if (!hasNormalizedAnalysis) return;

    if (confirm("Clear chat history?")) {
        localStorage.removeItem(STORAGE_KEY);
        location.reload();
    }
}

/**
 * Appends message to UI and History
 * @param {string} role 'user' or 'assistant'
 * @param {string} content 
 * @param {boolean} isTemporary If true, does not save to history
 * @param {boolean} saveToStorage If true (default), updates localStorage
 */
function appendMessage(role, content, isTemporary = false, saveToStorage = true) {
    const div = document.createElement('div');
    div.className = `message msg-${role}`;

    // Use Marked.js for rendering
    // Configure marked to not sanitize if trusting input, or sanitize separately.
    // Assuming backend is safe LLM output.
    div.innerHTML = marked.parse(content);

    const id = `msg-${Date.now()}-${Math.random()}`;
    div.id = id;

    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    if (!isTemporary) {
        chatHistory.push({ role, content });

        if (saveToStorage) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(chatHistory));
        }
    }
    return id;
}
