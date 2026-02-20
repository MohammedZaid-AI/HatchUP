const HATCHUP_SESSION_KEY = 'hatchup_sid';

window.getHatchupSessionId = function () {
    let sid = localStorage.getItem(HATCHUP_SESSION_KEY);
    if (!sid) {
        sid = (window.crypto && crypto.randomUUID)
            ? crypto.randomUUID()
            : `sid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
        localStorage.setItem(HATCHUP_SESSION_KEY, sid);
    }
    return sid;
};

window.getHatchupSessionHeaders = function () {
    return { 'X-Hatchup-Session': window.getHatchupSessionId() };
};
