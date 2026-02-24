function getDefaultRouteForMode(mode) {
    return mode === 'founder' ? '/founder' : '/vc/deck-analyzer';
}

function getRouteMode(pathname) {
    if (pathname === '/founder') {
        return 'founder';
    }
    if (pathname.startsWith('/vc/') || pathname === '/vc' || pathname === '/chat' || pathname === '/hatchup_chat') {
        return 'vc';
    }
    return null;
}

function shouldRedirectOnModeChange(pathname) {
    return getRouteMode(pathname) !== null;
}

function getModeState() {
    return window.HatchupAppState || null;
}

function syncModeLoadingUi(isLoading) {
    if (isLoading) {
        document.body.classList.add('mode-loading');
    } else {
        document.body.classList.remove('mode-loading');
    }
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

    const modeState = getModeState();
    const serverMode = modeToggle.dataset.activeMode === 'founder' ? 'founder' : 'vc';
    const storedMode = modeState && modeState.getStoredMode ? modeState.getStoredMode() : null;
    const currentPath = window.location.pathname;
    const routeMode = getRouteMode(currentPath);
    const resolvedMode = storedMode || serverMode;

    if (modeState && modeState.startModeLoading) {
        modeState.startModeLoading();
    }

    // Keep UI hidden while redirecting off a mismatched route.
    if (routeMode && resolvedMode !== routeMode) {
        const destination = getDefaultRouteForMode(resolvedMode);
        if (currentPath !== destination) {
            if (modeState && modeState.persistMode) {
                modeState.persistMode(resolvedMode);
            }
            window.location.replace(destination);
            return;
        }
    }

    let currentMode;
    if (modeState && modeState.setMode) {
        currentMode = modeState.setMode(resolvedMode);
        syncModeLoadingUi(modeState.isModeLoading ? modeState.isModeLoading() : false);
        if (modeState.subscribeMode) {
            modeState.subscribeMode((state) => {
                applyModeUi(state.mode);
                syncModeLoadingUi(state.modeLoading);
            });
        }
    } else {
        currentMode = resolvedMode;
        syncModeLoadingUi(false);
    }

    applyModeUi(currentMode);

    const switchInput = document.getElementById('mode-switch-input');
    if (!switchInput) return;

    switchInput.addEventListener('change', () => {
        const selectedMode = switchInput.checked ? 'founder' : 'vc';
        if (selectedMode === currentMode) {
            return;
        }
        currentMode = selectedMode;

        if (modeState && modeState.setMode) {
            modeState.setMode(selectedMode);
        } else {
            applyModeUi(selectedMode);
        }

        if (shouldRedirectOnModeChange(window.location.pathname)) {
            const destination = getDefaultRouteForMode(selectedMode);
            if (window.location.pathname !== destination) {
                window.location.href = destination;
            }
        }
    });
});
