(function () {
    const AUTH_COOKIE_NAME = "hatchup_access_token";
    const AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;
    const PENDING_MODE_KEY = "hatchup_pending_mode";

    const state = {
        currentUser: null,
        isAuthReady: false,
        isAuthModalOpen: false,
        pendingMode: null,
    };

    let currentSession = null;
    let supabaseClient = null;
    let authUiBound = false;
    let authReadyResolve;
    const authReady = new Promise((resolve) => {
        authReadyResolve = resolve;
    });

    function normalizePendingMode(mode) {
        if (mode === "founder" || mode === "builders") return "builders";
        if (mode === "vc" || mode === "backers") return "backers";
        return null;
    }

    function pendingModeToWorkspacePath(mode) {
        return mode === "builders" ? "/founder" : "/vc/deck-analyzer";
    }

    function pendingModeToAppMode(mode) {
        return mode === "builders" ? "founder" : "vc";
    }

    function readPendingMode() {
        try {
            return normalizePendingMode(localStorage.getItem(PENDING_MODE_KEY));
        } catch (_) {
            return null;
        }
    }

    function persistPendingMode(mode) {
        const normalized = normalizePendingMode(mode);
        state.pendingMode = normalized;
        try {
            if (normalized) {
                localStorage.setItem(PENDING_MODE_KEY, normalized);
            } else {
                localStorage.removeItem(PENDING_MODE_KEY);
            }
        } catch (_) {
            // Ignore storage errors.
        }
    }

    function setAuthCookie(token) {
        document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; Max-Age=${AUTH_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
    }

    function clearAuthCookie() {
        document.cookie = `${AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
    }

    function extractName(user) {
        if (!user) return "";
        const metadata = user.user_metadata || {};
        return metadata.full_name || metadata.name || metadata.preferred_name || "";
    }

    function extractCurrentUser(session) {
        if (!session || !session.user) return null;
        return {
            id: session.user.id || "",
            email: session.user.email || "",
            name: extractName(session.user),
        };
    }

    function updateAuthUi() {
        const isAuthenticated = !!state.currentUser;
        document.querySelectorAll('[data-auth="logged-out"]').forEach((el) => {
            el.style.display = isAuthenticated ? "none" : "";
        });
        document.querySelectorAll('[data-auth="logged-in"]').forEach((el) => {
            el.style.display = isAuthenticated ? "" : "none";
        });
        const emailNode = document.getElementById("auth-user-email");
        if (emailNode) {
            emailNode.textContent = isAuthenticated ? (state.currentUser.email || "Signed in") : "";
        }
    }

    function publishAuthState() {
        window.HatchupAuthState = {
            currentUser: state.currentUser,
            isAuthReady: state.isAuthReady,
            isAuthModalOpen: state.isAuthModalOpen,
            pendingMode: state.pendingMode,
        };
        window.dispatchEvent(new CustomEvent("hatchup:authchange", {
            detail: {
                currentUser: state.currentUser,
                session: currentSession,
                pendingMode: state.pendingMode,
            },
        }));
    }

    function setAuthReady() {
        if (!state.isAuthReady) {
            state.isAuthReady = true;
            publishAuthState();
            authReadyResolve();
        }
    }

    function setAuthMessage(message, type) {
        const node = document.getElementById("auth-error");
        if (!node) return;
        node.textContent = message || "";
        node.classList.toggle("success", type === "success");
    }

    function setAuthLoading(loading) {
        const submitBtn = document.getElementById("auth-submit-btn");
        const googleBtn = document.getElementById("auth-google-btn");
        if (submitBtn) submitBtn.disabled = !!loading;
        if (googleBtn) googleBtn.disabled = !!loading;
    }

    function getAuthModalElement() {
        return document.getElementById("auth-modal");
    }

    function applyAuthMode(mode) {
        const modal = getAuthModalElement();
        if (!modal) return;

        const resolvedMode = mode === "signup" ? "signup" : "login";
        modal.dataset.mode = resolvedMode;
        setAuthMessage("");

        const title = document.getElementById("auth-modal-title");
        const submitBtn = document.getElementById("auth-submit-btn");
        const passwordInput = document.getElementById("auth-password");
        const nameRow = document.getElementById("auth-name-row");
        const nameInput = document.getElementById("auth-name");
        const loginToggle = document.getElementById("auth-mode-login");
        const signupToggle = document.getElementById("auth-mode-signup");

        if (title) {
            title.textContent = resolvedMode === "signup" ? "Create your account" : "Log in to HatchUp";
        }
        if (submitBtn) {
            submitBtn.textContent = resolvedMode === "signup" ? "Sign Up" : "Login";
        }
        if (passwordInput) {
            passwordInput.setAttribute("autocomplete", resolvedMode === "signup" ? "new-password" : "current-password");
        }
        if (nameRow) {
            nameRow.style.display = resolvedMode === "signup" ? "" : "none";
        }
        if (nameInput) {
            nameInput.required = resolvedMode === "signup";
        }
        if (loginToggle) {
            loginToggle.classList.toggle("active", resolvedMode === "login");
        }
        if (signupToggle) {
            signupToggle.classList.toggle("active", resolvedMode === "signup");
        }
    }

    function bindAuthModalUi(modal) {
        if (!modal) return;
        if (modal.dataset.bound === "true") return;
        modal.dataset.bound = "true";

        const closeBtn = modal.querySelector('[data-auth-close="true"]');
        if (closeBtn) {
            closeBtn.addEventListener("click", closeAuthModal);
        }

        modal.querySelectorAll("[data-auth-switch]").forEach((btn) => {
            btn.addEventListener("click", () => {
                applyAuthMode(btn.getAttribute("data-auth-switch"));
            });
        });

        const form = modal.querySelector("#auth-form");
        if (form) {
            form.addEventListener("submit", submitEmailAuth);
        }

        const googleBtn = modal.querySelector("#auth-google-btn");
        if (googleBtn) {
            googleBtn.addEventListener("click", loginWithGoogle);
        }

        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                closeAuthModal();
            }
        });
    }

    function ensureAuthModalRendered() {
        let modal = getAuthModalElement();
        if (modal) {
            bindAuthModalUi(modal);
            return modal;
        }

        const template = document.getElementById("auth-modal-template");
        if (!template || !template.content) {
            return null;
        }

        const fragment = template.content.cloneNode(true);
        document.body.appendChild(fragment);
        modal = getAuthModalElement();
        bindAuthModalUi(modal);
        return modal;
    }

    function setAuthModalOpen(isOpen) {
        state.isAuthModalOpen = !!isOpen;
        const modal = state.isAuthModalOpen ? ensureAuthModalRendered() : getAuthModalElement();
        if (modal) {
            modal.hidden = !state.isAuthModalOpen;
            modal.style.display = state.isAuthModalOpen ? "flex" : "none";
        }
        if (!state.isAuthModalOpen) {
            setAuthLoading(false);
            setAuthMessage("");
        }
        publishAuthState();
    }

    function openAuthModal(mode) {
        setAuthModalOpen(true);
        applyAuthMode(mode);
    }

    function closeAuthModal() {
        setAuthModalOpen(false);
    }

    async function syncUserWithBackend(session) {
        if (!session || !session.access_token) return;
        try {
            await fetch("/api/auth/sync-user", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${session.access_token}`,
                },
                credentials: "same-origin",
                cache: "no-store",
            });
        } catch (_) {
            // Keep auth UI resilient even if sync endpoint is unavailable.
        }
    }

    function redirectToPendingWorkspaceIfNeeded() {
        const pendingMode = normalizePendingMode(state.pendingMode || readPendingMode());
        if (!pendingMode || !state.currentUser) return;

        persistPendingMode(null);
        const appMode = pendingModeToAppMode(pendingMode);
        if (window.HatchupAppState && window.HatchupAppState.setMode) {
            window.HatchupAppState.setMode(appMode);
        }
        const destination = pendingModeToWorkspacePath(pendingMode);
        if (window.location.pathname !== destination) {
            window.location.assign(destination);
        }
    }

    async function applySession(session) {
        currentSession = session || null;
        state.currentUser = extractCurrentUser(currentSession);

        if (currentSession && currentSession.access_token) {
            setAuthCookie(currentSession.access_token);
        } else {
            clearAuthCookie();
        }

        updateAuthUi();
        publishAuthState();

        if (state.currentUser) {
            closeAuthModal();
            await syncUserWithBackend(currentSession);
            redirectToPendingWorkspaceIfNeeded();
        }
    }

    async function handleSignup(email, password, name) {
        const metadata = {};
        const trimmedName = (name || "").trim();
        if (trimmedName) {
            metadata.full_name = trimmedName;
            metadata.name = trimmedName;
        }

        const { data, error } = await supabaseClient.auth.signUp({
            email,
            password,
            options: { data: metadata },
        });

        if (error) {
            const message = String(error.message || "").toLowerCase();
            if (message.includes("already registered") || message.includes("already exists") || message.includes("user already")) {
                throw new Error("This email is already registered. Please log in.");
            }
            throw error;
        }

        if (!data || !data.session) {
            setAuthMessage("Check your email to confirm your account.", "success");
        }
    }

    async function checkAuthAccountExists(email) {
        const normalizedEmail = (email || "").trim().toLowerCase();
        if (!normalizedEmail) return null;
        try {
            const response = await fetch("/api/auth/email-exists", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                cache: "no-store",
                body: JSON.stringify({ email: normalizedEmail }),
            });
            if (!response.ok) return null;
            const payload = await response.json();
            return !!(payload && payload.exists);
        } catch (_) {
            return null;
        }
    }

    async function submitEmailAuth(event) {
        if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
        }
        if (!supabaseClient) {
            setAuthMessage("Authentication is not configured.");
            return false;
        }

        const modal = getAuthModalElement();
        const mode = modal && modal.dataset.mode === "signup" ? "signup" : "login";
        const nameInput = document.getElementById("auth-name");
        const emailInput = document.getElementById("auth-email");
        const passwordInput = document.getElementById("auth-password");

        if (!emailInput || !passwordInput) {
            return false;
        }

        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const name = nameInput ? nameInput.value.trim() : "";

        setAuthMessage("");
        setAuthLoading(true);
        try {
            if (mode === "signup") {
                await handleSignup(email, password, name);
            } else {
                const { error } = await supabaseClient.auth.signInWithPassword({ email, password });
                if (error) throw error;
            }
        } catch (error) {
            const message = String(error && error.message ? error.message : "Authentication failed");
            const normalized = message.toLowerCase();
            if (mode === "login" && (normalized.includes("invalid login credentials") || normalized.includes("user not found"))) {
                const exists = await checkAuthAccountExists(email);
                if (exists === false) {
                    setAuthMessage("Account not found. Please sign up.");
                } else {
                    setAuthMessage("Invalid email or password.");
                }
            } else if (normalized.includes("already registered") || normalized.includes("already exists") || normalized.includes("user already")) {
                setAuthMessage("This email is already registered. Please log in.");
            } else if (normalized.includes("email not confirmed")) {
                setAuthMessage("Check your email to confirm your account.");
            } else {
                setAuthMessage(message);
            }
        } finally {
            setAuthLoading(false);
        }
        return false;
    }

    async function loginWithGoogle() {
        if (!supabaseClient) return;
        setAuthMessage("");
        setAuthLoading(true);
        try {
            const { error } = await supabaseClient.auth.signInWithOAuth({
                provider: "google",
                options: {
                    redirectTo: window.location.origin,
                },
            });
            if (error) throw error;
        } catch (error) {
            setAuthMessage(error && error.message ? error.message : "Google sign-in failed");
            setAuthLoading(false);
        }
    }

    async function logout() {
        if (supabaseClient) {
            await supabaseClient.auth.signOut();
        } else {
            await applySession(null);
        }
        persistPendingMode(null);
        if (window.location.pathname !== "/") {
            window.location.assign("/");
        }
    }

    function bindAuthUi() {
        if (authUiBound) return;
        authUiBound = true;

        document.querySelectorAll('[data-auth-open="login"]').forEach((btn) => {
            btn.addEventListener("click", () => openAuthModal("login"));
        });
        document.querySelectorAll('[data-auth-open="signup"]').forEach((btn) => {
            btn.addEventListener("click", () => openAuthModal("signup"));
        });

        const logoutBtn = document.getElementById("auth-logout-btn");
        if (logoutBtn) {
            logoutBtn.addEventListener("click", () => {
                void logout();
            });
        }
    }

    async function bootstrapAuth() {
        state.pendingMode = readPendingMode();
        publishAuthState();
        supabaseClient = window.getSupabaseClient ? window.getSupabaseClient() : null;

        if (!supabaseClient) {
            updateAuthUi();
            setAuthReady();
            return;
        }

        const { data } = await supabaseClient.auth.getSession();
        await applySession(data ? data.session : null);
        setAuthReady();

        supabaseClient.auth.onAuthStateChange((_event, session) => {
            void applySession(session || null);
        });
    }

    window.waitForAuthReady = function () {
        return authReady;
    };

    window.getHatchupSessionHeaders = function () {
        const headers = {};
        if (currentSession && currentSession.access_token) {
            headers.Authorization = `Bearer ${currentSession.access_token}`;
        }
        if (window.getActiveAnalysisId) {
            const analysisId = window.getActiveAnalysisId();
            if (analysisId) {
                headers["X-Hatchup-Analysis-Id"] = analysisId;
            }
        }
        return headers;
    };

    window.getHatchupAccessToken = function () {
        return currentSession && currentSession.access_token ? currentSession.access_token : "";
    };

    window.isAuthenticated = function () {
        return !!state.currentUser;
    };

    window.getCurrentHatchupUser = function () {
        return state.currentUser ? { ...state.currentUser } : null;
    };

    window.setPendingAuthMode = function (mode) {
        persistPendingMode(mode);
        publishAuthState();
    };

    window.clearPendingAuthMode = function () {
        persistPendingMode(null);
        publishAuthState();
    };

    window.openAuthModal = openAuthModal;
    window.closeAuthModal = closeAuthModal;
    window.submitEmailAuth = submitEmailAuth;
    window.loginWithGoogle = loginWithGoogle;
    window.logoutHatchup = logout;
    window.HatchupAuthState = {
        currentUser: null,
        isAuthReady: false,
        isAuthModalOpen: false,
        pendingMode: null,
    };

    if (document.readyState === "loading") {
        window.addEventListener("DOMContentLoaded", bindAuthUi);
    } else {
        bindAuthUi();
    }

    void bootstrapAuth().catch(() => {
        setAuthReady();
    });
})();
