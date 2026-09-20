/* Global navbar behaviour, shared by every page (chat + error pages).
 * Loaded once from templates/base.html with `defer`, then cached by the
 * browser. The home URL is read from the brand link's href instead of being
 * rendered into the script by Django, so this file stays fully static. */
(function () {
    "use strict";

    var SESSION_KEY = "barkai.session_id";
    var brandLink = document.getElementById("nav-brand");
    var newChatBtn = document.getElementById("nav-new-chat");
    var ctaEl = document.getElementById("nav-interview-cta");
    var deleteSessionBtn = document.getElementById("delete-session");

    // The brand link always carries the chat home URL ({% url 'chat:index' %});
    // fall back to "/" only if the markup is ever removed.
    var homeUrl = brandLink ? brandLink.getAttribute("href") : "/";

    function storedSessionId() {
        try {
            return localStorage.getItem(SESSION_KEY) || "";
        } catch (err) {
            return ""; // Private mode: nothing is stored, nothing to erase.
        }
    }

    function forgetSession() {
        try {
            localStorage.removeItem(SESSION_KEY);
        } catch (err) {
            /* localStorage may be unavailable (private mode); ignore. */
        }
    }

    // The chat API and the erasure endpoint are CSRF-protected; the token rides
    // in the cookie the chat page's {% csrf_token %} sets.
    function csrfToken() {
        var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    // "New Chat": drop the persisted session, then land on a fresh chat screen.
    function startNewChat() {
        forgetSession();
        window.location.href = homeUrl;
    }

    if (newChatBtn) {
        newChatBtn.addEventListener("click", startNewChat);
    }

    // "Delete my conversation" (footer, on every page): erase the session in the
    // database, drop the local pointer, then land on a fresh chat. It is hidden
    // while there is no conversation to erase — so /privacy/ and the error pages
    // never show a dead button — and that check waits for DOMContentLoaded
    // because chat.js, which mints the session id on the chat page, is deferred
    // *after* this file.
    if (deleteSessionBtn) {
        window.addEventListener("DOMContentLoaded", function () {
            deleteSessionBtn.hidden = storedSessionId() === "";
        });
        deleteSessionBtn.addEventListener("click", function () {
            var sessionId = storedSessionId();
            if (!sessionId) {
                return; // Nothing to erase.
            }
            var question = deleteSessionBtn.getAttribute("data-confirm-message") ||
                "Delete this conversation? This cannot be undone.";
            if (!window.confirm(question)) {
                return;
            }
            fetch("/session/delete/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken()
                },
                body: JSON.stringify({ session_id: sessionId })
            })["catch"](function () {
                /* Network hiccup: still drop the local session below. */
            }).then(function () {
                forgetSession();
                window.location.href = homeUrl;
            });
        });
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
