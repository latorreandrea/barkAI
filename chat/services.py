"""BarklAI's reply service layer.

This is the seam between the chat API and the agent. When ``GROQ_API_KEY`` is
set, :func:`generate_reply` asks the Groq LLM (JSON mode) for a structured
answer grounded in the knowledge base (career profile + GitHub READMEs). When
the key is missing — or when Groq is unreachable — BarklAI falls back to a
consistent, in-character message that playfully reports the connection problem,
so the recruiter always gets an answer instead of a stack trace.

The agent must also answer in the recruiter's language, so :func:`generate_reply`
detects the language of the message and asks the model once more when it replies
in the wrong one (:func:`detect_language` + the ``AGENT_LANGUAGE_GUARD`` setting).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from django.conf import settings
from django.utils import translation
from django.utils.translation import get_language, gettext

from chat.models import KnowledgeDocument
from chat.prompts import build_system_prompt, language_name

logger = logging.getLogger(__name__)

# Where to report hiccups (shown in the fallback copy).
_SUPPORT_EMAIL = "latorre.andrea.93@gmail.com"

# Consistent, in-character fallbacks (used when the LLM is unavailable).
FALLBACK_NO_KEY = (
    "Woof! My Groq nose isn't plugged in yet, so I'm running on a tiny mock "
    "brain right now. Add the API key and I'll be back to my full, snappy "
    f"self! 🐾 (Something off? Report it to {_SUPPORT_EMAIL}.)"
)

FALLBACK_UNREACHABLE = (
    "Woof… sniff sniff… I lost the scent of my Groq brain! 🐾 My connection to "
    "the model dropped, so I can't fetch a real answer right now. Give me a "
    "moment and try again — or throw me another question in the meantime. "
    f"Still stuck? Report the hiccup to {_SUPPORT_EMAIL} and I'll be back on "
    "the scent soon!"
)

FALLBACK_INTERVIEW = (
    "Woof — even with a fuzzy nose I still caught the scent of an interview! 🎉 "
    "I've flagged this opportunity for Andrea. My Groq link is down right now, "
    f"so I can't collect your details just yet — ping {_SUPPORT_EMAIL} if I go "
    "quiet!"
)

# Words that strongly suggest the recruiter wants to book an interview. The live
# model decides this itself; the offline fallback and the API's re-arm signal for
# the hand-off form use these heuristics. Both languages are covered, otherwise a
# Danish recruiter would never be flagged while Groq is unreachable — and see
# ``mentions_interview`` below: the lists are merged, so an English hint (``zoom``)
# also matches inside a Danish sentence.
_EN_INTERVIEW_HINTS = (
    "interview",
    "meeting",
    "schedule",
    "availability",
    "zoom",
    "phone call",
    "talk to",
    "book a",
    "set up",
    "conversation",
    "call",
    "appointment",
    "in touch",
    "reach out",
)
_DA_INTERVIEW_HINTS = (
    "samtale",
    "interview",
    "møde",
    "mødes",
    "booke",
    "aftale",
    "ringe",
    "opkald",
    "snakke med",
    "tid til",
    "kontakt",
    "tale med",
    "få fat i",
)
_INTERVIEW_HINTS = _EN_INTERVIEW_HINTS + _DA_INTERVIEW_HINTS

# --- Language detection ---------------------------------------------------
# Deliberately tiny and dependency-free: enough to catch the "Danish question,
# English answer" regression without shipping a language-detection model.
_DA_MARKERS = frozenset(
    {
        "og", "er", "har", "hvad", "hvordan", "hvor", "hvilke", "hvilken",
        "kan", "jeg", "vi", "til", "med", "for", "ikke", "den", "det", "der",
        "som", "hans", "arbejde", "erfaring", "samtale", "møde", "udvikler",
        "projekt", "projekter", "kompetencer", "virksomhed", "opgaver",
    }
)
_EN_MARKERS = frozenset(
    {
        "the", "and", "is", "are", "has", "have", "what", "how", "where",
        "which", "can", "we", "to", "with", "for", "not", "about", "interview",
        "experience", "work", "project", "projects", "developer", "you", "your",
        "would", "like", "his", "he", "she", "does", "do", "tell",
    }
)
_DA_LETTERS = frozenset("æøåÆØÅ")


def detect_language(text: str) -> str | None:
    """Best-effort ``"da"`` / ``"en"`` for a message, ``None`` when undecidable.

    ``None`` is intentional: the guard then stays quiet instead of triggering an
    unnecessary (and paid) model retry for a one-word message.
    """
    words = re.findall(r"[a-zæøå]+", (text or "").lower())
    if not words:
        return None
    danish = sum(1 for word in words if word in _DA_MARKERS)
    english = sum(1 for word in words if word in _EN_MARKERS)
    if any(char in _DA_LETTERS for char in (text or "")):
        danish += 2
    if danish == english == 0:
        return None
    if danish > english:
        return "da"
    if english > danish:
        return "en"
    return None


@dataclass(frozen=True)
class BarkleyResponse:
    """Payload returned to the API and used to drive the mascot video."""

    reply: str
    barkley_state: str  # One of: "speaking", "celebrating", "searching", "typing".
    interview_requested: bool
    suggest_questions: bool = False
    # Citations of the numbered passages retrieval returned, already resolved to
    # ``{label, title, url, lines}`` dicts (see _resolve_citations): the model only
    # ever proposes passage numbers, so a fabricated label — or an invented URL —
    # can never appear here.
    sources: tuple[dict[str, str], ...] = ()


# The model occasionally answers in prose instead of JSON, which Groq rejects
# with 400 json_validate_failed. Throwing that text away would lose a perfectly
# good answer, so the refusal is salvaged (see _salvage_failed_generation).
#
# JSON mode guarantees an object, not a clean `reply`: in practice the model
# sometimes appends its citation list to the prose ("Sources: ['a', 'b']", or a
# bare list/bullet run). Those lines are citation material by definition, so they
# are dropped — but a bullet or a bracketed line is only dropped when every item
# it carries is a number or a label retrieval actually returned. A real sentence
# that happens to start with a dash is left alone.
_SOURCES_LINE_RE = re.compile(
    r"^\s*(?:sources?|kilder?|kilde|references?|referencer|fonti|quellen)\s*[:\-–—].*$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*[-*•·]\s+(.+)$")
# A quoted, comma-separated list: a Python/JSON list is never prose.
_QUOTED_ITEM_RE = re.compile(r"^['\"`].+['\"`]$")


def _looks_like_citation_list(line: str, labels: set[str]) -> bool:
    """True when a line carries nothing but citation material (never prose)."""
    text = (line or "").strip().rstrip(".").strip()
    if not text:
        return False
    bullet = _BULLET_RE.match(text)
    payload = bullet.group(1) if bullet else text.strip("[](){} \t")
    items = [item for item in re.split(r"[,;|]", payload) if item.strip()]
    if not items or len(items) > 8:
        return False
    cleaned = [item.strip().strip("'\"`").strip() for item in items]
    if all(item.isdigit() for item in cleaned):
        return True  # a passage list: [1, 3]
    if labels and all(item.lower() in labels for item in cleaned):
        return True  # ['owner/repo', 'owner/repo']
    if len(items) > 1 and all(_QUOTED_ITEM_RE.match(item.strip()) for item in items):
        return True  # a quoted list of strings, whatever the labels were
    return False


def _strip_sources_lines(text: str, known_labels: set[str] | None = None) -> str:
    """Drop the citation list the model sometimes appends to the prose.

    ``known_labels`` are the labels of the citable passages, which is what makes
    the bullet/list branch safe to apply.
    """
    labels = {str(label).lower() for label in (known_labels or set())}
    kept = [
        line
        for line in (text or "").splitlines()
        if not _SOURCES_LINE_RE.match(line) and not _looks_like_citation_list(line, labels)
    ]
    return "\n".join(kept).strip()


def _salvage_failed_generation(exc: Exception) -> str:
    """Recover the answer Groq refused to accept in JSON mode.

    Returns the refused text when the error really is a ``json_validate_failed``
    (Groq embeds it in ``error.failed_generation``), otherwise an empty string.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - an unusable error body is just "no text"
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict) or error.get("code") != "json_validate_failed":
        return ""
    return str(error.get("failed_generation") or "").strip()


