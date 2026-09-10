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
    var messageListEl = document.getElementById("message-list");
    var threadEl = document.getElementById("message-thread");
    var formEl = document.getElementById("chat-form");
    var inputEl = document.getElementById("chat-input");
    var sendBtn = document.getElementById("chat-send");
    var sessionChip = document.getElementById("session-chip");
    var heroEl = document.getElementById("hero-onboarding");
    var heroHintEl = document.getElementById("hero-scroll-hint");
    var heroSteps = Array.prototype.slice.call(document.querySelectorAll("[data-hero-step]"));
    var barkOnomatopoeiaEl = document.getElementById("bark-onomatopoeia");
    var bubbleTextEl = document.getElementById("speech-bubble-text");
    var bubbleScrollEl = document.getElementById("speech-bubble-scroll");
    var promptEl = document.getElementById("chat-prompt");
    var suggestionRailEl = document.getElementById("suggestion-rail");

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
    // 4) SPEECH BUBBLE (the "live" comic nuvoletta).                   //
    //    It holds BarklAI's current utterance OR a transient progress  //
    //    label ("BarklAI is searching"). It never holds chat history.  //
    // ================================================================ //

    // Text of the BarklAI message currently occupying the bubble. Null means
    // the bubble only shows an idle hint or a transient progress label.
    var activeBubbleText = null;
    var typeTimer = null;

    function bubbleIsMessage() {
        return typeof activeBubbleText === "string" && activeBubbleText.length > 0;
    }

    function setBubbleContent(node, idle) {
        if (typeTimer) {
            window.clearInterval(typeTimer);
            typeTimer = null;
        }
        bubbleTextEl.classList.remove("bubble-msg-leaving");
        if (idle) {
            bubbleTextEl.classList.add("is-idle");
        } else {
            bubbleTextEl.classList.remove("is-idle");
        }
        bubbleTextEl.textContent = "";
        bubbleTextEl.appendChild(node);
        bubbleScrollEl.scrollTop = bubbleScrollEl.scrollHeight;
    }

    // Idle placeholder shown while there is nothing live to say yet.
    function showBubbleIdle() {
        activeBubbleText = null;
        setBubbleContent(document.createTextNode(STATES.idle), true);
    }

    // Transient progress state, e.g. "BarklAI is searching" + bouncing dots.
    function showBubbleProgress(label) {
        activeBubbleText = null;
        var frag = document.createDocumentFragment();
        frag.appendChild(document.createTextNode(label + " "));
        var dots = document.createElement("span");
        dots.className = "bubble-dots";
        dots.setAttribute("aria-hidden", "true");
        for (var i = 0; i < 3; i += 1) {
            dots.appendChild(document.createElement("i"));
        }
        frag.appendChild(dots);
        setBubbleContent(frag, false);
    }

    // Print a BarklAI message into the bubble word by word (typewriter fade).
    // Words are inserted with textContent inside <span>s => injection-safe.
    function typeBubbleMessage(text) {
        return new Promise(function (resolve) {
            var words = text.split(" ");
            var index = 0;
            activeBubbleText = text;
            setBubbleContent(document.createTextNode(""), false);
            if (words.length === 1 && words[0] === "") {
                resolve();
                return;
            }
            // Adaptive pace: fast enough for long replies, still legible short ones.
            var totalMs = Math.min(6000, Math.max(1400, words.length * 45));
            var delay = Math.max(18, Math.round(totalMs / words.length));
            typeTimer = window.setInterval(function () {
                if (index >= words.length) {
                    window.clearInterval(typeTimer);
                    typeTimer = null;
                    bubbleScrollEl.scrollTop = bubbleScrollEl.scrollHeight;
                    resolve();
                    return;
                }
                var word = document.createElement("span");
                word.className = "word-fade";
                word.textContent = (index > 0 ? " " : "") + words[index];
                bubbleTextEl.appendChild(word);
                bubbleScrollEl.scrollTop = bubbleScrollEl.scrollHeight;
                index += 1;
            }, delay);
        });
    }

    // ================================================================ //
    // 5) CHAT HISTORY RENDERING (message rows inside #message-list).   //
    // ================================================================ //

    function scrollThreadToBottom() {
        threadEl.scrollTop = threadEl.scrollHeight;
    }

    function addMessageRow(sender, content, animateIn) {
        var isUser = sender === "user";
        var row = document.createElement("div");
        row.className = "flex " + (isUser ? "justify-end" : "justify-start");

        var bubble = document.createElement("div");
        bubble.className = "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed " +
            (isUser ? "rounded-br-sm bg-amber-500 text-slate-950"
                    : "rounded-bl-sm border-2 border-slate-900 bg-white text-slate-900 " +
                      "shadow-[3px_3px_0_0_#0f172a]");
        if (animateIn) {
            bubble.classList.add("history-row-in");
        }

        var meta = document.createElement("div");
        meta.className = "mb-1 text-[10px] font-semibold uppercase tracking-wide " +
            (isUser ? "text-amber-900/80" : "text-amber-700");
        meta.textContent = isUser ? "You" : "BarklAI 🐾";

        var text = document.createElement("p");
        text.className = "whitespace-pre-wrap";
        text.textContent = content; // textContent prevents HTML injection.

        bubble.appendChild(meta);
        bubble.appendChild(text);
        row.appendChild(bubble);
        messageListEl.appendChild(row);
        scrollThreadToBottom();
    }

    // Hand-off: the utterance currently in the bubble fades/slides OUT of it
    // while the very same message is appended to the bottom of the history,
    // so it visibly "moves up" into the conversation transcript.
    function flushBubbleToHistory() {
        return new Promise(function (resolve) {
            if (!bubbleIsMessage()) {
                resolve();
                return;
            }
            var text = activeBubbleText;
            activeBubbleText = null;
            bubbleTextEl.classList.add("bubble-msg-leaving");
            addMessageRow("assistant", text, true);
            window.setTimeout(function () {
                bubbleTextEl.classList.remove("bubble-msg-leaving");
                bubbleTextEl.textContent = "";
                resolve();
            }, 430);
        });
    }

    // ================================================================ //
    // 6) CSRF HELPER (reads the Django csrftoken cookie)               //
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
    // 7) COMPOSER HINT + SUGGESTION RAIL                               //
    // ================================================================ //
    function showChatPrompt() {
        if (promptEl) {
            promptEl.hidden = false;
        }
    }

    function hideChatPrompt() {
        if (promptEl) {
            promptEl.hidden = true;
        }
    }

    function hideSuggestionRail() {
        if (suggestionRailEl) {
            suggestionRailEl.classList.add("hidden");
        }
    }

    // Quick-prompt chips stay visible only while the conversation is empty.
    function refreshSuggestionRail() {
        if (messageListEl.children.length > 0) {
            hideSuggestionRail();
        }
    }

    // ================================================================ //
    // 8) FIRST-VISIT ONBOARDING: hero lines -> sniffing -> woof ->      //
    //    two spoken intro messages (scripted, never persisted).        //
    // ================================================================ //
    var ONBOARDING_MESSAGE_1 = "Woof! Wait... [sniff, sniff]... I smell clean code and " +
        "new opportunities! Hi! I'm BarkAI. What brings you here? Are you looking for " +
        "the right dev for your team?";
    var ONBOARDING_MESSAGE_2 = "Perfect! Then you're in the right place. If you want to " +
        "learn more about Andrea's work, his skills, or chat about his projects (or even " +
        "figure out how he can help you solve a specific technical challenge), just tell " +
        "me: I'm all ears!";
    var REVISITOR_GREETING = "Woof! 👋 I'm BarklAI, Andrea's AI career companion. " +
        "Ask me about his open-source projects, Python/Django experience, or RAG pipelines — " +
        "or request an interview right here!";

    // Message 2 automatically follows message 1 after this pause.
    var SECOND_MESSAGE_DELAY_MS = 3000;
    // How long each hero welcome line stays on screen before fading out.
    var HERO_STEP_HOLD_MS = 3200;

    var heroDismissed = false;
    var heroAwaitingScroll = false;
    var onboardingBusy = false;
    var secondMessageTimer = null;
    var heroTimers = [];

    function clearHeroTimers() {
        heroTimers.forEach(function (timer) {
            window.clearTimeout(timer);
        });
        heroTimers = [];
    }

    function showHeroStep(name) {
        heroSteps.forEach(function (step) {
            if (step.getAttribute("data-hero-step") === name) {
                step.classList.remove("is-leaving");
                step.classList.add("is-active");
            } else {
                step.classList.remove("is-active");
            }
        });
    }

    function hideHeroStep(name) {
        heroSteps.forEach(function (step) {
            if (step.getAttribute("data-hero-step") === name) {
                step.classList.remove("is-active");
                step.classList.add("is-leaving");
            }
        });
    }

    // Fade in the two welcome lines in sequence, then wait for the visitor to
    // scroll so the mascot stage can take over.
    function playHeroIntro() {
        showHeroStep("1");
        heroTimers.push(window.setTimeout(function () {
            hideHeroStep("1");
            heroTimers.push(window.setTimeout(function () {
                showHeroStep("2");
                heroAwaitingScroll = true; // A scroll/click may now dismiss the hero.
            }, 500));
        }, HERO_STEP_HOLD_MS));
    }

    function startOnboarding() {
        heroEl.hidden = false; // Reveal the fullscreen hero for first-time visitors.
        playHeroIntro();
        window.addEventListener("wheel", handleScrollIntent, { passive: true });
        window.addEventListener("touchmove", handleScrollIntent, { passive: true });
        window.addEventListener("keydown", handleScrollIntent);
        if (heroHintEl) {
            heroHintEl.addEventListener("click", dismissOnboarding);
        }
    }

    function handleScrollIntent(event) {
        if (heroDismissed || !heroAwaitingScroll) {
            // Ignore gestures once the hero is gone or before it awaits a scroll.
            return;
        }
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

    // Welcome the visitor directly in the central bubble (never in the history).
    // Returns a promise that resolves once the whole utterance has been typed.
    function greetInBubble(text) {
        refreshSuggestionRail();
        if (messageListEl.children.length > 0 || bubbleIsMessage()) {
            setMascotState("idle");
            return Promise.resolve();
        }
        setMascotState("speaking");
        setBusy(true);
        return typeBubbleMessage(text).then(function () {
            setBusy(false);
            showChatPrompt();
        });
    }

    function dismissOnboarding() {
        if (heroDismissed) {
            return;
        }
        heroDismissed = true;
        heroAwaitingScroll = false;
        localStorage.setItem(VISITED_KEY, "true");

        clearHeroTimers();
        onboardingBusy = true;

        // Step 3: the comic "Sniff sniff" onomatopoeia flashes before the dog.
        hideHeroStep("2");
        window.setTimeout(function () {
            showHeroStep("3");
        }, 450);

        // Then the whole overlay fades away and BarklAI takes the stage. The
        // [hidden] rule guarantees it stays hidden once the transition ends.
        window.setTimeout(function () {
            hideHeroStep("3");
            heroEl.classList.add("is-leaving");
            window.setTimeout(function () {
                heroEl.hidden = true;
                heroEl.classList.remove("is-leaving");
                heroSteps.forEach(function (step) {
                    step.classList.remove("is-active", "is-leaving");
                });
            }, 750);
            startSniffingSequence();
        }, 1900);
    }

    // BarklAI sniffs the newcomer; the "Woof!" pops near the end of the clip,
    // then he introduces himself straight into the comic speech bubble.
    function startSniffingSequence() {
        setMascotState("sniffing");
        refreshSuggestionRail();
        popBarkWhenSniffingEnds(function () {
            window.setTimeout(function () {
                greetInBubble(ONBOARDING_MESSAGE_1).then(scheduleSecondMessage);
            }, 1400);
        });
    }

    // Fire `onBark` once, when the sniffing clip is ~80% through (falls back to
    // a fixed delay when the clip length is unknown).
    function popBarkWhenSniffingEnds(onBark) {
        var video = videos[0];
        var fired = false;

        function popBark() {
            if (fired) {
                return;
            }
            fired = true;
            if (barkOnomatopoeiaEl) {
                barkOnomatopoeiaEl.classList.remove("is-visible");
                void barkOnomatopoeiaEl.offsetWidth; // Restart the CSS animation.
                barkOnomatopoeiaEl.classList.add("is-visible");
            }
            if (onBark) {
                onBark();
            }
        }

        if (!video) {
            window.setTimeout(popBark, 2600);
            return;
        }
        video.addEventListener("timeupdate", function () {
            if (fired || !video.duration || !isFinite(video.duration)) {
                return;
            }
            if (video.currentTime >= video.duration * 0.8) {
                popBark();
            }
        });
        window.setTimeout(popBark, 8000); // Safety net for very short clips.
    }

    // Message 2 lands automatically a few seconds after message 1.
    function scheduleSecondMessage() {
        if (secondMessageTimer) {
            window.clearTimeout(secondMessageTimer);
        }
        secondMessageTimer = window.setTimeout(function () {
            secondMessageTimer = null;
            // Only speak if the conversation has not moved on in the meantime.
            if (!bubbleIsMessage() || activeBubbleText !== ONBOARDING_MESSAGE_1) {
                return;
            }
            setMascotState("speaking");
            setBusy(true);
            flushBubbleToHistory()
                .then(function () {
                    return typeBubbleMessage(ONBOARDING_MESSAGE_2);
                })
                .then(function () {
                    onboardingBusy = false;
                    setBusy(false);
                    showChatPrompt();
                });
        }, SECOND_MESSAGE_DELAY_MS);
    }

    // Cancel the pending message-2 reveal once the visitor starts chatting.
    function cancelSecondMessage() {
        if (secondMessageTimer) {
            window.clearTimeout(secondMessageTimer);
            secondMessageTimer = null;
        }
    }

    // ================================================================ //
    // 9) SEND MESSAGE -> POST /api/chat/send                           //
    // ================================================================ //
    function setBusy(busy) {
        formEl.dataset.busy = busy ? "true" : "false";
        inputEl.disabled = busy;
        sendBtn.disabled = busy;
        if (!busy) {
            inputEl.focus();
        }
    }

    function requestReply(text) {
        return fetch("/api/chat/send", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken")
            },
            body: JSON.stringify({
                session_id: sessionId,
                message: text
            })
        }).then(function (response) {
            if (!response.ok) {
                throw new Error("server returned HTTP " + response.status);
            }
            return response.json();
        });
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text || formEl.dataset.busy === "true") {
            return;
        }

        // The visitor is chatting: drop the scripted message-2 reveal, if pending.
        cancelSecondMessage();
        onboardingBusy = false;

        hideChatPrompt();
        hideSuggestionRail();
        inputEl.value = "";
        setBusy(true);

        // 1) The previous live utterance moves up into the history while the
        //    user's new message is appended right below it.
        var flushPromise = flushBubbleToHistory();
        addMessageRow("user", text, false);

        // 2) BarklAI visibly searches; the bubble shows the progress state as
        //    soon as the previous answer has finished moving up.
        setMascotState("searching");
        var requestDone = false;
        var requestPromise = requestReply(text).then(function (data) {
            requestDone = true;
            return data;
        }, function (err) {
            requestDone = true;
            throw err;
        });
        flushPromise.then(function () {
            if (!requestDone) {
                showBubbleProgress(STATES.searching.replace(/…$/, ""));
            }
        });

        try {
            var data = await requestPromise;
            await flushPromise; // Never type the new reply over the old bubble copy.
            setMascotState(data.interview_requested ? "celebrating" : "speaking");
            await typeBubbleMessage(data.reply);
        } catch (err) {
            await flushPromise.catch(function () { return null; });
            setMascotState("idle");
            await typeBubbleMessage(
                "Woof… sorry, I could not reach my backend (" +
                (err && err.message ? err.message : err) +
                "). Please try again."
            );
        } finally {
            setBusy(false);
        }
    }

    // ================================================================ //
    // 10) BOOTSTRAP: restore the persisted history for this session.   //
    //     Everything except the FINAL assistant message is rendered as //
    //     history; that final reply becomes the live bubble content.   //
    // ================================================================ //
    async function loadHistory() {
        try {
            var response = await fetch("/api/chat/history/" + encodeURIComponent(sessionId));
            if (!response.ok) {
                throw new Error("server returned HTTP " + response.status);
            }
            var data = await response.json();
            var messages = data.messages.slice();

            // The last assistant reply is the "live" one: park it in the bubble.
            var bubbleContent = null;
            if (messages.length && messages[messages.length - 1].sender === "assistant") {
                bubbleContent = messages.pop().content;
            }
            messages.forEach(function (message) {
                addMessageRow(message.sender, message.content, false);
            });
            refreshSuggestionRail();

            if (data.messages.length === 0 && !isFirstVisit) {
                // Recurring visitor with an empty session: warm spoken hello.
                greetInBubble(REVISITOR_GREETING);
            } else if (bubbleContent !== null) {
                activeBubbleText = bubbleContent;
                setBubbleContent(document.createTextNode(bubbleContent), false);
                setMascotState(data.interview_requested ? "celebrating" : "idle");
            } else if (!onboardingBusy) {
                showBubbleIdle();
                setMascotState(data.interview_requested ? "celebrating" : "idle");
            }
        } catch (err) {
            showBubbleIdle();
            addMessageRow(
                "assistant",
                "Woof… I could not load the conversation history (" + err.message + ").",
                false
            );
        }
    }

    async function init() {
        setMascotState("idle");
        showBubbleIdle();

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

        if (!isFirstVisit && inputEl && !inputEl.disabled) {
            inputEl.focus();
        }
    }

    // ================================================================ //
    // 11) QUICK QUESTIONS + EVENT WIRING                               //
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

