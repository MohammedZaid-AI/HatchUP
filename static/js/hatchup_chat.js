const messagesDiv = document.getElementById('chat-messages');
const input = document.getElementById('chat-input');
let chatHistory = []; // {role: str, content: str}

const STORAGE_KEY = 'hatchup_chat_history';

// Initialize from History
window.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        try {
            const hist = JSON.parse(saved);
            if (hist && hist.length > 0) {
                // Clear default message only if we have history
                // Wait, default message is in HTML.
                messagesDiv.innerHTML = "";
                chatHistory = [];

                hist.forEach(msg => {
                    appendMessage(msg.role, msg.content, false, false);
                });
            }
        } catch (e) { console.error("Error parsing history", e); }
    }
});

// Expose askQuery for chips
window.askQuery = function (q) {
    input.value = q;
    sendMessage();
}

window.sendMessage = async function () {
    const text = input.value.trim();
    if (!text) return;

    // UI: Add User Message
    input.value = "";
    appendMessage("user", text);

    // UI: Add Thinking
    const thinkingId = appendMessage("assistant", "Thinking (Checking Live Tools)...", true);

    try {
        const payload = {
            messages: chatHistory, // Includes the new user message
            query: text
        };

        const res = await fetch('/api/chat/hatchup', {
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
        appendMessage("assistant", data.response);

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

    // Use Marked
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
