const MODE_STORAGE_KEY = 'hatchup_mode';

function getStoredMode() {
    const mode = localStorage.getItem(MODE_STORAGE_KEY);
    return mode === 'founder' ? 'founder' : 'vc';
}

function getDefaultRouteForMode(mode) {
    return mode === 'founder' ? '/founder' : '/vc/deck-analyzer';
}

function shouldRedirectOnModeChange(pathname) {
    return pathname.startsWith('/vc/') || pathname === '/founder';
}

function applyModeUi(mode) {
    const vcNav = document.getElementById('vc-nav');
    const founderNav = document.getElementById('founder-nav');
    const modeButtons = document.querySelectorAll('.mode-btn');

    if (vcNav) {
        vcNav.style.display = mode === 'vc' ? 'block' : 'none';
    }
    if (founderNav) {
        founderNav.style.display = mode === 'founder' ? 'block' : 'none';
    }

    modeButtons.forEach((btn) => {
        if (btn.dataset.mode === mode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

window.addEventListener('DOMContentLoaded', () => {
    const modeToggle = document.getElementById('mode-toggle');
    if (!modeToggle) return;

    const serverMode = modeToggle.dataset.activeMode === 'founder' ? 'founder' : 'vc';
    const storedMode = getStoredMode();
    const currentPath = window.location.pathname;
    const activeMode = shouldRedirectOnModeChange(currentPath) ? serverMode : storedMode;

    localStorage.setItem(MODE_STORAGE_KEY, activeMode);
    applyModeUi(activeMode);

    modeToggle.addEventListener('click', (event) => {
        const target = event.target.closest('.mode-btn');
        if (!target) return;

        const selectedMode = target.dataset.mode === 'founder' ? 'founder' : 'vc';
        localStorage.setItem(MODE_STORAGE_KEY, selectedMode);
        applyModeUi(selectedMode);

        if (shouldRedirectOnModeChange(window.location.pathname)) {
            const destination = getDefaultRouteForMode(selectedMode);
            if (window.location.pathname !== destination) {
                window.location.href = destination;
            }
        }
    });
});