def _mentions_interview(text: str) -> bool:
    """Offline interview heuristic, reused for salvaged prose answers."""
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _INTERVIEW_HINTS)


def mentions_interview(text: str) -> bool:
    """Public door to the offline heuristic above.

    The API uses it as a *deterministic* backstop for the hand-off form: a
    request the model failed to flag — in either language — still counts when the
    message itself says it. It never replaces the model's judgement for the
    interview record or the notification (a keyword is not evidence enough to
    email anyone), it only decides whether the form may come back.
    """
    return _mentions_interview(text)


def generate_reply(
    user_message: str, history: list[dict] | None = None, language: str | None = None
) -> BarkleyResponse:
    """Produce BarklAI's reply for a message plus the prior conversation turns.

    ``history`` is a chronological list of ``{"role", "content"}`` dicts
    (``role`` is ``"user"`` or ``"assistant"``). ``language`` is the active
    interface language, used only as the fallback for ambiguous messages.
    """
    user_message = (user_message or "").strip()
    api_key = getattr(settings, "GROQ_API_KEY", "")

    if not api_key:
        return _offline_reply(user_message)

    ui_language = language or get_language() or "en"
    # The language the recruiter actually wrote in; ``None`` when undecidable.
    expected_language = detect_language(user_message)
    knowledge, passages = _knowledge_for_prompt(user_message)
    system_prompt = build_system_prompt(knowledge, ui_language, passages)

    # Primary model first, then the configured production fallback, so a
    # decommissioned preview model cannot take the whole chat down.
    primary_model = getattr(settings, "GROQ_MODEL", "")
    fallback_model = getattr(settings, "GROQ_MODEL_FALLBACK", "")
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)

    for position, model in enumerate(models):
        try:
            return _reply_from_model(
                user_message,
                history or [],
                api_key,
                system_prompt,
                passages,
                expected_language,
                model,
            )
        except Exception as exc:  # noqa: BLE001 - any failure -> salvage or copy
            salvaged = _salvage_failed_generation(exc)
            if salvaged:
                # The model answered in prose instead of JSON: Groq refused it,
                # but the answer itself is good (citations stay unknown).
                logger.warning("Groq rejected the JSON; keeping the prose answer.")
                labels = {str(passage.get("label") or "") for passage in passages}
                reply = _strip_sources_lines(salvaged, labels) or salvaged
                interview = _mentions_interview(reply)
                return BarkleyResponse(
                    reply=reply,
                    barkley_state="celebrating" if interview else "speaking",
                    interview_requested=interview,
                )
            if position + 1 < len(models):
                logger.warning(
                    "Model %s failed (%s); retrying with %s.",
                    model,
                    exc,
                    models[position + 1],
                )
                continue
            logger.exception("Groq request failed: %s", exc)
            return BarkleyResponse(
                reply=gettext(FALLBACK_UNREACHABLE),
                barkley_state="speaking",
                interview_requested=False,
            )

    # Unreachable while GROQ_MODEL is set, but kept so the contract is explicit.
    return BarkleyResponse(
        reply=gettext(FALLBACK_UNREACHABLE),
        barkley_state="speaking",
        interview_requested=False,
    )


