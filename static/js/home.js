function setMode(mode) {
    if (window.HatchupAppState && window.HatchupAppState.setMode) {
        return window.HatchupAppState.setMode(mode);
    }
    const value = mode === "founder" ? "founder" : "vc";
    localStorage.setItem("mode", value);
    localStorage.setItem("hatchup_mode", value);
    sessionStorage.setItem("hatchup_mode_session", value);
    return value;
}

function normalizeWorkspaceIntent(mode) {
    if (mode === "founder" || mode === "builders") return "builders";
    return "backers";
}

function getWorkspacePath(intentMode) {
    return intentMode === "builders" ? "/founder" : "/vc/deck-analyzer";
}

window.enterWorkspace = async function (mode) {
    const intentMode = normalizeWorkspaceIntent(mode);
    const appMode = intentMode === "builders" ? "founder" : "vc";

    setMode(appMode);
    if (window.setPendingAuthMode) {
        window.setPendingAuthMode(intentMode);
    }

    if (window.waitForAuthReady) {
        await window.waitForAuthReady();
    }

    if (window.isAuthenticated && !window.isAuthenticated()) {
        if (window.openAuthModal) {
            window.openAuthModal(intentMode === "builders" ? "signup" : "login");
        }
        return;
    }

    if (window.clearPendingAuthMode) {
        window.clearPendingAuthMode();
    }
    const destination = getWorkspacePath(intentMode);
    if (window.location.pathname !== destination) {
        window.location.assign(destination);
    }
};
