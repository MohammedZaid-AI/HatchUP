function setMode(mode) {
    const value = mode === 'founder' ? 'founder' : 'vc';
    localStorage.setItem('mode', value);
    localStorage.setItem('hatchup_mode', value);
}

window.enterWorkspace = function (mode) {
    setMode(mode);
    const destination = mode === 'founder' ? '/founder' : '/vc';
    window.location.href = destination;
};
