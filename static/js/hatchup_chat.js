const messagesDiv = document.getElementById("chat-messages");
const input = document.getElementById("chat-input");

let chatHistory = [];
let currentChatId = "";
let activeUserId = "";
let isSending = false;

const DEFAULT_ASSISTANT_TEXT = "Hi! I am HatchUp Chat. Ask about markets, trends, or startups and I will pull live context.";

function buildHeaders() {
    return {
        "Content-Type": "application/json",
        ...(window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {}),
    };
}

function getCurrentUserId() {
    if (!window.getCurrentHatchupUser) return "";
    const user = window.getCurrentHatchupUser();
    return user && user.id ? String(user.id) : "";
}

function renderDefaultAssistantMessage() {
    if (!messagesDiv) return;
    messagesDiv.innerHTML = "";
    appendMessage("assistant", DEFAULT_ASSISTANT_TEXT, true);
}

function clearLocalChatState() {
    chatHistory = [];
    currentChatId = "";
    renderDefaultAssistantMessage();
}

function setComposerEnabled(enabled) {
    if (input) input.disabled = !enabled;
    document.querySelectorAll(".chat-input-area button").forEach((btn) => {
        btn.disabled = !enabled;
    });
}

async function loadServerHistory(chatId) {
    if (!messagesDiv) return;
    const query = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : "";
    const res = await fetch(`/api/chat/hatchup/history${query}`, {
        method: "GET",
        headers: window.getHatchupSessionHeaders ? window.getHatchupSessionHeaders() : {},
        credentials: "same-origin",
        cache: "no-store",
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    currentChatId = data && data.chat_id ? String(data.chat_id) : "";
    if (data && data.storage_warning) {
        console.warn(data.storage_warning);
    }
    const messages = Array.isArray(data && data.messages) ? data.messages : [];

    messagesDiv.innerHTML = "";
    chatHistory = [];
    if (!messages.length) {
        renderDefaultAssistantMessage();
        return;
    }
    messages.forEach((msg) => {
        appendMessage(msg.role, msg.content, false);
    });
}

async function bootstrapChatForCurrentUser() {
    if (!window.waitForAuthReady) return;
    await window.waitForAuthReady();
    const nextUserId = getCurrentUserId();
    if (!nextUserId) {
        activeUserId = "";
        clearLocalChatState();
        setComposerEnabled(false);
        return;
    }
    if (activeUserId === nextUserId && currentChatId) return;
    activeUserId = nextUserId;
    setComposerEnabled(true);
    await loadServerHistory();
}

window.askQuery = function (q) {
    if (!input) return;
    input.value = q;
    void window.sendMessage();
};

window.sendMessage = async function () {
    if (isSending) return;
    const text = input ? input.value.trim() : "";
    if (!text) return;
    if (!activeUserId) return;

    isSending = true;
    setComposerEnabled(false);
    input.value = "";
    appendMessage("user", text);
    const thinkingId = appendMessage("assistant", "Thinking (Checking Live Tools)...", true);

    try {
        const payload = {
            chat_id: currentChatId || null,
            messages: chatHistory,
            query: text,
        };
        const res = await fetch("/api/chat/hatchup", {
            method: "POST",
            headers: buildHeaders(),
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (data && data.chat_id) {
            currentChatId = String(data.chat_id);
        }
        if (data && data.storage_warning) {
            console.warn(data.storage_warning);
        }

        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) thinkingEl.remove();
        appendMessage("assistant", data.response);
    } catch (err) {
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) {
            thinkingEl.innerText = "Error: " + err.message;
            thinkingEl.style.color = "red";
        }
    } finally {
        isSending = false;
        setComposerEnabled(true);
    }
};

window.clearChat = function () {
    if (!confirm("Start a new chat session?")) return;
    chatHistory = [];
    currentChatId = crypto.randomUUID();
    renderDefaultAssistantMessage();
};

function appendMessage(role, content, isTemporary = false) {
    const div = document.createElement("div");
    div.className = `message msg-${role}`;
    div.innerHTML = marked.parse(content || "");
    const id = `msg-${Date.now()}-${Math.random()}`;
    div.id = id;
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    if (!isTemporary) {
        chatHistory.push({ role, content });
    }
    return id;
}

window.addEventListener("hatchup:authchange", (event) => {
    const detail = event && event.detail ? event.detail : {};
    const currentUser = detail.currentUser || null;
    const nextUserId = currentUser && currentUser.id ? String(currentUser.id) : "";
    if (!nextUserId) {
        activeUserId = "";
        clearLocalChatState();
        setComposerEnabled(false);
        return;
    }
    if (nextUserId !== activeUserId) {
        activeUserId = nextUserId;
        void loadServerHistory();
    }
});

window.addEventListener("DOMContentLoaded", () => {
    renderDefaultAssistantMessage();
    setComposerEnabled(false);
    void bootstrapChatForCurrentUser().catch((error) => {
        console.error("Failed to bootstrap chat history", error);
    });
});
