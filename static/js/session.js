(function () {
    const AUTH_COOKIE_NAME = "hatchup_access_token";
    const AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;
    const LEGACY_SESSION_KEY = "hatchup_sid";
    const ANALYSIS_WORKSPACE_KEY = "hatchup_workspace_cache";
    const LEGACY_ANALYSIS_KEY = "hatchup_analysis";
    const LEGACY_RESEARCH_KEY = "hatchup_deep_research_history";
    const AUTH_INTENT_KEY = "hatchup_auth_intent_mode";
    const PENDING_MODE_KEY = "pending_mode";

    let supabaseClient = null;
    let currentSession = null;
    let currentUser = null;
    let authReadyResolve;
    const authReady = new Promise((resolve) => {
        authReadyResolve = resolve;
    });
    let handlingAuthSuccess = false;
    let lastHandledAccessToken = null;
    let authUiBound = false;

    function getSupabaseConfig() {
        return window.HATCHUP_SUPABASE || {};
    }

    function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function normalizeMode(mode) {
        return mode === "founder" ? "founder" : "vc";
    }

    function setAuthIntentMode(mode) {
        const normalizedMode = normalizeMode(mode);
        try {
            localStorage.setItem(AUTH_INTENT_KEY, normalizedMode);
            localStorage.setItem(PENDING_MODE_KEY, normalizedMode);
        } catch (_) {
            // Ignore storage errors.
        }
    }

    function getAuthIntentMode() {
        try {
            const value = localStorage.getItem(AUTH_INTENT_KEY);
            return value ? normalizeMode(value) : null;
        } catch (_) {
            return null;
        }
    }

    function clearAuthIntentMode() {
        try {
            localStorage.removeItem(AUTH_INTENT_KEY);
            localStorage.removeItem(PENDING_MODE_KEY);
        } catch (_) {
            // Ignore storage errors.
        }
    }

    function getModeWorkspacePath(mode) {
        const normalized = normalizeMode(mode);
        if (normalized === "founder") {
            return "/founder";
        }
        return "/vc/deck-analyzer";
    }

    function setAuthCookie(token) {
        document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; Max-Age=${AUTH_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
    }

    function clearAuthCookie() {
        document.cookie = `${AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
    }

    function clearLocalWorkspaceCache() {
        localStorage.removeItem(LEGACY_SESSION_KEY);
        localStorage.removeItem(ANALYSIS_WORKSPACE_KEY);
        localStorage.removeItem(LEGACY_ANALYSIS_KEY);
        localStorage.removeItem(LEGACY_RESEARCH_KEY);
    }

    function extractName(user) {
        if (!user) return "";
        const metadata = user.user_metadata || {};
        return metadata.full_name || metadata.name || metadata.preferred_name || "";
    }

    function extractUser(session) {
        if (!session || !session.user) return null;
        const user = session.user;
        return {
            id: user.id || "",
            email: user.email || "",
            name: extractName(user),
        };
    }

    function updateAuthUi(session) {
        const isAuthed = !!(session && session.user);
        document.querySelectorAll('[data-auth="logged-out"]').forEach((el) => {
            el.style.display = isAuthed ? "none" : "";
        });
        document.querySelectorAll('[data-auth="logged-in"]').forEach((el) => {
            el.style.display = isAuthed ? "" : "none";
        });

        const emailNode = document.getElementById("auth-user-email");
        if (emailNode) {
            emailNode.textContent = isAuthed ? (session.user.email || "Signed in") : "";
        }
    }

    function setAuthLoading(loading) {
        const submitBtn = document.getElementById("auth-submit-btn");
        const googleBtn = document.getElementById("auth-google-btn");
        if (submitBtn) submitBtn.disabled = !!loading;
        if (googleBtn) googleBtn.disabled = !!loading;
    }

    function setAuthModalOpen(isOpen) {
        const modal = document.getElementById("auth-modal");
        if (!modal) return;
        modal.hidden = !isOpen;
        if (!isOpen) {
            const error = document.getElementById("auth-error");
            if (error) error.textContent = "";
            setAuthLoading(false);
        }
    }

    function closeAuthModal() {
        setAuthModalOpen(false);
    }

    function applyAuthMode(mode) {
        const modal = document.getElementById("auth-modal");
        if (!modal) return;
        const resolvedMode = mode === "signup" ? "signup" : "login";
        modal.dataset.mode = resolvedMode;

        const title = document.getElementById("auth-modal-title");
        const action = document.getElementById("auth-submit-btn");
        const passwordInput = document.getElementById("auth-password");
        const nameRow = document.getElementById("auth-name-row");
        const nameInput = document.getElementById("auth-name");
        const loginToggle = document.getElementById("auth-mode-login");
        const signupToggle = document.getElementById("auth-mode-signup");

        if (title) {
            title.textContent = resolvedMode === "signup" ? "Create your account" : "Log in to HatchUp";
        }
        if (action) {
            action.textContent = resolvedMode === "signup" ? "Sign Up" : "Login";
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
            loginToggle.setAttribute("aria-selected", resolvedMode === "login" ? "true" : "false");
        }
        if (signupToggle) {
            signupToggle.classList.toggle("active", resolvedMode === "signup");
            signupToggle.setAttribute("aria-selected", resolvedMode === "signup" ? "true" : "false");
        }
    }

    async function waitForActiveSession(timeoutMs = 8000) {
        if (!supabaseClient) return null;
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {
            const { data } = await supabaseClient.auth.getSession();
            if (data && data.session && data.session.access_token) {
                return data.session;
            }
            await sleep(120);
        }
        return null;
    }

    async function syncUserWithBackend(session) {
        if (!session || !session.access_token) return;
        const response = await fetch("/api/auth/sync-user", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${session.access_token}`,
            },
            credentials: "same-origin",
            cache: "no-store",
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Failed to sync user");
        }
    }

    function navigateToAuthIntent() {
        let intendedMode = getAuthIntentMode();
        if (!intendedMode) {
            try {
                const pendingMode = localStorage.getItem(PENDING_MODE_KEY);
                intendedMode = pendingMode ? normalizeMode(pendingMode) : null;
            } catch (_) {
                intendedMode = null;
            }
        }
        if (!intendedMode) return false;
        clearAuthIntentMode();
        try {
            localStorage.removeItem(PENDING_MODE_KEY);
        } catch (_) {
            // Ignore storage errors.
        }
        if (window.HatchupAppState && window.HatchupAppState.setMode) {
            window.HatchupAppState.setMode(intendedMode);
        } else {
            try {
                localStorage.setItem("mode", intendedMode);
                localStorage.setItem("hatchup_mode", intendedMode);
                sessionStorage.setItem("hatchup_mode_session", intendedMode);
            } catch (_) {
                // Ignore storage errors.
            }
        }
        const destination = getModeWorkspacePath(intendedMode);
        if (window.location.pathname + window.location.search !== destination) {
            window.location.href = destination;
            return true;
        }
        return false;
    }

    async function handlePostAuthSuccess(session) {
        if (!session || !session.access_token || !session.user) return;
        if (handlingAuthSuccess) return;
        if (lastHandledAccessToken === session.access_token) return;

        handlingAuthSuccess = true;
        let syncError = null;
        try {
            await syncUserWithBackend(session);
        } catch (error) {
            syncError = error;
            console.error("Auth user sync failed", error);
        } finally {
            lastHandledAccessToken = session.access_token;
            closeAuthModal();
            navigateToAuthIntent();
            if (syncError) {
                window.dispatchEvent(new CustomEvent("hatchup:authsyncwarning", {
                    detail: {
                        message: syncError.message || "Failed to sync user profile",
                    },
                }));
            }
            handlingAuthSuccess = false;
        }
    }

    function setSession(session) {
        const previousToken = currentSession && currentSession.access_token ? currentSession.access_token : null;
        currentSession = session || null;
        currentUser = extractUser(currentSession);
        setAuthLoading(false);
        const token = currentSession && currentSession.access_token;
        if (token) {
            setAuthCookie(token);
        } else {
            clearAuthCookie();
            lastHandledAccessToken = null;
        }
        updateAuthUi(currentSession);
        window.dispatchEvent(new CustomEvent("hatchup:authchange", {
            detail: {
                session: currentSession,
                user: currentUser,
            },
        }));

        if (token && token !== previousToken) {
            void handlePostAuthSuccess(currentSession);
        }
    }

    function ensureFetchAuthWrapper() {
        if (!window.fetch || window.fetch.__hatchupWrapped) return;
        const originalFetch = window.fetch.bind(window);
        const wrappedFetch = async function (input, init) {
            const requestInit = init ? { ...init } : {};
            await authReady;
            const headers = new Headers(requestInit.headers || {});
            if (!headers.has("Authorization")) {
                const token = currentSession && currentSession.access_token;
                if (token) headers.set("Authorization", `Bearer ${token}`);
            }
            if (window.getActiveAnalysisId && !headers.has("X-Hatchup-Analysis-Id")) {
                const analysisId = window.getActiveAnalysisId();
                if (analysisId) headers.set("X-Hatchup-Analysis-Id", analysisId);
            }
            requestInit.headers = headers;
            return originalFetch(input, requestInit);
        };
        wrappedFetch.__hatchupWrapped = true;
        window.fetch = wrappedFetch;
    }

    async function bootstrapSupabase() {
        const config = getSupabaseConfig();
        if (!window.supabase || !config.url || !config.anonKey) {
            authReadyResolve();
            return;
        }

        supabaseClient = window.supabase.createClient(config.url, config.anonKey);
        try {
            const { data } = await supabaseClient.auth.getSession();
            setSession(data ? data.session : null);
        } catch (_) {
            setSession(null);
        } finally {
            authReadyResolve();
        }

        supabaseClient.auth.onAuthStateChange((_event, session) => {
            setSession(session || null);
        });
    }

    function openAuthModal(mode) {
        const modal = document.getElementById("auth-modal");
        if (!modal) return;
        setAuthModalOpen(true);
        applyAuthMode(mode);
    }

    async function loginWithEmail(email, password) {
        const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
        if (error) throw error;
        return data ? data.session : null;
    }

    async function signUpWithEmail(email, password, name) {
        const metadata = {};
        const trimmedName = (name || "").trim();
        if (trimmedName) {
            metadata.full_name = trimmedName;
            metadata.name = trimmedName;
        }

        const { data, error } = await supabaseClient.auth.signUp({
            email,
            password,
            options: {
                data: metadata,
            },
        });
        if (error) {
            const msg = String(error.message || "").toLowerCase();
            if (msg.includes("already registered") || msg.includes("already exists") || msg.includes("user already")) {
                throw new Error("This email is already signed up. Please log in.");
            }
            throw error;
        }
        return data || null;
    }

    async function submitEmailAuth(event) {
        if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
        }
        if (!supabaseClient) {
            const errorNode = document.getElementById("auth-error");
            if (errorNode) errorNode.textContent = "Authentication is not ready. Please refresh and try again.";
            return false;
        }
        const modal = document.getElementById("auth-modal");
        const nameInput = document.getElementById("auth-name");
        const emailInput = document.getElementById("auth-email");
        const passwordInput = document.getElementById("auth-password");
        const errorNode = document.getElementById("auth-error");

        if (!emailInput || !passwordInput) return false;
        if (errorNode) errorNode.textContent = "";
        setAuthLoading(true);

        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const name = nameInput ? nameInput.value.trim() : "";

        try {
            let session = null;
            if ((modal && modal.dataset.mode) === "signup") {
                const signUpData = await signUpWithEmail(email, password, name);
                if (signUpData && signUpData.user && signUpData.session) {
                    await supabaseClient.auth.signOut();
                    setSession(null);
                    applyAuthMode("login");
                    if (errorNode) errorNode.textContent = "Sign up successful. Please log in.";
                    return false;
                }
                if (signUpData && signUpData.user) {
                    applyAuthMode("login");
                    if (errorNode) errorNode.textContent = "Sign up successful. Please confirm email, then log in.";
                    return false;
                }
                throw new Error("Sign up failed. Please try again.");
            } else {
                session = await loginWithEmail(email, password);
            }

            const activeSession = session || (await waitForActiveSession());
            if (!activeSession) {
                throw new Error("Authenticated session not available");
            }
            setSession(activeSession);
            await handlePostAuthSuccess(activeSession);
        } catch (authError) {
            if (errorNode) {
                const rawMessage = authError && authError.message ? authError.message : "Authentication failed";
                const normalized = String(rawMessage).toLowerCase();
                if (normalized.includes("invalid login credentials") || normalized.includes("user not found")) {
                    const isLoginMode = (modal && modal.dataset.mode) !== "signup";
                    errorNode.textContent = isLoginMode
                        ? "Please sign up first. No account found for this email."
                        : "User does not exist or password is incorrect.";
                } else if (normalized.includes("email not confirmed")) {
                    errorNode.textContent = "Email not confirmed. Check your inbox and verify your email first.";
                } else if (normalized.includes("rate limit") || normalized.includes("email rate limit")) {
                    errorNode.textContent = "Too many email attempts. Please wait a few minutes and try again.";
                } else {
                    errorNode.textContent = rawMessage;
                }
            }
        } finally {
            setAuthLoading(false);
        }
        return false;
    }

    async function loginWithGoogle() {
        if (!supabaseClient) return;
        const errorNode = document.getElementById("auth-error");
        if (errorNode) errorNode.textContent = "";
        setAuthLoading(true);
        try {
            const { error } = await supabaseClient.auth.signInWithOAuth({
                provider: "google",
                options: {
                    redirectTo: `${window.location.origin}/`,
                },
            });
            if (error) throw error;
        } catch (error) {
            if (errorNode) {
                errorNode.textContent = error && error.message ? error.message : "Google sign-in failed";
            }
            setAuthLoading(false);
        }
    }

    async function logout() {
        if (supabaseClient) {
            await supabaseClient.auth.signOut();
        }
        setSession(null);
        clearLocalWorkspaceCache();
        clearAuthIntentMode();
        if (window.location.pathname !== "/") {
            window.location.href = "/";
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
        document.querySelectorAll('[data-auth-switch]').forEach((btn) => {
            btn.addEventListener("click", () => {
                applyAuthMode(btn.getAttribute("data-auth-switch"));
            });
        });
        document.querySelectorAll('[data-auth-close="true"]').forEach((btn) => {
            btn.addEventListener("click", closeAuthModal);
        });

        const form = document.getElementById("auth-form");
        if (form) {
            form.addEventListener("submit", submitEmailAuth);
        }

        const googleBtn = document.getElementById("auth-google-btn");
        if (googleBtn) {
            googleBtn.addEventListener("click", loginWithGoogle);
        }

        const logoutBtn = document.getElementById("auth-logout-btn");
        if (logoutBtn) {
            logoutBtn.addEventListener("click", logout);
        }
    }

    window.waitForAuthReady = function () {
        return authReady;
    };

    window.getHatchupSessionHeaders = function () {
        const headers = {};
        const token = currentSession && currentSession.access_token;
        if (token) headers["Authorization"] = `Bearer ${token}`;
        if (window.getActiveAnalysisId) {
            const activeAnalysisId = window.getActiveAnalysisId();
            if (activeAnalysisId) headers["X-Hatchup-Analysis-Id"] = activeAnalysisId;
        }
        return headers;
    };

    window.isAuthenticated = function () {
        return !!(currentSession && currentSession.user);
    };

    window.getCurrentHatchupUser = function () {
        return currentUser ? { ...currentUser } : null;
    };

    window.setAuthIntentMode = setAuthIntentMode;
    window.getAuthIntentMode = getAuthIntentMode;
    window.clearAuthIntentMode = clearAuthIntentMode;
    window.navigateToAuthIntent = navigateToAuthIntent;
    window.setAuthModalOpen = setAuthModalOpen;
    window.closeAuthModal = closeAuthModal;
    window.openAuthModal = openAuthModal;
    window.submitEmailAuth = submitEmailAuth;
    window.loginWithGoogle = loginWithGoogle;
    window.logoutHatchup = logout;
    window.__HATCHUP_SESSION_VERSION = "20260227j";

    ensureFetchAuthWrapper();
    void bootstrapSupabase();

    if (document.readyState === "loading") {
        window.addEventListener("DOMContentLoaded", bindAuthUi);
    } else {
        bindAuthUi();
    }
})();
