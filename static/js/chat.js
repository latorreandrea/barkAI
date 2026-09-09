(function () {
    "use strict";
    // Session + onboarding keys persisted in localStorage.
    var STORAGE_KEY = "barkai.session_id";
    var VISITED_KEY = "barkai_visited";

    // ================================================================ //
    // 1) SESSION: reuse ?session_id= when given, otherwise generate    //
    //    and persist a UUID (the chat survives reloads).               //
    // ================================================================ //
    var bodyEl = document.body;

    function generateSessionId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        // RFC4122 v4 fallback for browsers without crypto.randomUUID.
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
            var r = (Math.random() * 16) | 0;
            var v = c === "x" ? r : (r & 0x3) | 0x8;
            return v.toString(16);
        });
    }

    var sessionId = bodyEl.getAttribute("data-session-id") || localStorage.getItem(STORAGE_KEY);
    if (!sessionId) {
        sessionId = generateSessionId();
    }
    localStorage.setItem(STORAGE_KEY, sessionId);

    // First visit: the onboarding flag has never been written yet.
    var isFirstVisit = localStorage.getItem(VISITED_KEY) === null;

    // ================================================================ //
    // 2) DOM REFERENCES                                                //
    // ================================================================ //
    var mediaUrl = bodyEl.getAttribute("data-media-url"); // e.g. "/static/mascot/"
    var videos = Array.prototype.slice.call(document.querySelectorAll("video.js-mascot-video"));
    var statusEls = Array.prototype.slice.call(document.querySelectorAll("[data-mascot-status]"));
    var threadEl = document.getElementById("message-thread");
    var formEl = document.getElementById("chat-form");
    var inputEl = document.getElementById("chat-input");
    var sendBtn = document.getElementById("chat-send");
    var sessionChip = document.getElementById("session-chip");
    var heroEl = document.getElementById("hero-onboarding");
    var heroHintEl = document.getElementById("hero-scroll-hint");

    if (sessionChip) {
        sessionChip.textContent = sessionId.slice(0, 8) + "…";
    }

    // ================================================================ //
    // 3) MASCOT STATE MACHINE: swaps the <video> src + status labels.  //
    // ================================================================ //
    var STATES = {
        idle: "BarklAI is ready — ask me anything!",
        sniffing: "BarklAI caught your scent — coming closer…",
        searching: "BarklAI is searching repositories…",
        typing: "BarklAI is typing…",
        speaking: "BarklAI is speaking…",
        celebrating: "BarklAI found an interview opportunity! 🎉"
    };

    function setMascotState(state) {
        if (!STATES.hasOwnProperty(state)) {
            state = "idle";
        }
        var src = mediaUrl + state + ".mp4";
        videos.forEach(function (video) {
            var shell = video.closest(".js-video-shell");
            if (shell) {
                shell.classList.remove("is-missing");
            }
            if (video.getAttribute("src") !== src) {
                video.setAttribute("src", src);
                video.load();
                video.play()["catch"](function () {
                    // Autoplay can be blocked before the first user gesture.
                });
            }
        });
        statusEls.forEach(function (el) {
            el.textContent = STATES[state];
        });
    }

    // When a reaction MP4 is missing, show the emoji fallback instead of a black frame.
    videos.forEach(function (video) {
        video.addEventListener("error", function () {
            var shell = video.closest(".js-video-shell");
            if (shell) {
                shell.classList.add("is-missing");
            }
        });
    });

    // ================================================================ //
    // 4) MESSAGE RENDERING (textContent => safe against injection)     //
    // ================================================================ //
    function addMessage(sender, content) {
        var isUser = sender === "user";
        var row = document.createElement("div");
        row.className = "flex " + (isUser ? "justify-end" : "justify-start");

        var bubble = document.createElement("div");
        bubble.className = "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-md md:max-w-[75%] " +
            (isUser ? "rounded-br-sm bg-amber-500 text-slate-950"
                    : "rounded-bl-sm bg-white/10 text-slate-100 ring-1 ring-white/10");

        var meta = document.createElement("div");
        meta.className = "mb-1 text-[10px] font-semibold uppercase tracking-wide " +
            (isUser ? "text-amber-900/80" : "text-amber-300/80");
        meta.textContent = isUser ? "You" : "BarklAI 🐾";

        var text = document.createElement("p");
        text.textContent = content; // textContent prevents HTML injection.

        bubble.appendChild(meta);
        bubble.appendChild(text);
        row.appendChild(bubble);
        threadEl.appendChild(row);
        scrollToBottom();
    }

    function scrollToBottom() {
        threadEl.scrollTop = threadEl.scrollHeight;
    }

    // ================================================================ //
    // 5) CSRF HELPER (reads the Django csrftoken cookie)               //
    // ================================================================ //
    function getCookie(name) {
        var prefix = name + "=";
        var parts = document.cookie.split(";");
        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim();
            if (part.indexOf(prefix) === 0) {
                return decodeURIComponent(part.slice(prefix.length));
            }
        }
        return null;
    }

    // ================================================================ //
    // 6) FIRST-VISIT ONBOARDING: staggered hero, sniffing, typed hello //
    // ================================================================ //
    var HERO_GREETING = "Woof! Hello there! I'm BarklAI. I just caught your scent! " +
        "What would you like to know about Andrea's software development career and projects?";
    var REVISITOR_GREETING = "Woof! 👋 I'm BarklAI, Andrea's AI career companion. " +
        "Ask me about her open-source projects, Python/Django experience, or RAG pipelines — " +
        "or request an interview right here!";
    var heroDismissed = false;

    // Trigger the staggered fade-up of the hero headline, subtitle and hint.
    function revealHero() {
        // requestAnimationFrame lets the browser paint the overlay first, so the
        // reveal animations always run (elements start with opacity: 0).
        window.requestAnimationFrame(function () {
            heroEl.classList.add("is-ready");
        });
    }

    function startOnboarding() {
        heroEl.hidden = false; // Reveal the fullscreen hero for first-time visitors.
        revealHero();
        window.addEventListener("wheel", handleScrollIntent, { passive: true });
        window.addEventListener("touchmove", handleScrollIntent, { passive: true });
        window.addEventListener("keydown", handleScrollIntent);
        if (heroHintEl) {
            heroHintEl.addEventListener("click", dismissOnboarding);
        }
    }

    function handleScrollIntent(event) {
        if (event.type === "wheel" && event.deltaY <= 0) {
            return; // Ignore upward wheel gestures.
        }
        if (event.type === "keydown") {
            if (event.key !== "ArrowDown" && event.key !== "PageDown" && event.key !== " ") {
                return;
            }
            event.preventDefault();
        }
        dismissOnboarding();
    }

    function dismissOnboarding() {
        if (heroDismissed) {
            return;
        }
        heroDismissed = true;
        localStorage.setItem(VISITED_KEY, "true");

        // BarklAI moves closer and "sniffs" the new recruiter.
        setMascotState("sniffing");

        // Smooth full-viewport slide-out towards the chat section underneath.
        // The [hidden] rule in base.html guarantees the overlay stays hidden
        // once the transition finishes (flex must never override hidden).
        heroEl.classList.add("is-leaving");
        window.setTimeout(function () {
            heroEl.hidden = true;
            heroEl.classList.remove("is-ready", "is-leaving");
        }, 900);

        // Once BarklAI stops sniffing he speaks the welcome message word by
        // word, then the intermittent scroll invitation appears below it.
        window.setTimeout(function () {
            if (threadEl && threadEl.children.length === 0) {
                setMascotState("speaking");
                addTypedMessage(HERO_GREETING, showChatPrompt);
            } else {
                setMascotState("idle");
            }
        }, 2600);
    }

    // Render an assistant message whose words fade in one by one. Words are
    // inserted with textContent inside <span>s => safe against HTML injection.
    function addTypedMessage(text, onComplete) {
        var row = document.createElement("div");
        row.className = "flex justify-start";

        var bubble = document.createElement("div");
        bubble.className = "max-w-[85%] rounded-2xl rounded-bl-sm bg-white/10 px-4 py-3 text-sm leading-relaxed text-slate-100 shadow-md ring-1 ring-white/10 md:max-w-[75%]";

        var meta = document.createElement("div");
        meta.className = "mb-1 text-[10px] font-semibold uppercase tracking-wide text-amber-300/80";
        meta.textContent = "BarklAI 🐾";

        var body = document.createElement("p");
        bubble.appendChild(meta);
        bubble.appendChild(body);
        row.appendChild(bubble);
        threadEl.appendChild(row);

        var words = text.split(" ");
        var index = 0;
        var intervalId = window.setInterval(function () {
            if (index >= words.length) {
                window.clearInterval(intervalId);
                scrollToBottom();
                if (typeof onComplete === "function") {
                    onComplete();
                }
                return;
            }
            var word = document.createElement("span");
            word.className = "word-fade";
            word.textContent = (index > 0 ? " " : "") + words[index];
            body.appendChild(word);
            scrollToBottom(); // Keep the typed message in view while it grows.
            index += 1;
        }, 70);
    }

    // Intermittent pulsing invitation shown once the first greeting is done.
    function showChatPrompt() {
        if (!threadEl || document.getElementById("chat-prompt")) {
            return;
        }
        var prompt = document.createElement("p");
        prompt.id = "chat-prompt";
        prompt.className = "pt-1 text-center text-[11px] font-medium tracking-wide text-amber-300/80";
        prompt.textContent = "Scroll down to keep chatting with BarklAI…";
        threadEl.appendChild(prompt);
        scrollToBottom();
    }

    function hideChatPrompt() {
        var prompt = document.getElementById("chat-prompt");
        if (prompt) {
            prompt.remove();
        }
    }

    // ================================================================ //
    // 7) SEND MESSAGE -> POST /api/chat/send                           //
    // ================================================================ //
    function setBusy(busy) {
        formEl.dataset.busy = busy ? "true" : "false";
        inputEl.disabled = busy;
        sendBtn.disabled = busy;
        if (!busy) {
            inputEl.focus();
        }
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text || formEl.dataset.busy === "true") {
            return;
        }

        hideChatPrompt(); // The pulsing invitation disappears when chatting begins.

        addMessage("user", text);
        inputEl.value = "";
        setBusy(true);
        setMascotState("searching"); // BarklAI visibly searches while the API works.

        try {
            var response = await fetch("/api/chat/send", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken")
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    message: text
                })
            });
            if (!response.ok) {
                throw new Error("server returned HTTP " + response.status);
            }
            var data = await response.json();
            addMessage("assistant", data.reply);
            // Interview requests make BarklAI celebrate; everything else = speaking.
            setMascotState(data.interview_requested ? "celebrating" : "speaking");
        } catch (err) {
            addMessage("assistant", "Woof… sorry, I could not reach my backend (" + err.message + "). Please try again.");
            setMascotState("idle");
        } finally {
            setBusy(false);
        }
    }

    // ================================================================ //
    // 8) QUICK QUESTIONS: fill the composer and submit immediately.    //
    // ================================================================ //
    function wireSuggestions() {
        var buttons = Array.prototype.slice.call(document.querySelectorAll("[data-suggestion]"));
        buttons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (formEl.dataset.busy === "true") {
                    return;
                }
                inputEl.value = btn.getAttribute("data-suggestion");
                sendMessage();
            });
        });
    }

    // ================================================================ //
    // 9) BOOTSTRAP: load the persisted history for this session.       //
    // ================================================================ //
    async function loadHistory() {
        try {
            var response = await fetch("/api/chat/history/" + encodeURIComponent(sessionId));
            if (!response.ok) {
                throw new Error("server returned HTTP " + response.status);
            }
            var data = await response.json();
            data.messages.forEach(function (message) {
                addMessage(message.sender, message.content);
            });

            // Recurring visitors with an empty session get a spoken hello.
            if (data.messages.length === 0 && !isFirstVisit) {
                addMessage("assistant", REVISITOR_GREETING);
            }
            if (data.interview_requested) {
                setMascotState("celebrating");
            } else if (data.messages.length === 0 && !isFirstVisit) {
                setMascotState("speaking");
            }
        } catch (err) {
            addMessage("assistant", "Woof… I could not load the conversation history (" + err.message + ").");
        }
    }

    async function init() {
        setMascotState("idle");

        if (isFirstVisit) {
            // First-time visitor: show the onboarding hero and wait for a scroll.
            if (heroEl) {
                startOnboarding();
            }
        } else if (heroEl) {
            // Recurring visitor: skip onboarding and go straight to the chat.
            heroEl.hidden = true;
        }

        // Load history in the background (empty for a brand-new session).
        await loadHistory();

        if (!isFirstVisit && inputEl) {
            inputEl.focus();
        }
    }

    // ================================================================ //
    // 10) EVENT WIRING                                                 //
    // ================================================================ //
    formEl.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage();
    });
    wireSuggestions();

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
