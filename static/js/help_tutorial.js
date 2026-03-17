(function () {
    const HELP_SEEN_KEY = 'hatchup_has_seen_tutorial';
    const body = document.body;
    let fab = null;
    let modal = null;
    let listenersBound = false;

    if (!body) {
        return;
    }

    let modalOpen = false;
    let autoOpenHandledForUser = '';

    function getCurrentUser() {
        return window.getCurrentHatchupUser ? window.getCurrentHatchupUser() : null;
    }

    function getUserScopedKey() {
        const user = getCurrentUser();
        if (!user || !user.id) return '';
        return `${HELP_SEEN_KEY}:${user.id}`;
    }

    function hasSeenTutorial() {
        const key = getUserScopedKey();
        if (!key) return true;
        try {
            return localStorage.getItem(key) === 'true';
        } catch (_) {
            return true;
        }
    }

    function markTutorialSeen() {
        const key = getUserScopedKey();
        if (!key) return;
        try {
            localStorage.setItem(key, 'true');
        } catch (_) {
            // Ignore storage errors.
        }
    }

    function getCurrentMode() {
        const appState = window.HatchupAppState || null;
        if (appState && appState.getMode) {
            return appState.getMode();
        }
        return 'vc';
    }

    function isTutorialEligible() {
        return !!getCurrentUser() && getCurrentMode() === 'vc';
    }

    function syncFabVisibility() {
        if (!fab) return;
        fab.classList.remove('is-hidden');
    }

    function openTutorial(options) {
        const settings = options || {};
        if (!modal) return;
        if (settings.markSeen) {
            markTutorialSeen();
        }
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.classList.add('is-open');
        body.style.overflow = 'hidden';
        modalOpen = true;
    }

    function closeTutorial() {
        if (!modal) return;
        modal.classList.remove('is-open');
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        body.style.overflow = '';
        modalOpen = false;
    }

    function maybeAutoOpenTutorial() {
        const user = getCurrentUser();
        const userId = user && user.id ? user.id : '';
        if (!userId || !isTutorialEligible()) return;
        if (autoOpenHandledForUser === userId) return;
        autoOpenHandledForUser = userId;
        if (hasSeenTutorial()) return;
        openTutorial({ markSeen: true });
    }

    function handleStartAnalysis() {
        console.log('Tutorial CTA clicked');
        closeTutorial();
        if (typeof window.startNewAnalysis === 'function') {
            window.startNewAnalysis();
            return;
        }
        if (getCurrentMode() !== 'vc' && window.HatchupAppState && window.HatchupAppState.setMode) {
            window.HatchupAppState.setMode('vc');
        }
        window.location.assign('/vc/deck-analyzer?fresh=1');
    }

    function bindDelegatedListeners() {
        if (listenersBound) return;
        listenersBound = true;

        document.addEventListener('click', function (event) {
            const helpButton = event.target.closest('#help-fab');
            if (helpButton) {
                console.log('Help button clicked');
                openTutorial({ markSeen: false });
                return;
            }

            const closeTrigger = event.target.closest('#tutorial-close, #tutorial-dismiss');
            if (closeTrigger) {
                console.log('Tutorial close clicked');
                closeTutorial();
                return;
            }

            const startTrigger = event.target.closest('#tutorial-start-analysis');
            if (startTrigger) {
                handleStartAnalysis();
                return;
            }

            if (modal && event.target === modal) {
                console.log('Tutorial backdrop clicked');
                closeTutorial();
            }
        });
    }

    function initializePage() {
        fab = document.getElementById('help-fab');
        modal = document.getElementById('tutorial-modal');
        if (!fab || !modal) return;
        bindDelegatedListeners();
        syncFabVisibility();
        maybeAutoOpenTutorial();
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modalOpen) {
            closeTutorial();
        }
    });

    window.addEventListener('hatchup:authchange', function () {
        syncFabVisibility();
        maybeAutoOpenTutorial();
        if (!getCurrentUser() && modalOpen) {
            closeTutorial();
        }
    });

    if (window.HatchupAppState && window.HatchupAppState.subscribeMode) {
        window.HatchupAppState.subscribeMode(function () {
            syncFabVisibility();
            maybeAutoOpenTutorial();
        });
    }

    window.initializeHelpTutorial = initializePage;

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', function () {
            initializePage();
        });
        return;
    }

    initializePage();
})();
