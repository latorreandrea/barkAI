(function () {
    "use strict";

    // Translators: gettext()/ngettext() are provided by Django's
    // JavaScriptCatalog (served from /jsi18n/ and loaded before this file).
    // The fallbacks keep the UI working if that catalog is ever missing.
    var gettext = window.gettext || function (message) { return message; };
    var ngettext = window.ngettext || function (singular, plural, count) {
        return count === 1 ? singular : plural;
    };

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
    var chatLayoutEl = document.getElementById("chat-layout");
    var mascotStageEl = document.getElementById("mascot-stage");
    var composerEl = document.getElementById("chat-composer");
    var historyToggleEl = document.getElementById("history-toggle");
    var historyToggleLabelEl = document.getElementById("history-toggle-label");
    var historyToggleIconEl = document.getElementById("history-toggle-icon");
    var bubbleTextEl = document.getElementById("speech-bubble-text");
    var bubbleScrollEl = document.getElementById("speech-bubble-scroll");
    var idleSuggestionsEl = document.getElementById("idle-suggestions");
    var idleSuggestionsTextEl = document.getElementById("idle-suggestions-text");

    if (sessionChip) {
        sessionChip.textContent = sessionId.slice(0, 8) + "…";
    }

    // ================================================================ //
    // 3) MASCOT STATE MACHINE: swaps the <video> src + status labels.  //
    // ================================================================ //
    var STATES = {
        idle: gettext("BarklAI is ready — ask me anything!"),
        sniffing: gettext("BarklAI caught your scent — coming closer…"),
        searching: gettext("BarklAI is searching repositories…"),
        typing: gettext("BarklAI is typing…"),
        speaking: gettext("BarklAI is speaking…"),
        celebrating: gettext("BarklAI found an interview opportunity! 🎉")
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
        // Any real bubble content replaces the idle-suggestion nudge.
        hideIdleSuggestions();
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
        meta.textContent = isUser ? gettext("You") : gettext("BarklAI 🐾");

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
    // 7) IDLE SUGGESTIONS: after a spell of inactivity BarklAI himself  //
    //    suggests a few questions, right inside his own speech bubble.  //
    // ================================================================ //
    // No typing and no sending for a minute: the chips show up...
    var IDLE_DELAY_MS = 60000;
    // ...and if a draft keeps sitting in the composer for a long while, a
    // friendlier nudge replaces the default one.
    var TYPING_STUCK_DELAY_MS = 300000;
    var IDLE_HINT = gettext("👇 Ask BarklAI your first question below!");
    var TYPING_HINT = gettext("🐾 Take your time! Or pick a shortcut to get started:");

    var idleTimer = null;
    var typingTimer = null;

    // Reveal the quick-question chips inside the bubble.
    // `hint` is an optional line BarklAI "says" above the chips (the idle
    // nudge); when it is omitted the live reply stays visible above them.
    function showIdleSuggestions(hint) {
        var hintText = (hint || "").trim();
        if (idleSuggestionsTextEl) {
            idleSuggestionsTextEl.textContent = hintText;
            idleSuggestionsTextEl.hidden = hintText === "";
        }
        if (idleSuggestionsEl) {
            idleSuggestionsEl.hidden = false;
        }
        if (bubbleScrollEl) {
            // Grow the bubble so every chip is visible, and rewind to the top.
            bubbleScrollEl.classList.add("is-suggesting");
            bubbleScrollEl.classList.toggle("is-hinting", hintText !== "");
            bubbleScrollEl.scrollTop = 0;
        }
    }

    function hideIdleSuggestions() {
        if (idleSuggestionsEl) {
            idleSuggestionsEl.hidden = true;
        }
        if (bubbleScrollEl) {
            bubbleScrollEl.classList.remove("is-suggesting", "is-hinting");
        }
    }

    function clearIdleTimer() {
        if (idleTimer) {
            window.clearTimeout(idleTimer);
            idleTimer = null;
        }
    }

    function clearTypingTimer() {
        if (typingTimer) {
            window.clearTimeout(typingTimer);
            typingTimer = null;
        }
    }

    // (Re)start the "visitor is idle" countdown.
    function armIdleTimer() {
        clearIdleTimer();
        idleTimer = window.setTimeout(function () {
            showIdleSuggestions(IDLE_HINT);
        }, IDLE_DELAY_MS);
    }

    // The visitor has been drafting a message for a long time: offer a hand.
    function armTypingTimer() {
        clearTypingTimer();
        typingTimer = window.setTimeout(function () {
            showIdleSuggestions(TYPING_HINT);
        }, TYPING_STUCK_DELAY_MS);
    }

    // Any real user action drops the nudge and stops both countdowns.
    function cancelIdleSuggestions() {
        clearIdleTimer();
        clearTypingTimer();
        hideIdleSuggestions();
    }

    // ================================================================ //
    // 8) FIRST-VISIT ONBOARDING: hero lines -> sniffing -> woof ->      //
    //    two spoken intro messages (scripted, never persisted).        //
    // ================================================================ //
    var ONBOARDING_MESSAGE_1 = gettext("Woof! Wait... [sniff, sniff]... I smell clean code and new opportunities! Hi! I'm BarkAI. What brings you here? Are you looking for the right dev for your team?");
    var ONBOARDING_MESSAGE_2 = gettext("Perfect! Then you're in the right place. If you want to learn more about Andrea's work, his skills, or chat about his projects (or even figure out how he can help you solve a specific technical challenge), just tell me: I'm all ears!");
    var REVISITOR_GREETING = gettext("Woof! 👋 I'm BarklAI, Andrea's AI career companion. Ask me about his open-source projects, Python/Django experience, or RAG pipelines — or request an interview right here!");

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
        if (messageListEl.children.length > 0 || bubbleIsMessage()) {
            setMascotState("idle");
            return Promise.resolve();
        }
        setMascotState("speaking");
        setBusy(true);
        return typeBubbleMessage(text).then(function () {
            setBusy(false);
            armIdleTimer(); // BarklAI is quiet: start the idle-suggestion countdown.
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

    // BarklAI sniffs the newcomer. The "Woof!" pops ~2 s earlier than before
    // (around the middle of the clip), then he introduces himself once the
    // sniffing clip has played through. The two beats are independent, so
    // moving the bark does not shift the greeting.
    function startSniffingSequence() {
        setMascotState("sniffing");

        var video = videos[0];
        var barkFired = false;
        var messageStarted = false;

        function fireBark() {
            if (barkFired) {
                return;
            }
            barkFired = true;
            if (barkOnomatopoeiaEl) {
                barkOnomatopoeiaEl.classList.remove("is-visible");
                void barkOnomatopoeiaEl.offsetWidth; // Restart the CSS animation.
                barkOnomatopoeiaEl.classList.add("is-visible");
            }
        }

        function startMessage() {
            if (messageStarted) {
                return;
            }
            messageStarted = true;
            greetInBubble(ONBOARDING_MESSAGE_1).then(scheduleSecondMessage);
        }

        function arm() {
            var duration = (video && video.duration && isFinite(video.duration))
                ? video.duration : 0;
            if (!duration) {
                window.setTimeout(fireBark, 3500);
                window.setTimeout(startMessage, 6800);
                return;
            }
            // Woof ~2 seconds earlier than the previous 80% mark.
            var barkAt = Math.max(0, duration * 0.8 - 2);
            window.setTimeout(fireBark, Math.max(0, (barkAt - video.currentTime) * 1000));
            // Greeting once the sniffing clip has played through (~unchanged).
            window.setTimeout(startMessage, duration * 1000);
        }

        if (video) {
            if (video.readyState >= 1) {
                arm();
            } else {
                video.addEventListener("loadedmetadata", arm, { once: true });
            }
            video.addEventListener("timeupdate", function () {
                if (barkFired || !video.duration || !isFinite(video.duration)) {
                    return;
                }
                if (video.currentTime >= Math.max(0, video.duration * 0.8 - 2)) {
                    fireBark();
                }
            });
        } else {
            arm();
        }

        // Safety nets in case the clip metadata never arrives.
        window.setTimeout(fireBark, 8000);
        window.setTimeout(startMessage, 9000);
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
                    armIdleTimer();
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

        // The visitor is chatting: drop the scripted message-2 reveal and the
        // idle-suggestion nudge, then clear the composer.
        cancelSecondMessage();
        cancelIdleSuggestions();
        onboardingBusy = false;

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
            // The agent decided the recruiter is unsure: offer quick questions.
            if (data.suggest_questions) {
                showIdleSuggestions(null);
            }
        } catch (err) {
            await flushPromise.catch(function () { return null; });
            setMascotState("idle");
            await typeBubbleMessage(
                gettext("Woof… sorry, I could not reach my backend") +
                " (" + (err && err.message ? err.message : err) + "). " +
                gettext("Please try again.")
            );
        } finally {
            setBusy(false);
            armIdleTimer(); // Chat is quiet again: restart the idle countdown.
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
                gettext("Woof… I could not load the conversation history") +
                " (" + err.message + ").",
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

        // Once the chat is quiet, wait a while before BarklAI nudges with ideas.
        armIdleTimer();

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

    // ================================================================ //
    // 12) EXPANDABLE HISTORY + WHEEL FORWARDING                        //
    // ================================================================ //
    var historyExpanded = false;

    function setHistoryExpanded(expanded) {
        historyExpanded = expanded;
        if (chatLayoutEl) {
            chatLayoutEl.classList.toggle("is-history-expanded", expanded);
        }
        if (historyToggleEl) {
            historyToggleEl.setAttribute("aria-expanded", expanded ? "true" : "false");
        }
        if (historyToggleLabelEl) {
            historyToggleLabelEl.textContent = expanded ? gettext("Live chat") : gettext("History");
        }
        if (historyToggleIconEl) {
            historyToggleIconEl.textContent = expanded ? "✕" : "⤢";
        }
        if (expanded) {
            // Opening the history: jump straight to the most recent message.
            scrollThreadToBottom();
        }
    }

    if (historyToggleEl) {
        historyToggleEl.addEventListener("click", function () {
            setHistoryExpanded(!historyExpanded);
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && historyExpanded) {
            setHistoryExpanded(false);
        }
    });

    // Forward the mouse wheel over the mascot / composer to the history thread,
    // so the visitor does not have to aim precisely at the scrollable list.
    function forwardWheelToHistory(event) {
        if (!threadEl || threadEl.scrollHeight <= threadEl.clientHeight) {
            return; // Nothing to scroll: leave the event alone.
        }
        // If the pointer is over a scrollable speech bubble, let it scroll itself.
        if (bubbleScrollEl && bubbleScrollEl.contains(event.target) &&
            bubbleScrollEl.scrollHeight > bubbleScrollEl.clientHeight) {
            return;
        }
        threadEl.scrollTop += event.deltaY;
    }

    [mascotStageEl, composerEl].forEach(function (el) {
        if (el) {
            el.addEventListener("wheel", forwardWheelToHistory, { passive: true });
        }
    });

    // ================================================================ //
    // 13) GDPR: erase this conversation on demand (right to erasure)   //
    // ================================================================ //
    var deleteSessionBtn = document.getElementById("delete-session");
    if (deleteSessionBtn) {
        deleteSessionBtn.addEventListener("click", async function () {
            var question = gettext("Delete this conversation? This cannot be undone.");
            if (!window.confirm(question)) {
                return;
            }
            try {
                await fetch("/session/delete/", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": getCookie("csrftoken")
                    },
                    body: JSON.stringify({ session_id: sessionId })
                });
            } catch (err) {
                /* Network hiccup: still drop the local session below. */
            }
            localStorage.removeItem(STORAGE_KEY);
            window.location.reload();
        });
    }

    formEl.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage();
    });
    wireSuggestions();

    // Typing counts as activity: restart the idle countdown, and start the
    // "long draft" clock while a non-empty message sits in the composer.
    inputEl.addEventListener("input", function () {
        armIdleTimer();
        if (inputEl.value.trim() !== "") {
            if (!typingTimer) {
                armTypingTimer();
            }
        } else {
            clearTypingTimer();
        }
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

