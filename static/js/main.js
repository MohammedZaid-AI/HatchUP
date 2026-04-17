function getModeState() {
    return window.HatchupAppState || null;
}

const routePrefetchState = new Map();
let modePrefetchInitialized = false;

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
    if (window.preloadAnalysisWorkspace && mode === 'vc') {
        window.preloadAnalysisWorkspace().catch(() => null);
    }
}

function routeForMode(mode) {
    return mode === 'founder' ? '/founder' : '/vc/deck-analyzer';
}

function preloadDocumentRoute(path) {
    if (!path || routePrefetchState.has(path)) {
        return routePrefetchState.get(path) || Promise.resolve();
    }

    const preloadPromise = new Promise((resolve) => {
        const link = document.createElement('link');
        link.rel = 'prefetch';
        link.as = 'document';
        link.href = path;
        link.onload = () => resolve();
        link.onerror = () => resolve();
        document.head.appendChild(link);

        window.fetch(path, {
            credentials: 'same-origin',
            cache: 'force-cache'
        }).catch(() => null).finally(resolve);
    });

    routePrefetchState.set(path, preloadPromise);
    return preloadPromise;
}

function preloadModeResources(mode) {
    const path = routeForMode(mode);
    void preloadDocumentRoute(path);
    if (mode === 'vc' && window.preloadAnalysisWorkspace) {
        void window.preloadAnalysisWorkspace();
    }
}

function scheduleModePreloads(currentMode) {
    if (modePrefetchInitialized) {
        preloadModeResources(currentMode === 'founder' ? 'vc' : 'founder');
        return;
    }

    modePrefetchInitialized = true;
    const warmRoutes = () => {
        preloadModeResources(currentMode);
        preloadModeResources(currentMode === 'founder' ? 'vc' : 'founder');
    };

    if ('requestIdleCallback' in window) {
        window.requestIdleCallback(warmRoutes, { timeout: 1200 });
        return;
    }
    window.setTimeout(warmRoutes, 250);
}

let workspaceUiInitialized = false;
let workspacePageInitialized = false;

function initializePage() {
    if (workspacePageInitialized) {
        if (window.initializeHelpTutorial) {
            window.initializeHelpTutorial();
        }
        return;
    }
    workspacePageInitialized = true;

    const modeToggle = document.getElementById('mode-toggle');
    if (!modeToggle) return;

    const modeState = getModeState();
    const serverMode = modeToggle.dataset.activeMode === 'founder' ? 'founder' : 'vc';
    const storedMode = modeState && modeState.getStoredMode ? modeState.getStoredMode() : null;
    const resolvedMode = storedMode || serverMode;

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
    if (!switchInput) return;

    let switchFrameId = null;
    let pendingMode = null;

    function applySelectedMode(selectedMode) {
        if (selectedMode === currentMode) {
            return;
        }
        const targetRoute = routeForMode(selectedMode);
        currentMode = selectedMode;
        if (modeState && modeState.setMode) {
            modeState.setMode(selectedMode);
        } else {
            applyModeUi(selectedMode);
        }
        preloadModeResources(selectedMode === 'founder' ? 'vc' : 'founder');
        if (window.location.pathname !== targetRoute) {
            window.setTimeout(() => {
                window.location.assign(targetRoute);
            }, 0);
            return;
        }
    }

    switchInput.addEventListener('change', () => {
        pendingMode = switchInput.checked ? 'founder' : 'vc';
        if (switchFrameId !== null) {
            return;
        }
        switchFrameId = window.requestAnimationFrame(() => {
            const nextMode = pendingMode;
            pendingMode = null;
            switchFrameId = null;
            applySelectedMode(nextMode);
        });
    });

    if (!workspaceUiInitialized) {
        workspaceUiInitialized = true;

        document.addEventListener('click', (event) => {
            const founderModeLink = event.target.closest('#founder-mode-link');
            if (!founderModeLink) return;

            event.preventDefault();
            if (modeState && modeState.setMode) {
                modeState.setMode('founder');
            }
            preloadModeResources('founder');
            window.location.assign(routeForMode('founder'));
        });
    }

    scheduleModePreloads(currentMode);

    const founderNavLink = document.querySelector('a[href="/founder"]');
    const founderScoutLink = document.querySelector('a[href="/founder-mode"]');
    const vcDeckLink = document.querySelector('a[href="/vc/deck-analyzer"]');

    [founderNavLink, founderScoutLink].forEach((link) => {
        if (!link) return;
        link.addEventListener('mouseenter', () => preloadModeResources('founder'), { passive: true });
        link.addEventListener('focus', () => preloadModeResources('founder'), { passive: true });
    });
    if (vcDeckLink) {
        vcDeckLink.addEventListener('mouseenter', () => preloadModeResources('vc'), { passive: true });
        vcDeckLink.addEventListener('focus', () => preloadModeResources('vc'), { passive: true });
    }

    if (window.initializeHelpTutorial) {
        window.initializeHelpTutorial();
    }
}

window.initializePage = initializePage;

window.addEventListener('DOMContentLoaded', initializePage);
