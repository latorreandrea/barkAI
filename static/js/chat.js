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
    // Cache-buster for the clips, mirroring the `?v=` on the CSS/JS links: the
    // MP4s are cached for a year, so a replaced clip needs a new URL to be seen.
    var assetVersion = bodyEl.getAttribute("data-asset-version");
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
    var contactFormEl = document.getElementById("interview-contact");
    var contactNameEl = document.getElementById("contact-name");
    var contactEmailEl = document.getElementById("contact-email");
    var contactCompanyEl = document.getElementById("contact-company");
    var contactSaveBtn = document.getElementById("interview-contact-save");
    var contactStatusEl = document.getElementById("interview-contact-status");
    var sourcesLabelEl = document.getElementById("sources-label");

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

    // The state currently on screen. The composer's "typing" hold (3b) reads it
    // to decide whether it may take the stage and what to hand back afterwards.
    var currentMascotState = null;

    // ================================================================ //
    // 3a) VIDEO STAGE (A/B): two stacked players, one of them visible. //
    // ================================================================ //
    // Changing the `src` of a <video> tears its decoder down, so the element
    // shows NOTHING until the first keyframe of the new file is decoded: that
    // is the gap between two reaction clips (worse on a cold cache, where the
    // download sits in front of it). The second element removes it — it
    // pre-rolls the next clip while the one on screen keeps playing, and only
    // replaces it once it can actually draw.
    //
    // All six clips start AND end on the same neutral pose, so a cut is
    // invisible exactly when it lands on the outgoing clip's loop seam: that
    // pose is where the incoming clip starts (it is pre-rolled on its first
    // frame, not running, for the same reason). The cut waits for the seam
    // while it is at hand and otherwise happens as soon as the new clip is
    // drawable — waiting longer would hold the whole reaction back by up to a
    // clip length (idle is 7 s, searching 17 s).
    //
    // The hand-over is deliberately a cut and not a cross-fade: these are
    // hand-drawn poses on white, so blending two of them shows the dog twice.
    // A cut that misses the seam is a pose jump, which reads as a cut; set
    // SWAP_BLINK_MS if you would rather cover it with a 90 ms white blink.
    var SEAM_WAIT_MS = 300;      // Give the loop this long to reach its neutral pose.
    var SWAP_TICK_MS = 40;       // How often the cut conditions are re-checked.
    var SWAP_BLINK_MS = 0;       // > 0: blink the stage white when the cut misses the seam.
    // Clips the visitor is most likely to need next, fetched while the page is
    // quiet so the first keystroke does not wait on the network.
    var WARM_CLIPS = ["typing", "speaking"];
    var WARM_DELAY_MS = 4000;

    // The visitor is owed the WHOLE take the first time one of these clips takes
    // the stage: whoever sees "BarklAI is searching…" for the first time should
    // watch the searching clip play out, instead of it being cut the moment the
    // reply is ready. Every later play-through is cut as soon as the next clip can
    // draw — exactly as before.
    var HOLD_FIRST_FULL_CLIP = ["searching"];
    // Not a UX cut-off: the clip is always given its full length, plus this grace
    // second. A background tab pauses the video while timers keep ticking, so
    // without a deadline a stalled clip could hold the reply back forever.
    var FULL_CLIP_GRACE_MS = 1000;
    // Deadline used when the clip's metadata never arrived (broken file, cold
    // cache): long enough for a slow network, short enough to not look stuck.
    var FIRST_TAKE_FALLBACK_MS = 20000;

    var frontVideo = videos[0] || null; // The element on screen.
    var backVideo = videos[1] || null;  // The element being pre-rolled (may be absent).
    var visibleState = null;            // State of the element on screen.
    var pendingState = null;            // State being pre-rolled behind it.
    var swapTimer = null;
    var fullClipSeen = {};              // States whose "watch me once" take is over.
    var heldClip = null;                // {state, deadline} of the hold in progress.

    function videoUrl(state) {
        return mediaUrl + state + ".mp4" + (assetVersion ? "?v=" + assetVersion : "");
    }

    // The clip on screen: what the visitor sees, and what timing is measured on.
    function visibleVideo() {
        return frontVideo;
    }

    // The element holding a state, whether it is on screen or still pre-rolling
    // (the onboarding reads the sniffing clip's duration to time the "Woof!").
    function videoShowingState(state) {
        var src = videoUrl(state);
        if (frontVideo && frontVideo.getAttribute("src") === src) {
            return frontVideo;
        }
        if (backVideo && backVideo.getAttribute("src") === src) {
            return backVideo;
        }
        return null;
    }

    // `playNow` = the clip takes the stage; otherwise it is pre-rolled to its
    // first frame (the neutral pose) and left paused, so the cut can be an
    // exact pose match. Some engines only start decoding once play() is
    // requested, hence the immediate pause.
    function warmVideo(video, state, playNow) {
        if (!video) {
            return;
        }
        var src = videoUrl(state);
        if (video.getAttribute("src") !== src) {
            video.setAttribute("src", src);
            video.load();
        }
        if (playNow) {
            video.play()["catch"](function () {
                // Autoplay can be blocked before the first user gesture.
            });
        } else {
            // Pre-roll: decode the first frame (the neutral pose) and leave it
            // paused. Some engines only start decoding once play() is requested,
            // hence the immediate pause — skipped when the clip has meanwhile
            // taken the stage, or the pre-roll would freeze the clip on screen.
            video.play().then(function () {
                if (video !== frontVideo) {
                    video.pause();
                }
            })["catch"](function () {
                // Pre-roll refused (autoplay policy): the cut still works.
            });
        }
    }

    function cancelSwap() {
        if (swapTimer) {
            window.clearInterval(swapTimer);
            swapTimer = null;
        }
        pendingState = null;
    }

    // readyState 2 = HAVE_CURRENT_DATA: there is a frame to show (no blank box).
    function canDraw(video) {
        return !!video && video.readyState >= 2;
    }

    // Milliseconds left before the looping clip wraps around to its seam.
    function seamInMs(video) {
        if (!video || !isFinite(video.duration) || video.duration <= 0) {
            return 0; // Length unknown: there is nothing to wait for.
        }
        return Math.max(0, (video.duration - video.currentTime) * 1000);
    }

    // True while the clip on screen still has to play through once before the
    // stage (and BarklAI's answer) may go on: see HOLD_FIRST_FULL_CLIP. The hold
    // ends on the loop seam — the neutral pose — or on its deadline, which only
    // triggers when the clip stopped advancing (a background tab pauses video,
    // not timers).
    function firstPlayThroughPending() {
        if (
            HOLD_FIRST_FULL_CLIP.indexOf(visibleState) === -1 ||
            fullClipSeen[visibleState]
        ) {
            return false;
        }
        var video = frontVideo;
        var duration = video && isFinite(video.duration) ? video.duration : 0;
        if (!heldClip || heldClip.state !== visibleState) {
            heldClip = {
                state: visibleState,
                deadline: Date.now() + (duration > 0 ? duration * 1000 : FIRST_TAKE_FALLBACK_MS) + FULL_CLIP_GRACE_MS
            };
        }
        if (duration > 0 && duration - video.currentTime <= SEAM_WAIT_MS / 1000) {
            fullClipSeen[visibleState] = true; // Wrapped: the whole take has been seen.
            heldClip = null;
            return false;
        }
        if (Date.now() >= heldClip.deadline) {
            fullClipSeen[visibleState] = true; // Stalled: never block the reply.
            heldClip = null;
            return false;
        }
        return true;
    }

    // The same wait, seen from the caller's side: the answer is typed (and the
    // speaking clip requested) once the first take is over.
    function whenFirstPlayThroughEnds() {
        if (!firstPlayThroughPending()) {
            return Promise.resolve();
        }
        return new Promise(function (resolve) {
            var watcher = window.setInterval(function () {
                if (firstPlayThroughPending()) {
                    return;
                }
                window.clearInterval(watcher);
                resolve();
            }, SWAP_TICK_MS);
        });
    }

    // A clip took the stage: the emoji fallback is no longer needed.
    function markStageTaken(element) {
        var shell = element.closest(".js-video-shell");
        if (shell) {
            shell.classList.remove("is-missing");
        }
    }

    // Cover a cut that could not land on the neutral pose. The animation length
    // is driven by the constant above, so there is a single place to tune it.
    function blinkShell() {
        var shell = frontVideo ? frontVideo.closest(".js-video-shell") : null;
        if (!shell) {
            return;
        }
        shell.style.setProperty("--swap-blink", SWAP_BLINK_MS + "ms");
        shell.classList.remove("is-swapping");
        void shell.offsetWidth; // Restart the animation.
        shell.classList.add("is-swapping");
        window.setTimeout(function () {
            shell.classList.remove("is-swapping");
        }, SWAP_BLINK_MS);
    }

    // Hand the stage over: the pre-rolled clip becomes visible on its neutral
    // pose and starts running exactly then.
    function swapVideos() {
        // Tailwind's opacity utility is the switch, so the stage needs no CSS of
        // its own — the classes come from the template.
        frontVideo.classList.add("opacity-0");
        backVideo.classList.remove("opacity-0");
        var previousFront = frontVideo;
        frontVideo = backVideo;
        backVideo = previousFront;
        backVideo.pause(); // The hidden element has nothing left to advance.
        markStageTaken(frontVideo);
        frontVideo.play()["catch"](function () {
            // Autoplay can be blocked before the first user gesture.
        });
        visibleState = pendingState;
        cancelSwap();
    }


    // A state was asked for: pre-roll it behind the clip on screen, then cut to
    // it as soon as the decoder is ready (and on its seam, when that is close).
    function stageSet(state) {
        if (!frontVideo) {
            return;
        }
        if (!backVideo || visibleState === null) {
            // No second element, or nothing on screen yet (the very first clip):
            // the front element is the one to load.
            visibleState = state;
            warmVideo(frontVideo, state, true);
            markStageTaken(frontVideo);
            return;
        }
        if (state === visibleState) {
            // Back to what is already playing (the visitor resumed typing, say):
            // drop the pre-roll instead of flashing the other clip.
            cancelSwap();
            return;
        }
        if (state === pendingState) {
            return; // Already pre-rolling it.
        }

        cancelSwap();
        pendingState = state;
        warmVideo(backVideo, state, false);

        swapTimer = window.setInterval(function () {
            if (!canDraw(backVideo)) {
                // Never cut to a blank frame: keep the current clip running. If
                // the file is broken rather than slow, its error listener cancels
                // the swap and the mascot keeps the previous reaction.
                return;
            }
            if (firstPlayThroughPending()) {
                return; // The first take of this clip still has to play out.
            }
            var seam = seamInMs(frontVideo);
            if (seam > 0 && seam <= SEAM_WAIT_MS) {
                // The loop is about to reach the pose the new clip starts from:
                // a few more milliseconds buy a cut nobody can see. The wait is
                // bounded by SEAM_WAIT_MS, and it ends by itself on the tick
                // after the wrap — that is, on the neutral pose.
                return;
            }
            if (SWAP_BLINK_MS > 0 && seam > SEAM_WAIT_MS) {
                blinkShell(); // This cut misses the seam: cover the pose jump.
            }
            swapVideos();
        }, SWAP_TICK_MS);
    }

    // Fetch the clips the visitor is about to need, so the first keystroke does
    // not wait on the network. Skipped when the page is hidden, when the
    // connection is metered (saveData) or slow — and it is only an optimisation:
    // a failed fetch changes nothing.
    function prefetchUpcomingClips() {
        var connection = navigator.connection;
        if (document.hidden) {
            return;
        }
        if (connection && (connection.saveData || /(^|-)2g$/.test(connection.effectiveType || ""))) {
            return;
        }
        WARM_CLIPS.forEach(function (state) {
            window.fetch(videoUrl(state), { cache: "force-cache" }).then(function (response) {
                return response.arrayBuffer();
            })["catch"](function () {
                // The clip will simply be fetched when it is needed.
            });
        });
    }


    function setMascotState(state) {
        if (!STATES.hasOwnProperty(state)) {
            state = "idle";
        }
        currentMascotState = state;
        // The celebration owns the stage for a while, but not forever: it settles
        // back into the resting clip on its own (see armCelebrateTimer).
        if (state === "celebrating") {
            armCelebrateTimer();
        } else {
            clearCelebrateTimer();
        }
        stageSet(state);
        statusEls.forEach(function (el) {
            el.textContent = STATES[state];
        });
    }

    // When a reaction MP4 is missing, show the emoji fallback instead of a black
    // frame — but only when the element on screen is the broken one. A failure in
    // the pre-rolling copy just cancels the swap, so the clip the visitor is
    // watching keeps playing instead of being replaced by a pooch emoji.
    videos.forEach(function (video) {
        video.addEventListener("error", function () {
            if (video === frontVideo || visibleState === null) {
                var shell = video.closest(".js-video-shell");
                if (shell) {
                    shell.classList.add("is-missing");
                }
            } else if (video === backVideo) {
                cancelSwap();
            }
        });
    });

    // ================================================================ //
    // 3b) COMPOSER TYPING: while the VISITOR writes a message the      //
    //     mascot plays the "typing" clip, and hands the stage back a   //
    //     moment after the keys stop.                                  //
    // ================================================================ //
    // Detection is the `input` event on the composer (wired at the bottom):
    // it is the one event that also fires for paste, cut, drag & drop,
    // autofill, dictation and phone keyboards, it never fires for Shift,
    // arrows or a held modifier (a `keydown` handler would), and it never
    // hands us the characters themselves — nothing here wants to read
    // `event.key`. Composition/IME typing reports it too, so no `keydown`
    // fallback is needed.
    //
    // The hold keeps the clip looping for the whole burst instead of
    // restarting it on every keystroke (see noteComposerTyping).
    var TYPING_HOLD_MS = 1200;
    var composerTyping = false;
    var typingHoldTimer = null;
    var stateBeforeTyping = "idle";

    // The stage belongs to BarklAI whenever he is mid-turn (his composer is
    // disabled while he searches/speaks) or still sniffing the newcomer: a
    // visitor typing there must not cut the scripted onboarding short. A
    // hidden page and the expanded history view hide the stage entirely, so
    // there is nothing to switch.
    function mascotStageIsFree() {
        if (document.hidden || currentMascotState === "sniffing") {
            return false;
        }
        if (formEl.dataset.busy === "true") {
            return false;
        }
        return !(chatLayoutEl && chatLayoutEl.classList.contains("is-history-expanded"));
    }

    // Back to whatever was on screen before the visitor started writing. The
    // state is only touched while "typing" is still the current one, so a
    // reply that arrived meanwhile (or an explicit setMascotState) wins.
    function stopComposerTyping(restore) {
        if (typingHoldTimer) {
            window.clearTimeout(typingHoldTimer);
            typingHoldTimer = null;
        }
        if (!composerTyping) {
            return;
        }
        composerTyping = false;
        if (restore !== false && currentMascotState === "typing") {
            setMascotState(stateBeforeTyping);
        }
    }

    // Called on every input event: the first one enters the state, the next
    // ones only push the "keys stopped" deadline forward.
    function noteComposerTyping() {
        if (typingHoldTimer) {
            window.clearTimeout(typingHoldTimer);
        }
        typingHoldTimer = window.setTimeout(function () {
            typingHoldTimer = null;
            stopComposerTyping();
        }, TYPING_HOLD_MS);
        if (composerTyping || !mascotStageIsFree()) {
            return;
        }
        stateBeforeTyping = currentMascotState || "idle";
        composerTyping = true;
        setMascotState("typing");
    }

    // ================================================================ //
    // 4) SPEECH BUBBLE (the "live" comic nuvoletta).                   //
    //    It holds BarklAI's current utterance OR a transient progress  //
    //    label ("BarklAI is searching"). It never holds chat history.  //
    // ================================================================ //

    // Text of the BarklAI message currently occupying the bubble. Null means
    // the bubble only shows an idle hint or a transient progress label.
    var activeBubbleText = null;
    // Knowledge-base labels cited by the utterance above (empty for user turns,
    // progress labels and greetings).
    var activeBubbleSources = [];
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

    // Translated label for the citation chips ("Sources" / "Kilder"), read from
    // the template so the string lives in the Django catalogue.
    function sourcesLabel() {
        return sourcesLabelEl ? sourcesLabelEl.getAttribute("data-label") || "" : "";
    }

    // A discreet "Sources: <project> <project>" line, or null when there is none.
    // The server resolves each citation into {label, title, url, lines}, so the
    // values are inserted with textContent and can never inject HTML; a citation
    // with a URL becomes a link that opens the cited lines on GitHub.
    // What the chip says: the section of the cited file, plus the lines.
    function citationText(citation) {
        // The section is the useful label; without one, the source itself.
        var parts = [citation.title || citation.label || ""];
        if (citation.lines) {
            parts.push("L" + citation.lines);
        }
        return parts.filter(Boolean).join(" · ");
    }

    // The full picture on hover, for a chip that had to be shortened.
    function citationTooltip(citation) {
        var parts = [];
        if (citation.label) {
            parts.push(citation.label);
        }
        if (citation.title && citation.title !== citation.label) {
            parts.push(citation.title);
        }
        if (citation.lines) {
            parts.push("L" + citation.lines);
        }
        return parts.join(" · ");
    }

    function buildCitationChip(citation) {
        var chip = document.createElement(citation.url ? "a" : "span");
        chip.className = citation.url
            ? "sources-chip sources-chip-link"
            : "sources-chip";
        if (citation.url) {
            chip.href = citation.url;
            chip.target = "_blank";
            chip.rel = "noopener noreferrer";
        }
        chip.textContent = citationText(citation) || citation.label || "";
        var tooltip = citationTooltip(citation);
        if (tooltip) {
            chip.title = tooltip;
        }
        return chip;
    }

    function buildSourcesLine(sources) {
        if (!sources || !sources.length) {
            return null;
        }
        var line = document.createElement("p");
        line.className = "sources-line";
        var label = document.createElement("span");
        label.className = "sources-label";
        label.textContent = sourcesLabel();
        line.appendChild(label);
        sources.forEach(function (source) {
            // Citations stored before they carried links are still plain strings.
            var citation = typeof source === "string" ? { label: source } : source || {};
            line.appendChild(buildCitationChip(citation));
        });
        return line;
    }

    function appendSourcesToBubble(sources) {
        var line = buildSourcesLine(sources);
        if (line) {
            bubbleTextEl.appendChild(line);
            bubbleScrollEl.scrollTop = bubbleScrollEl.scrollHeight;
        }
    }

    // Idle placeholder shown while there is nothing live to say yet.
    function showBubbleIdle() {
        activeBubbleText = null;
        activeBubbleSources = [];
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
    function typeBubbleMessage(text, sources) {
        return new Promise(function (resolve) {
            var words = text.split(" ");
            var index = 0;
            activeBubbleText = text;
            activeBubbleSources = sources || [];
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
                    appendSourcesToBubble(activeBubbleSources);
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

    function addMessageRow(sender, content, animateIn, sources) {
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
        // Citations travel with the bubble into the transcript.
        var sourcesLine = buildSourcesLine(sources);
        if (sourcesLine) {
            bubble.appendChild(sourcesLine);
        }
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
            var sources = activeBubbleSources;
            activeBubbleText = null;
            activeBubbleSources = [];
            bubbleTextEl.classList.add("bubble-msg-leaving");
            addMessageRow("assistant", text, true, sources);
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
    // 7) INTERVIEW HAND-OFF: once BarklAI flags an interview, reveal a //
    //    small form so Andrea actually gets a way to reply. The details //
    //    ride along with the next message AND have their own endpoint.  //
    // ================================================================ //
    // Returns the form values, or empties when the form is not showing (so a
    // hidden form never overwrites stored details with blank strings).
    function contactDetails() {
        if (!contactFormEl || contactFormEl.hidden) {
            return { hr_name: "", hr_email: "", company_name: "" };
        }
        return {
            hr_name: contactNameEl ? contactNameEl.value.trim() : "",
            hr_email: contactEmailEl ? contactEmailEl.value.trim() : "",
            company_name: contactCompanyEl ? contactCompanyEl.value.trim() : ""
        };
    }

    // What the conversation already knows about the recruiter: the API returns
    // it with the history and with every reply (name/email/company, all
    // optional). It includes an address the visitor simply *typed* in the chat —
    // the server picks it up from the message (chat/interviews.py) — so the form
    // below can be shown prefilled instead of asking for it twice.
    var knownContact = { hr_name: "", hr_email: "", company_name: "" };

    function rememberContact(contact) {
        if (!contact) {
            return;
        }
        ["hr_name", "hr_email", "company_name"].forEach(function (key) {
            if (contact[key]) {
                knownContact[key] = contact[key];
            }
        });
    }

    // What the form was last filled with: a field the visitor has edited since
    // then is never overwritten, while an untouched one follows whatever the
    // conversation learns next (a corrected address, say).
    var prefilledContact = { hr_name: "", hr_email: "", company_name: "" };

    // Front of the form: fill from what we know without stepping on the visitor.
    function fillContactForm() {
        [[contactNameEl, "hr_name"], [contactEmailEl, "hr_email"], [contactCompanyEl, "company_name"]]
            .forEach(function (pair) {
                var field = pair[0];
                var key = pair[1];
                var typed = field ? field.value.trim() : "";
                if (!field || !knownContact[key]) {
                    return;
                }
                if (typed === "" || typed === prefilledContact[key]) {
                    field.value = knownContact[key];
                    prefilledContact[key] = knownContact[key];
                }
            });
    }

    // The label says what the visitor is doing: confirming details the
    // conversation already knows (the form is prefilled) or saving the ones they
    // typed just now. Both strings come from the template.
    function setContactActionLabel(isConfirming) {
        if (!contactSaveBtn) {
            return;
        }
        var label = contactSaveBtn.getAttribute(isConfirming ? "data-confirm-label" : "data-save-label");
        if (label) {
            contactSaveBtn.textContent = label;
        }
    }

    // Reveal the hand-off form for confirmation: whatever the conversation
    // collected is prefilled, so the visitor only has to correct or approve it.
    function revealContactForm() {
        if (!contactFormEl) {
            return;
        }
        fillContactForm();
        setContactActionLabel(!!(knownContact.hr_name || knownContact.hr_email || knownContact.company_name));
        contactFormEl.hidden = false;
    }

    function hideContactForm() {
        if (contactFormEl) {
            contactFormEl.hidden = true;
        }
    }

    // The two messages are translated server-side and carried as data attributes,
    // so they stay in the Django catalogue instead of the JS one.
    function contactMessage(name) {
        if (contactStatusEl) {
            return contactStatusEl.getAttribute("data-" + name + "-message") || "";
        }
        return "";
    }

    function setContactStatus(message, isError) {
        if (!contactStatusEl) {
            return;
        }
        if (!message) {
            contactStatusEl.hidden = true;
            contactStatusEl.textContent = "";
            return;
        }
        contactStatusEl.textContent = message;
        contactStatusEl.hidden = false;
        contactStatusEl.classList.toggle("text-emerald-700", !isError);
        contactStatusEl.classList.toggle("text-rose-600", !!isError);
    }

    // The details reached the backend: hide the form and confirm in his voice.
    function showContactSaved() {
        hideContactForm();
        setContactStatus(contactMessage("saved"), false);
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

    // The visitor has been quiet for a minute: BarklAI offers a few questions AND
    // settles back into his resting pose. An idle visitor should be looking at an
    // idle dog, not at a loop of his last reaction — one countdown, one moment.
    function settleToIdle() {
        if (formEl.dataset.busy === "true") {
            return; // Mid-turn: the stage belongs to BarklAI (and to the answer).
        }
        if (currentMascotState !== "idle") {
            setMascotState("idle");
        }
    }

    // (Re)start the "visitor is idle" countdown.
    function armIdleTimer() {
        clearIdleTimer();
        idleTimer = window.setTimeout(function () {
            showIdleSuggestions(IDLE_HINT);
            settleToIdle();
        }, IDLE_DELAY_MS);
    }

    // The celebration is a take of its own, but it hands the stage back after a
    // minute instead of looping forever (the hand-off form stays available, and any
    // activity - typing, a new question - cancels this countdown anyway).
    var CELEBRATE_IDLE_MS = 60000;
    var celebrateTimer = null;

    function clearCelebrateTimer() {
        if (celebrateTimer) {
            window.clearTimeout(celebrateTimer);
            celebrateTimer = null;
        }
    }

    function armCelebrateTimer() {
        clearCelebrateTimer();
        celebrateTimer = window.setTimeout(function () {
            celebrateTimer = null;
            settleToIdle();
        }, CELEBRATE_IDLE_MS);
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

        // The element that carries the sniffing clip: it may still be the hidden
        // one while the stage hands over, and it is the playback that times the
        // "Woof!".
        var video = videoShowingState("sniffing") || videos[0];
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

    function requestReply(text, details) {
        return fetch("/api/chat/send", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken")
            },
            body: JSON.stringify({
                session_id: sessionId,
                message: text,
                hr_name: details.hr_name,
                hr_email: details.hr_email,
                company_name: details.company_name
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
        // The visitor is done writing: the request owns the clip from here.
        stopComposerTyping(false);
        setBusy(true);

        // Snapshot the hand-off form before the request: its details ride along
        // with the message. The form itself then steps out of the way while
        // BarklAI works, so nothing covers his answer — it comes back, prefilled,
        // once the reply is on screen and the interview is still pending.
        var sentDetails = contactDetails();
        hideContactForm();

        // 1) The previous live utterance moves up into the history while the
        //    user's new message is appended right below it.
        var flushPromise = flushBubbleToHistory();
        addMessageRow("user", text, false);

        // 2) BarklAI visibly searches; the bubble shows the progress state as
        //    soon as the previous answer has finished moving up.
        setMascotState("searching");
        var requestPromise = requestReply(text, sentDetails);
        // The progress label stays up for as long as the searching clip owns the
        // stage — the first search of a visit does that for the whole clip (see
        // HOLD_FIRST_FULL_CLIP), even when the reply is already waiting.
        flushPromise.then(function () {
            if (currentMascotState === "searching") {
                showBubbleProgress(STATES.searching.replace(/…$/, ""));
            }
        });

        try {
            var data = await requestPromise;
            rememberContact(data.contact);
            await flushPromise; // Never type the new reply over the old bubble copy.
            // The first search of a visit was promised its whole clip: BarklAI
            // starts speaking (the clip and the typed answer) once that take is over.
            await whenFirstPlayThroughEnds();
            setMascotState(data.interview_requested ? "celebrating" : "speaking");
            await typeBubbleMessage(data.reply, data.sources);
            // The agent decided the recruiter is unsure: offer quick questions.
            if (data.suggest_questions) {
                showIdleSuggestions(null);
            }
            if (data.interview_requested) {
                // Hand-off: keep asking for the details if we still have no way
                // to reply, or confirm the moment they are on their way.
                if (sentDetails.hr_email) {
                    showContactSaved();
                } else {
                    revealContactForm();
                }
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
            rememberContact(data.contact);
            var messages = data.messages.slice();

            // The last assistant reply is the "live" one: park it in the bubble.
            var bubbleContent = null;
            var bubbleSources = [];
            if (messages.length && messages[messages.length - 1].sender === "assistant") {
                var lastReply = messages.pop();
                bubbleContent = lastReply.content;
                bubbleSources = lastReply.sources || [];
            }
            messages.forEach(function (message) {
                addMessageRow(message.sender, message.content, false, message.sources);
            });

            if (data.messages.length === 0 && !isFirstVisit) {
                // Recurring visitor with an empty session: warm spoken hello.
                greetInBubble(REVISITOR_GREETING);
            } else if (bubbleContent !== null) {
                activeBubbleText = bubbleContent;
                activeBubbleSources = bubbleSources;
                setBubbleContent(document.createTextNode(bubbleContent), false);
                appendSourcesToBubble(bubbleSources);
                setMascotState(data.interview_requested ? "celebrating" : "idle");
            } else if (!onboardingBusy) {
                showBubbleIdle();
                setMascotState(data.interview_requested ? "celebrating" : "idle");
            }

            // Returning to a session where an interview was requested: make sure
            // the hand-off form (or its confirmation) is in front of the recruiter.
            if (data.interview_requested) {
                revealContactForm();
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

        // ...and fetch the clips he is most likely to need next, so the first
        // reaction does not wait on the network (see 3a).
        window.setTimeout(prefetchUpcomingClips, WARM_DELAY_MS);

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
    // 13) GDPR: the right to erasure lives in the site footer and is   //
    //     wired by navbar.js — it has to work on /privacy/ too, where   //
    //     this script is not loaded.                                   //
    // ================================================================ //

    formEl.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage();
    });

    // The hand-off form has its own endpoint: saving the details must not cost
    // an LLM call, and the recruiter does not have to send another message.
    if (contactFormEl) {
        contactFormEl.addEventListener("submit", function (event) {
            event.preventDefault();
            var details = contactDetails();
            if (!details.hr_email) {
                setContactStatus(contactMessage("error"), true);
                return;
            }
            if (contactSaveBtn) {
                contactSaveBtn.disabled = true;
            }
            fetch("/api/chat/contact", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken")
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    hr_name: details.hr_name,
                    hr_email: details.hr_email,
                    company_name: details.company_name
                })
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error("server returned HTTP " + response.status);
                }
                return response.json();
            }).then(function () {
                showContactSaved();
            }).catch(function () {
                setContactStatus(contactMessage("error"), true);
            }).finally(function () {
                if (contactSaveBtn) {
                    contactSaveBtn.disabled = false;
                }
            });
        });
    }

    wireSuggestions();

    // Typing counts as activity: restart the idle countdown, start the
    // "long draft" clock while a non-empty message sits in the composer, and
    // let the mascot answer the visitor who is writing (3b). The `input` event
    // is what makes this work for paste, dictation and phone keyboards too.
    inputEl.addEventListener("input", function () {
        armIdleTimer();
        if (inputEl.value.trim() !== "") {
            if (!typingTimer) {
                armTypingTimer();
            }
            noteComposerTyping();
        } else {
            clearTypingTimer();
            stopComposerTyping();
        }
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

