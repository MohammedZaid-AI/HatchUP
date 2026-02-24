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

window.enterWorkspace = function (mode) {
    setMode(mode);
    const destination = '/vc/deck-analyzer';
    window.location.href = destination;
};
