(function () {
    const STORAGE_KEY = "hatchup_mobile_notice_dismissed";
    const MOBILE_QUERY = "(max-width: 768px)";
    const MOBILE_UA_REGEX = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i;

    function isMobileContext() {
        const smallScreen = window.matchMedia(MOBILE_QUERY).matches;
        const userAgent = navigator.userAgent || navigator.vendor || window.opera || "";
        return smallScreen || MOBILE_UA_REGEX.test(userAgent);
    }

    function hasDismissed() {
        try {
            return localStorage.getItem(STORAGE_KEY) === "1";
        } catch (error) {
            return false;
        }
    }

    function storeDismissedPreference() {
        try {
            localStorage.setItem(STORAGE_KEY, "1");
        } catch (error) {
            // Ignore storage failures (private mode, blocked storage, etc.).
        }
    }

    function createNoticeElement() {
        const container = document.createElement("div");
        container.id = "mobile-desktop-notice";
        container.className = "mobile-desktop-notice is-hidden";
        container.setAttribute("role", "dialog");
        container.setAttribute("aria-modal", "false");
        container.setAttribute("aria-labelledby", "mobile-desktop-notice-title");
        container.setAttribute("aria-hidden", "true");

        container.innerHTML = [
            '<div class="mobile-desktop-notice-card">',
            '<p class="mobile-desktop-notice-kicker">Device Recommendation</p>',
            '<h2 id="mobile-desktop-notice-title">Best experienced on desktop</h2>',
            '<p class="mobile-desktop-notice-copy">HatchUp is optimized for larger screens. For the best experience, please switch to a desktop or laptop.</p>',
            '<div class="mobile-desktop-notice-actions">',
            '<button type="button" class="mobile-desktop-notice-btn secondary" data-mobile-notice-dismiss="true">Continue Anyway</button>',
            '<a class="mobile-desktop-notice-btn ghost" href="/terms">Learn More</a>',
            "</div>",
            "</div>"
        ].join("");

        return container;
    }

    function setNoticeVisibility(noticeElement, shouldShow) {
        if (!noticeElement) return;
        noticeElement.classList.toggle("is-hidden", !shouldShow);
        noticeElement.setAttribute("aria-hidden", shouldShow ? "false" : "true");
    }

    function initializeMobileNotice() {
        let noticeElement = document.getElementById("mobile-desktop-notice");
        if (!noticeElement) {
            noticeElement = createNoticeElement();
            document.body.appendChild(noticeElement);
        }

        const dismissButton = noticeElement.querySelector("[data-mobile-notice-dismiss='true']");
        if (dismissButton && !dismissButton.dataset.bound) {
            dismissButton.dataset.bound = "true";
            dismissButton.addEventListener("click", () => {
                storeDismissedPreference();
                setNoticeVisibility(noticeElement, false);
            });
        }

        if (hasDismissed()) {
            setNoticeVisibility(noticeElement, false);
            return;
        }

        setNoticeVisibility(noticeElement, isMobileContext());
    }

    document.addEventListener("DOMContentLoaded", initializeMobileNotice);
})();
