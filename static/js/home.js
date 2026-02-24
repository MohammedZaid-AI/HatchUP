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
    const selectedMode = setMode(mode);
    const destination = selectedMode === 'founder' ? '/founder' : '/vc';
    window.location.href = destination;
};
