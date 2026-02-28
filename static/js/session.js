(function () {
    const AUTH_COOKIE_NAME = "hatchup_access_token";
    const AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;
    const PENDING_MODE_KEY = "hatchup_pending_mode";
    const AVATAR_BUCKET = "avatars";
    const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

    const state = {
        currentUser: null,
        isAuthReady: false,
        isAuthModalOpen: false,
        pendingMode: null,
        profile: null,
    };

    let currentSession = null;
    let supabaseClient = null;
    let authUiBound = false;
    let profileUiBound = false;
    let logoutConfirmInProgress = false;
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

    function extractAvatar(user) {
        if (!user) return "";
        const metadata = user.user_metadata || {};
        return metadata.avatar_url || metadata.picture || "";
    }

    function extractCurrentUser(session) {
        if (!session || !session.user) return null;
        return {
            id: session.user.id || "",
            email: session.user.email || "",
            name: extractName(session.user),
            avatar_url: extractAvatar(session.user),
        };
    }

    function getDisplayName() {
        const fromProfile = state.profile && state.profile.full_name ? state.profile.full_name.trim() : "";
        if (fromProfile) return fromProfile;
        const fromUser = state.currentUser && state.currentUser.name ? state.currentUser.name.trim() : "";
        if (fromUser) return fromUser;
        const email = state.currentUser && state.currentUser.email ? state.currentUser.email : "";
        if (email && email.includes("@")) return email.split("@")[0];
        return "User";
    }

    function getDisplayEmail() {
        if (state.profile && state.profile.email) return state.profile.email;
        return state.currentUser && state.currentUser.email ? state.currentUser.email : "";
    }

    function getAvatarUrl() {
        if (state.profile && state.profile.avatar_url) return state.profile.avatar_url;
        return state.currentUser && state.currentUser.avatar_url ? state.currentUser.avatar_url : "";
    }

    function getAvatarInitial() {
        const name = getDisplayName();
        if (!name) return "U";
        return name.charAt(0).toUpperCase();
    }

    function renderAvatarNode(node, avatarUrl, initial) {
        if (!node) return;
        if (avatarUrl) {
            node.innerHTML = `<img src="${avatarUrl}" alt="Profile avatar" />`;
            return;
        }
        if (initial) {
            node.textContent = initial;
            return;
        }
        node.textContent = "U";
    }

    function updateAuthUi() {
        const isAuthenticated = !!state.currentUser;
        document.querySelectorAll('[data-auth="logged-out"]').forEach((el) => {
            el.style.display = isAuthenticated ? "none" : "";
        });
        document.querySelectorAll('[data-auth="logged-in"]').forEach((el) => {
            el.style.display = isAuthenticated ? "" : "none";
        });

        const displayName = getDisplayName();
        const displayEmail = getDisplayEmail();
        const avatarUrl = getAvatarUrl();
        const avatarInitial = getAvatarInitial();

        document.querySelectorAll('[data-profile-name="true"]').forEach((el) => {
            el.textContent = isAuthenticated ? displayName : "";
        });
        document.querySelectorAll('[data-profile-email="true"]').forEach((el) => {
            el.textContent = isAuthenticated ? displayEmail : "";
        });
        document.querySelectorAll('[data-profile-avatar="true"]').forEach((el) => {
            renderAvatarNode(el, isAuthenticated ? avatarUrl : "", isAuthenticated ? avatarInitial : "");
        });
        document.querySelectorAll('[data-profile-modal-avatar="true"]').forEach((el) => {
            renderAvatarNode(el, isAuthenticated ? avatarUrl : "", isAuthenticated ? avatarInitial : "");
        });

        if (!isAuthenticated) {
            closeProfileDropdown();
            closeProfileModal();
            closeLogoutConfirmModal();
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
                profile: state.profile,
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
        if (!modal || modal.dataset.bound === "true") return;
        modal.dataset.bound = "true";

        const closeBtn = modal.querySelector('[data-auth-close="true"]');
        if (closeBtn) closeBtn.addEventListener("click", closeAuthModal);

        modal.querySelectorAll("[data-auth-switch]").forEach((btn) => {
            btn.addEventListener("click", () => {
                applyAuthMode(btn.getAttribute("data-auth-switch"));
            });
        });

        const form = modal.querySelector("#auth-form");
        if (form) form.addEventListener("submit", submitEmailAuth);

        const googleBtn = modal.querySelector("#auth-google-btn");
        if (googleBtn) googleBtn.addEventListener("click", loginWithGoogle);

        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeAuthModal();
        });
    }

    function ensureAuthModalRendered() {
        let modal = getAuthModalElement();
        if (modal) {
            bindAuthModalUi(modal);
            return modal;
        }
        const template = document.getElementById("auth-modal-template");
        if (!template || !template.content) return null;
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

    function getProfileModalElement() {
        return document.getElementById("profile-modal");
    }

    function setProfileMessage(message, type) {
        const node = document.getElementById("profile-error");
        if (!node) return;
        node.textContent = message || "";
        node.classList.toggle("success", type === "success");
    }

    function setProfileLoading(loading) {
        const saveBtn = document.getElementById("profile-save-btn");
        if (saveBtn) saveBtn.disabled = !!loading;
    }

    function bindProfileModalUi(modal) {
        if (!modal || modal.dataset.bound === "true") return;
        modal.dataset.bound = "true";

        const closeBtn = modal.querySelector('[data-profile-close="true"]');
        if (closeBtn) closeBtn.addEventListener("click", closeProfileModal);

        const form = modal.querySelector("#profile-form");
        if (form) form.addEventListener("submit", submitProfileForm);

        const fileInput = modal.querySelector("#profile-avatar-file");
        if (fileInput) {
            fileInput.addEventListener("change", () => {
                const file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
                if (!file) {
                    updateAuthUi();
                    return;
                }
                const previewUrl = URL.createObjectURL(file);
                document.querySelectorAll('[data-profile-modal-avatar="true"]').forEach((el) => {
                    renderAvatarNode(el, previewUrl, "");
                });
            });
        }

        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeProfileModal();
        });
    }

    function ensureProfileModalRendered() {
        let modal = getProfileModalElement();
        if (modal) {
            bindProfileModalUi(modal);
            return modal;
        }
        const template = document.getElementById("profile-modal-template");
        if (!template || !template.content) return null;
        const fragment = template.content.cloneNode(true);
        document.body.appendChild(fragment);
        modal = getProfileModalElement();
        bindProfileModalUi(modal);
        return modal;
    }

    function openProfileModal() {
        if (!state.currentUser) return;
        const modal = ensureProfileModalRendered();
        if (!modal) return;
        const nameInput = modal.querySelector("#profile-full-name");
        const fileInput = modal.querySelector("#profile-avatar-file");
        if (nameInput) nameInput.value = getDisplayName();
        if (fileInput) fileInput.value = "";
        setProfileMessage("");
        setProfileLoading(false);
        updateAuthUi();
        modal.hidden = false;
        modal.style.display = "flex";
        closeProfileDropdown();
    }

    function closeProfileModal() {
        const modal = getProfileModalElement();
        if (!modal) return;
        modal.hidden = true;
        modal.style.display = "none";
        setProfileLoading(false);
        setProfileMessage("");
    }

    function getLogoutConfirmModalElement() {
        return document.getElementById("logout-confirm-modal");
    }

    function setLogoutConfirmLoading(loading) {
        const confirmBtn = document.querySelector('[data-logout-confirm="true"]');
        const cancelBtn = document.querySelector('[data-logout-cancel="true"]');
        if (confirmBtn) confirmBtn.disabled = !!loading;
        if (cancelBtn) cancelBtn.disabled = !!loading;
    }

    function bindLogoutConfirmModalUi(modal) {
        if (!modal || modal.dataset.bound === "true") return;
        modal.dataset.bound = "true";

        const cancelBtn = modal.querySelector('[data-logout-cancel="true"]');
        if (cancelBtn) {
            cancelBtn.addEventListener("click", () => {
                closeLogoutConfirmModal();
            });
        }

        const confirmBtn = modal.querySelector('[data-logout-confirm="true"]');
        if (confirmBtn) {
            confirmBtn.addEventListener("click", () => {
                void logout();
            });
        }

        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                closeLogoutConfirmModal();
            }
        });
    }

    function ensureLogoutConfirmModalRendered() {
        let modal = getLogoutConfirmModalElement();
        if (modal) {
            bindLogoutConfirmModalUi(modal);
            return modal;
        }
        const template = document.getElementById("logout-confirm-modal-template");
        if (!template || !template.content) return null;
        const fragment = template.content.cloneNode(true);
        document.body.appendChild(fragment);
        modal = getLogoutConfirmModalElement();
        bindLogoutConfirmModalUi(modal);
        return modal;
    }

    function openLogoutConfirmModal() {
        if (!state.currentUser) return;
        const modal = ensureLogoutConfirmModalRendered();
        if (!modal) return;
        closeProfileDropdown();
        setLogoutConfirmLoading(false);
        modal.hidden = false;
        modal.style.display = "flex";
    }

    function closeLogoutConfirmModal() {
        const modal = getLogoutConfirmModalElement();
        if (!modal) return;
        modal.hidden = true;
        modal.style.display = "none";
        setLogoutConfirmLoading(false);
    }

    function closeProfileDropdown() {
        document.querySelectorAll('[data-profile-dropdown="true"]').forEach((menu) => {
            menu.hidden = true;
            menu.classList.remove("open");
        });
        document.querySelectorAll('[data-profile-toggle="true"]').forEach((btn) => {
            btn.setAttribute("aria-expanded", "false");
        });
    }

    function toggleProfileDropdown(button) {
        const wrapper = button.closest(".profile-menu");
        if (!wrapper) return;
        const menu = wrapper.querySelector('[data-profile-dropdown="true"]');
        if (!menu) return;

        const shouldOpen = menu.hidden;
        closeProfileDropdown();
        if (shouldOpen) {
            menu.hidden = false;
            requestAnimationFrame(() => menu.classList.add("open"));
            button.setAttribute("aria-expanded", "true");
        }
    }

    function getAuthProvider(session) {
        if (!session || !session.user || !session.user.app_metadata) return "";
        return String(session.user.app_metadata.provider || "").toLowerCase();
    }

    async function syncUserWithBackend(session) {
        if (!session || !session.access_token) return null;
        try {
            const response = await fetch("/api/auth/sync-user", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${session.access_token}`,
                },
                credentials: "same-origin",
                cache: "no-store",
            });
            if (!response.ok) return null;
            const payload = await response.json();
            return payload && payload.user ? payload.user : null;
        } catch (_) {
            return null;
        }
    }

    async function fetchProfileFromBackend(session) {
        if (!session || !session.access_token) return null;
        try {
            const response = await fetch("/api/auth/profile", {
                method: "GET",
                headers: {
                    Authorization: `Bearer ${session.access_token}`,
                },
                credentials: "same-origin",
                cache: "no-store",
            });
            if (!response.ok) return null;
            const payload = await response.json();
            return payload && payload.profile ? payload.profile : null;
        } catch (_) {
            return null;
        }
    }

    function applyProfileData(profile) {
        if (!profile) return;
        state.profile = {
            user_id: profile.user_id || (state.currentUser ? state.currentUser.id : ""),
            email: profile.email || (state.currentUser ? state.currentUser.email : ""),
            full_name: profile.full_name || profile.name || "",
            avatar_url: profile.avatar_url || "",
        };
        if (state.currentUser) {
            state.currentUser.name = state.profile.full_name || state.currentUser.name || "";
            state.currentUser.avatar_url = state.profile.avatar_url || state.currentUser.avatar_url || "";
        }
        updateAuthUi();
        publishAuthState();
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
        if (!state.currentUser) {
            state.profile = null;
        }

        if (currentSession && currentSession.access_token) {
            setAuthCookie(currentSession.access_token);
        } else {
            clearAuthCookie();
        }

        updateAuthUi();
        publishAuthState();

        if (state.currentUser) {
            closeAuthModal();
            const syncUser = await syncUserWithBackend(currentSession);
            if (syncUser) applyProfileData(syncUser);

            const profile = await fetchProfileFromBackend(currentSession);
            if (profile) applyProfileData(profile);

            const provider = getAuthProvider(currentSession);
            if (provider === "google") {
                persistPendingMode(null);
                publishAuthState();
                return;
            }
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
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        if (!supabaseClient) {
            setAuthMessage("Authentication is not configured.");
            return false;
        }

        const modal = getAuthModalElement();
        const mode = modal && modal.dataset.mode === "signup" ? "signup" : "login";
        const nameInput = document.getElementById("auth-name");
        const emailInput = document.getElementById("auth-email");
        const passwordInput = document.getElementById("auth-password");
        if (!emailInput || !passwordInput) return false;

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

    async function uploadAvatarAndGetPublicUrl(file) {
        if (!state.currentUser || !state.currentUser.id) throw new Error("No authenticated user.");
        if (!file) return "";
        if (!file.type || !file.type.startsWith("image/")) {
            throw new Error("Only image files are allowed for profile pictures.");
        }
        if (file.size > MAX_AVATAR_BYTES) {
            throw new Error("Profile image is too large. Maximum size is 5MB.");
        }

        if (!currentSession || !currentSession.access_token) {
            throw new Error("Session not available.");
        }
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch("/api/auth/profile/avatar", {
            method: "POST",
            headers: {
                Authorization: `Bearer ${currentSession.access_token}`,
            },
            body: formData,
            credentials: "same-origin",
            cache: "no-store",
        });
        if (!response.ok) {
            const text = await response.text();
            const normalized = String(text || "").toLowerCase();
            if (normalized.includes("bucket") && normalized.includes("not found")) {
                throw new Error("Profile storage bucket 'avatars' was not found. Please run storage setup and try again.");
            }
            if (normalized.includes("policy") || normalized.includes("row-level") || normalized.includes("permission")) {
                throw new Error("Upload blocked by storage policy. Please verify avatar storage policies.");
            }
            throw new Error(text || "Failed to upload profile image.");
        }
        const payload = await response.json();
        const avatarUrl = payload && payload.avatar_url ? payload.avatar_url : (payload && payload.profile ? payload.profile.avatar_url : "");
        if (!avatarUrl) {
            throw new Error("Avatar upload succeeded but public URL is missing.");
        }
        return avatarUrl;
    }

    async function updateProfileOnBackend(fullName, avatarUrl) {
        if (!currentSession || !currentSession.access_token) {
            throw new Error("Session not available.");
        }
        const response = await fetch("/api/auth/profile", {
            method: "PUT",
            headers: {
                Authorization: `Bearer ${currentSession.access_token}`,
                "Content-Type": "application/json",
            },
            credentials: "same-origin",
            cache: "no-store",
            body: JSON.stringify({
                full_name: fullName,
                avatar_url: avatarUrl,
            }),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "Failed to update profile.");
        }
        const payload = await response.json();
        return payload && payload.profile ? payload.profile : null;
    }

    async function submitProfileForm(event) {
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        if (!state.currentUser) return false;

        const nameInput = document.getElementById("profile-full-name");
        const fileInput = document.getElementById("profile-avatar-file");
        const nextName = nameInput ? nameInput.value.trim() : "";
        const selectedFile = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
        let nextAvatarUrl = getAvatarUrl();

        setProfileMessage("");
        setProfileLoading(true);
        try {
            if (selectedFile) {
                nextAvatarUrl = await uploadAvatarAndGetPublicUrl(selectedFile);
            }
            const profile = await updateProfileOnBackend(nextName, nextAvatarUrl);
            if (profile) {
                applyProfileData(profile);
            }

            if (supabaseClient) {
                await supabaseClient.auth.updateUser({
                    data: {
                        full_name: nextName,
                        name: nextName,
                        avatar_url: nextAvatarUrl,
                    },
                });
            }

            closeProfileModal();
        } catch (error) {
            setProfileMessage(error && error.message ? error.message : "Failed to update profile.");
        } finally {
            setProfileLoading(false);
        }
        return false;
    }

    async function logout() {
        if (logoutConfirmInProgress) return;
        logoutConfirmInProgress = true;
        closeProfileDropdown();
        setLogoutConfirmLoading(true);
        try {
            if (supabaseClient) {
                await supabaseClient.auth.signOut();
            }
            await applySession(null);
            resetWorkspaceState();
            persistPendingMode(null);
            closeLogoutConfirmModal();
            if (window.location.pathname !== "/") {
                window.location.assign("/");
            }
        } finally {
            logoutConfirmInProgress = false;
            setLogoutConfirmLoading(false);
        }
    }

    function resetWorkspaceState() {
        const keys = [
            "hatchup_workspace_cache",
            "hatchup_analysis",
            "hatchup_deep_research_history",
            "hatchup_pending_mode",
            "hatchup_mode_session",
            "hatchup_mode",
            "mode",
        ];
        keys.forEach((key) => {
            try {
                localStorage.removeItem(key);
            } catch (_) {
                // Ignore storage errors.
            }
            try {
                sessionStorage.removeItem(key);
            } catch (_) {
                // Ignore storage errors.
            }
        });
        if (window.HatchupAppState && window.HatchupAppState.setMode) {
            window.HatchupAppState.setMode("vc");
        }
    }

    function bindProfileUi() {
        if (profileUiBound) return;
        profileUiBound = true;

        document.addEventListener("click", (event) => {
            const target = event.target;
            const toggleBtn = target.closest ? target.closest('[data-profile-toggle="true"]') : null;
            if (toggleBtn) {
                event.preventDefault();
                event.stopPropagation();
                toggleProfileDropdown(toggleBtn);
                return;
            }

            const editBtn = target.closest ? target.closest('[data-profile-edit="true"]') : null;
            if (editBtn) {
                event.preventDefault();
                openProfileModal();
                return;
            }

            const logoutBtn = target.closest ? target.closest('[data-profile-logout="true"]') : null;
            if (logoutBtn) {
                event.preventDefault();
                openLogoutConfirmModal();
                return;
            }

            const insideMenu = target.closest ? target.closest(".profile-menu") : null;
            if (!insideMenu) {
                closeProfileDropdown();
            }
        });
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
            if (analysisId) headers["X-Hatchup-Analysis-Id"] = analysisId;
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
        if (!state.currentUser) return null;
        return {
            ...state.currentUser,
            full_name: state.profile && state.profile.full_name ? state.profile.full_name : state.currentUser.name,
            avatar_url: getAvatarUrl(),
        };
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
    window.openProfileModal = openProfileModal;
    window.closeProfileModal = closeProfileModal;
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
        window.addEventListener("DOMContentLoaded", () => {
            bindAuthUi();
            bindProfileUi();
        });
    } else {
        bindAuthUi();
        bindProfileUi();
    }

    void bootstrapAuth().catch(() => {
        setAuthReady();
    });
})();