def _reply_from_model(
    user_message: str,
    history: list[dict],
    api_key: str,
    system_prompt: str,
    passages: list[dict],
    expected_language: str | None,
    model: str,
) -> BarkleyResponse:
    """One model attempt, including the single language-guard retry."""
    result = _parse_reply(
        _call_groq(user_message, history, api_key, system_prompt, model),
        passages,
    )
    if _should_retry_for_language(expected_language, result.reply):
        logger.info(
            "Reply language mismatch (expected %s); asking Groq once more.",
            expected_language,
        )
        retry = _parse_reply(
            _call_groq(
                user_message,
                history,
                api_key,
                _correction_prompt(system_prompt, expected_language),
                model,
            ),
            passages,
        )
        if not _should_retry_for_language(expected_language, retry.reply):
            return retry
    return result


def _should_retry_for_language(expected: str | None, reply: str) -> bool:
    """True when the reply is confidently written in the wrong language."""
    if not expected or not getattr(settings, "AGENT_LANGUAGE_GUARD", True):
        return False
    detected = detect_language(reply)
    return detected is not None and detected != expected


def _correction_prompt(system_prompt: str, expected: str) -> str:
    """System prompt plus an explicit "rewrite it in <language>" correction."""
    return (
        system_prompt
        + "\n\nCORRECTION: your previous attempt answered in the wrong language. "
        "Rewrite the answer in "
        + language_name(expected)
        + ", keeping exactly the same facts. Return the same JSON object."
    )


def get_knowledge_text() -> str:
    """Concatenate the synced knowledge documents, capped for the prompt."""
    chunks = []
    for doc in KnowledgeDocument.objects.all():
        header = doc.title or doc.source
        if doc.url:
            header = f"{header} ({doc.url})"
        chunks.append(f"### {header}\n{doc.content}")
    max_chars = getattr(settings, "AGENT_KNOWLEDGE_MAX_CHARS", 12000)
    return "\n\n".join(chunks)[:max_chars]


def _knowledge_for_prompt(user_message: str) -> tuple[str, list[dict]]:
    """Knowledge text for the system prompt plus the citable passages.

    With RAG enabled (``RAG_ENABLED=True``) only the chunks that match the
    question are sent, numbered so the model can cite them by number (see
    ``chat.rag.build_retrieved_context_with_citations``); otherwise the whole
    knowledge base is stuffed in, as a safe fallback for a small corpus — in that
    case there is nothing to cite, because no per-passage retrieval happened.
    """
    if getattr(settings, "RAG_ENABLED", False):
        from chat.rag import build_retrieved_context_with_citations

        context, passages = build_retrieved_context_with_citations(user_message)
        if context:
            return context, passages
    return get_knowledge_text(), []


