function getModeState() {
    return window.HatchupAppState || null;
}

function syncModeLoadingUi(isLoading) {
    const appContainer = document.getElementById('app-container');
    const modeLoader = document.getElementById('mode-loader');
    if (isLoading) {
        document.body.classList.add('mode-loading');
        if (appContainer) {
            appContainer.hidden = true;
        }
        if (modeLoader) {
            modeLoader.hidden = false;
        }
    } else {
        document.body.classList.remove('mode-loading');
        if (appContainer) {
            appContainer.hidden = false;
        }
        if (modeLoader) {
            modeLoader.hidden = true;
        }
    }
}

function applyModeUi(mode) {
    const vcNav = document.getElementById('vc-nav');
    const founderNav = document.getElementById('founder-nav');
    const vcModeView = document.getElementById('vc-mode-view');
    const founderModeView = document.getElementById('founder-mode-view');
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
    if (vcModeView) {
        vcModeView.hidden = mode !== 'vc';
    }
    if (founderModeView) {
        founderModeView.hidden = mode !== 'founder';
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
    const resolvedMode = storedMode || serverMode;
    const founderModeLink = document.getElementById('founder-mode-link');

    if (modeState && modeState.startModeLoading) {
        modeState.startModeLoading();
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
    if (founderModeLink) {
        founderModeLink.addEventListener('click', (event) => {
            event.preventDefault();
            if (currentMode === 'founder') {
                return;
            }
            currentMode = 'founder';
            if (modeState && modeState.setMode) {
                modeState.setMode('founder');
            } else {
                applyModeUi('founder');
            }
        });
    }
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
    });
});
