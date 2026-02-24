(function () {
    const MODE_STORAGE_KEY = 'hatchup_mode';
    const MODE_STORAGE_KEY_LEGACY = 'mode';
    const MODE_SESSION_KEY = 'hatchup_mode_session';

    const state = {
        mode: 'vc',
        modeLoading: true,
    };
    const listeners = new Set();

    function normalizeMode(mode) {
        return mode === 'founder' ? 'founder' : 'vc';
    }

    function readFromStorage(storage, key) {
        try {
            return storage.getItem(key);
        } catch (_) {
            return null;
        }
    }

    function writeToStorage(storage, key, value) {
        try {
            storage.setItem(key, value);
        } catch (_) {
            // Ignore storage availability errors.
        }
    }

    function getStoredMode() {
        const sessionMode = readFromStorage(sessionStorage, MODE_SESSION_KEY);
        if (sessionMode) {
            return normalizeMode(sessionMode);
        }
        const mode = readFromStorage(localStorage, MODE_STORAGE_KEY)
            || readFromStorage(localStorage, MODE_STORAGE_KEY_LEGACY);
        return mode ? normalizeMode(mode) : null;
    }

    function persistMode(mode) {
        writeToStorage(localStorage, MODE_STORAGE_KEY, mode);
        writeToStorage(localStorage, MODE_STORAGE_KEY_LEGACY, mode);
        writeToStorage(sessionStorage, MODE_SESSION_KEY, mode);
    }

    function notify() {
        const snapshot = { ...state };
        listeners.forEach((listener) => {
            try {
                listener(snapshot);
            } catch (_) {
                // Keep mode updates resilient to listener failures.
            }
        });
        window.dispatchEvent(new CustomEvent('hatchup:modechange', { detail: snapshot }));
    }

    function setMode(mode, options = {}) {
        const { persist = true } = options;
        const nextMode = normalizeMode(mode);
        const changed = state.mode !== nextMode || state.modeLoading;
        state.mode = nextMode;
        state.modeLoading = false;
        if (persist) {
            persistMode(nextMode);
        }
        if (changed) {
            notify();
        }
        return nextMode;
    }

    function startModeLoading() {
        if (!state.modeLoading) {
            state.modeLoading = true;
            notify();
        }
    }

    function resolveMode(fallbackMode = 'vc') {
        const storedMode = getStoredMode();
        return setMode(storedMode || normalizeMode(fallbackMode));
    }

    function subscribeMode(listener) {
        if (typeof listener !== 'function') {
            return function () { };
        }
        listeners.add(listener);
        return function () {
            listeners.delete(listener);
        };
    }

    window.HatchupAppState = {
        normalizeMode,
        getStoredMode,
        persistMode,
        setMode,
        resolveMode,
        startModeLoading,
        subscribeMode,
        getMode: function () {
            return state.mode;
        },
        isModeLoading: function () {
            return state.modeLoading;
        },
        getState: function () {
            return { ...state };
        },
    };
})();
