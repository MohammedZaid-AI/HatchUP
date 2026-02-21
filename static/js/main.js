const MODE_STORAGE_KEY = 'hatchup_mode';
const MODE_STORAGE_KEY_LEGACY = 'mode';

function getStoredMode() {
    const mode = localStorage.getItem(MODE_STORAGE_KEY) || localStorage.getItem(MODE_STORAGE_KEY_LEGACY);
    return mode === 'founder' ? 'founder' : 'vc';
}

function persistMode(mode) {
    localStorage.setItem(MODE_STORAGE_KEY, mode);
    localStorage.setItem(MODE_STORAGE_KEY_LEGACY, mode);
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
    const switchInput = document.getElementById('mode-switch-input');
    const modeToggle = document.getElementById('mode-toggle');
    const toolsLabel = document.getElementById('tools-section-label');
    const pastAnalysesPanel = document.getElementById('past-analyses-panel');

    if (vcNav) {
        vcNav.style.display = mode === 'vc' ? 'block' : 'none';
    }
    if (founderNav) {
        founderNav.style.display = mode === 'founder' ? 'block' : 'none';
    }
    if (switchInput) {
        switchInput.checked = mode === 'founder';
    }
    if (modeToggle) {
        modeToggle.dataset.activeMode = mode;
    }
    if (toolsLabel) {
        toolsLabel.textContent = mode === 'founder' ? 'Founder Tools' : 'VC Tools';
    }
    if (pastAnalysesPanel) {
        pastAnalysesPanel.style.display = mode === 'vc' ? 'flex' : 'none';
    }
    if (window.refreshAnalysisWorkspace && mode === 'vc') {
        window.refreshAnalysisWorkspace().catch(() => null);
    }
}

window.addEventListener('DOMContentLoaded', () => {
    const modeToggle = document.getElementById('mode-toggle');
    if (!modeToggle) return;

    const serverMode = modeToggle.dataset.activeMode === 'founder' ? 'founder' : 'vc';
    const storedMode = getStoredMode();
    const currentPath = window.location.pathname;
    const activeMode = shouldRedirectOnModeChange(currentPath) ? serverMode : storedMode;
    let currentMode = activeMode;

    persistMode(activeMode);
    applyModeUi(activeMode);

    const switchInput = document.getElementById('mode-switch-input');
    if (!switchInput) return;

    switchInput.addEventListener('change', () => {
        const selectedMode = switchInput.checked ? 'founder' : 'vc';
        if (selectedMode === currentMode) {
            return;
        }
        currentMode = selectedMode;

        persistMode(selectedMode);
        applyModeUi(selectedMode);

        if (shouldRedirectOnModeChange(window.location.pathname)) {
            const destination = getDefaultRouteForMode(selectedMode);
            if (window.location.pathname !== destination) {
                window.location.href = destination;
            }
        }
    });
});
