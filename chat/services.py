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
# model decides this itself; the offline fallback uses these heuristics. Both
# languages are covered, otherwise a Danish recruiter would never be flagged
# while Groq is unreachable.
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
    # Knowledge-base labels the answer is grounded in, already validated against
    # the chunks retrieval returned (see _sanitize_sources).
    sources: tuple[str, ...] = ()


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
    knowledge, allowed_sources = _knowledge_for_prompt(user_message)
    system_prompt = build_system_prompt(knowledge, ui_language, allowed_sources)

    try:
        result = _parse_reply(
            _call_groq(user_message, history or [], api_key, system_prompt),
            allowed_sources,
        )
        if _should_retry_for_language(expected_language, result.reply):
            logger.info(
                "Reply language mismatch (expected %s); asking Groq once more.",
                expected_language,
            )
            retry = _parse_reply(
                _call_groq(
                    user_message,
                    history or [],
                    api_key,
                    _correction_prompt(system_prompt, expected_language),
                ),
                allowed_sources,
            )
            if not _should_retry_for_language(expected_language, retry.reply):
                return retry
        return result
    except Exception as exc:  # noqa: BLE001 - any client/network failure -> copy
        logger.exception("Groq request failed: %s", exc)
        return BarkleyResponse(
            reply=gettext(FALLBACK_UNREACHABLE),
            barkley_state="speaking",
            interview_requested=False,
        )


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


def _knowledge_for_prompt(user_message: str) -> tuple[str, list[str]]:
    """Knowledge text for the system prompt plus the citable source labels.

    With RAG enabled (``RAG_ENABLED=True``) only the chunks that match the
    question are sent; otherwise the whole knowledge base is stuffed in, as a
    safe fallback for a small corpus — in that case there are no citation labels
    because no per-chunk retrieval happened.
    """
    if getattr(settings, "RAG_ENABLED", False):
        from chat.rag import build_retrieved_context_with_sources

        context, sources = build_retrieved_context_with_sources(user_message)
        if context:
            return context, sources
    return get_knowledge_text(), []


def _call_groq(
    user_message: str, history: list[dict], api_key: str, system_prompt: str
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
        model=settings.GROQ_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=settings.GROQ_TEMPERATURE,
        max_tokens=settings.GROQ_MAX_TOKENS,
    )
    return completion.choices[0].message.content


def _parse_reply(
    raw: str, allowed_sources: list[str] | None = None
) -> BarkleyResponse:
    """Turn the model's JSON (tolerantly parsed) into a ``BarkleyResponse``.

    ``allowed_sources`` are the labels retrieval actually returned; any other
    label the model invents is dropped by :func:`_sanitize_sources`.
    """
    data = _loads_json_object(raw)
    reply = str(data.get("reply") or "").strip() or FALLBACK_UNREACHABLE
    interview = bool(data.get("interview_requested"))
    return BarkleyResponse(
        reply=reply,
        barkley_state="celebrating" if interview else "speaking",
        interview_requested=interview,
        suggest_questions=bool(data.get("suggest_questions")),
        sources=_sanitize_sources(data.get("sources"), allowed_sources or []),
    )


def _sanitize_sources(raw, allowed: list[str]) -> tuple[str, ...]:
    """Keep only the labels that were actually retrieved, in a stable order.

    The same idea as the language guard: the model proposes, the server decides.
    A cited source that retrieval never returned is dropped rather than shown to
    a recruiter as evidence.
    """
    if not isinstance(raw, list) or not allowed:
        return ()
    by_label = {label.lower(): label for label in allowed}
    kept: list[str] = []
    for item in raw:
        label = by_label.get(str(item).strip().lower())
        if label and label not in kept:
            kept.append(label)
    return tuple(kept)


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