def _call_groq(
    user_message: str,
    history: list[dict],
    api_key: str,
    system_prompt: str,
    model: str = "",
) -> str:
    """Call Groq in JSON mode and return the raw assistant content."""
    from groq import Groq  # Imported lazily so the mock path needs no SDK.

    client = Groq(api_key=api_key, timeout=settings.GROQ_TIMEOUT_SECONDS)
    messages = [{"role": "system", "content": system_prompt}]
    limit = getattr(settings, "AGENT_HISTORY_LIMIT", 20)
    for turn in history[-limit:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    completion = client.chat.completions.create(
        model=model or settings.GROQ_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=settings.GROQ_TEMPERATURE,
        max_tokens=settings.GROQ_MAX_TOKENS,
    )
    return completion.choices[0].message.content


def _parse_reply(
    raw: str, passages: list[dict] | None = None
) -> BarkleyResponse:
    """Turn the model's JSON (tolerantly parsed) into a ``BarkleyResponse``.

    ``passages`` are the numbered passages retrieval returned. Their labels feed
    the prose sanitiser (so a citation list the model wrote into ``reply`` never
    reaches the recruiter) and their numbers are the only citations allowed
    through, see :func:`_resolve_citations`.
    """
    data = _loads_json_object(raw)
    passages = passages or []
    labels = {str(passage.get("label") or "") for passage in passages}
    reply = _strip_sources_lines(str(data.get("reply") or "").strip(), labels).strip()
    interview = bool(data.get("interview_requested"))
    return BarkleyResponse(
        reply=reply or FALLBACK_UNREACHABLE,
        barkley_state="celebrating" if interview else "speaking",
        interview_requested=interview,
        suggest_questions=bool(data.get("suggest_questions")),
        sources=_resolve_citations(data.get("sources"), passages),
    )


def _resolve_citations(raw, passages: list[dict]) -> tuple[dict, ...]:
    """Map what the model cited onto the passages retrieval actually returned.

    The same idea as the language guard: the model proposes, the server decides.
    Passage numbers are the documented form and the legacy label form is still
    accepted (the prompt used to ask for labels, and a stubbed or cached answer
    may still use it); anything else — an invented number, a label that was never
    retrieved — is dropped rather than shown to a recruiter as evidence.
    """
    if not isinstance(raw, list) or not passages:
        return ()
    by_id = {int(passage["id"]): passage for passage in passages}
    by_label = {str(passage["label"]).lower(): passage for passage in passages}
    kept: list[dict] = []
    seen: set[int] = set()
    for item in raw:
        if isinstance(item, bool):  # bool is an int subclass: never a passage
            continue
        passage = None
        if isinstance(item, int):
            passage = by_id.get(item)
        elif isinstance(item, str):
            text = item.strip()
            passage = (
                by_id.get(int(text))
                if text.isdigit()
                else by_label.get(_label_key(text))
            )
        if passage is not None and passage["id"] not in seen:
            seen.add(passage["id"])
            kept.append(_citation_out(passage))
    return tuple(kept)


def _label_key(text: str) -> str:
    """``owner/repo#L12-L24`` and ``owner/repo (lines 12-24)`` → ``owner/repo``."""
    return re.split(r"[#(]", (text or "").strip(), maxsplit=1)[0].strip().lower()


def _citation_out(passage: dict) -> dict:
    """The persisted/API shape of a citation (the passage number stays internal)."""
    return {
        "label": str(passage.get("label") or ""),
        "title": str(passage.get("title") or ""),
        "url": str(passage.get("url") or ""),
        "lines": str(passage.get("lines") or ""),
    }


def _loads_json_object(raw: str) -> dict:
    """Best-effort JSON extraction (tolerates code fences or extra prose)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("Groq reply was not valid JSON; using it as plain text.")
        return {"reply": (raw or "").strip()}
    return data if isinstance(data, dict) else {"reply": (raw or "").strip()}


def _offline_reply(user_message: str) -> BarkleyResponse:
    """Consistent, in-character fallback used when no API key is configured.

    The copy follows the language the recruiter wrote in (the strings are
    translated in ``locale/da``), so offline mode stays bilingual too.
    """
    text = user_message.lower()
    is_interview = any(hint in text for hint in _INTERVIEW_HINTS)
    # Prefer the language of the message; fall back to the interface language.
    with translation.override(detect_language(user_message) or get_language() or "en"):
        if is_interview:
            return BarkleyResponse(
                reply=gettext(FALLBACK_INTERVIEW),
                barkley_state="celebrating",
                interview_requested=True,
            )
        return BarkleyResponse(
            reply=gettext(FALLBACK_NO_KEY),
            barkley_state="speaking",
            interview_requested=False,
        )