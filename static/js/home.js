function setMode(mode) {
    if (window.HatchupAppState && window.HatchupAppState.setMode) {
        return window.HatchupAppState.setMode(mode);
    }
    const value = mode === 'founder' ? 'founder' : 'vc';
    localStorage.setItem('mode', value);
    localStorage.setItem('hatchup_mode', value);
    sessionStorage.setItem('hatchup_mode_session', value);
    return value;
}

window.enterWorkspace = async function (mode) {
    const normalizedMode = mode === 'founder' ? 'founder' : 'vc';
    setMode(normalizedMode);
    if (window.setAuthIntentMode) {
        window.setAuthIntentMode(normalizedMode);
    }
    if (window.waitForAuthReady) {
        await window.waitForAuthReady();
    }
    if (window.isAuthenticated && !window.isAuthenticated()) {
        const eventName = normalizedMode === 'founder' ? 'signup' : 'login';
        const authBtn = document.querySelector(`[data-auth-open="${eventName}"]`) || document.querySelector('[data-auth-open="login"]');
        if (authBtn) authBtn.click();
        return;
    }
    const destination = normalizedMode === 'founder' ? '/founder' : '/vc/deck-analyzer';
    window.location.href = destination;
};
