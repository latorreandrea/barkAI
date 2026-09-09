/* Global navbar behaviour, shared by every page (chat + error pages).
 * Loaded once from templates/base.html with `defer`, then cached by the
 * browser. The home URL is read from the brand link's href instead of being
 * rendered into the script by Django, so this file stays fully static. */
(function () {
    "use strict";

    var brandLink = document.getElementById("nav-brand");
    var newChatBtn = document.getElementById("nav-new-chat");
    var ctaEl = document.getElementById("nav-interview-cta");

    // The brand link always carries the chat home URL ({% url 'chat:index' %});
    // fall back to "/" only if the markup is ever removed.
    var homeUrl = brandLink ? brandLink.getAttribute("href") : "/";

    // "New Chat": drop the persisted session, then land on a fresh chat screen.
    function startNewChat() {
        try {
            localStorage.removeItem("barkai.session_id");
        } catch (err) {
            /* localStorage may be unavailable (private mode); ignore. */
        }
        window.location.href = homeUrl;
    }

    if (newChatBtn) {
        newChatBtn.addEventListener("click", startNewChat);
    }

    // "Request Interview": on the chat page pre-fill + focus the composer so the
    // mascot can flag the request; everywhere else the default link wins.
    if (ctaEl) {
        ctaEl.addEventListener("click", function (event) {
            var input = document.getElementById("chat-input");
            if (!input) {
                return; // Not on the chat screen: fall back to the href.
            }
            event.preventDefault();
            input.value = "I would like to schedule an interview with Andrea.";
            input.focus();
        });
    }
})();
