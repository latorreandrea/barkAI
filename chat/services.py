"""BarklAI's reply service layer.

This is the seam between the chat API and the agent. When ``GROQ_API_KEY`` is
set, :func:`generate_reply` asks the Groq LLM (JSON mode) for a structured
answer grounded in the knowledge base (career profile + GitHub READMEs). When
the key is missing — or when Groq is unreachable — BarklAI falls back to a
consistent, in-character message that playfully reports the connection problem,
so the recruiter always gets an answer instead of a stack trace.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils.translation import gettext

from chat.models import KnowledgeDocument
from chat.prompts import build_system_prompt

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
# model decides this itself; the offline fallback uses these heuristics.
_INTERVIEW_HINTS = (
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


@dataclass(frozen=True)
class BarkleyResponse:
    """Payload returned to the API and used to drive the mascot video."""

    reply: str
    barkley_state: str  # One of: "speaking", "celebrating", "searching", "typing".
    interview_requested: bool
    suggest_questions: bool = False


def generate_reply(
    user_message: str, history: list[dict] | None = None
) -> BarkleyResponse:
    """Produce BarklAI's reply for a message plus the prior conversation turns.

    ``history`` is a chronological list of ``{"role", "content"}`` dicts
    (``role`` is ``"user"`` or ``"assistant"``).
    """
    user_message = (user_message or "").strip()
    api_key = getattr(settings, "GROQ_API_KEY", "")

    if not api_key:
        return _offline_reply(user_message)

    try:
        raw = _call_groq(user_message, history or [], api_key)
    except Exception as exc:  # noqa: BLE001 - any client/network failure -> copy
        logger.exception("Groq request failed: %s", exc)
        return BarkleyResponse(
            reply=gettext(FALLBACK_UNREACHABLE),
            barkley_state="speaking",
            interview_requested=False,
        )
    return _parse_reply(raw)


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


def _knowledge_for_prompt(user_message: str) -> str:
    """Knowledge text for the system prompt.

    With RAG enabled (``RAG_ENABLED=True``) only the chunks that match the
    question are sent; otherwise the whole knowledge base is stuffed in, as a
    safe fallback for a small corpus.
    """
    if getattr(settings, "RAG_ENABLED", False):
        from chat.rag import build_retrieved_context

        context = build_retrieved_context(user_message)
        if context:
            return context
    return get_knowledge_text()


def _call_groq(user_message: str, history: list[dict], api_key: str) -> str:
    """Call Groq in JSON mode and return the raw assistant content."""
    from groq import Groq  # Imported lazily so the mock path needs no SDK.

    client = Groq(api_key=api_key, timeout=settings.GROQ_TIMEOUT_SECONDS)
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(_knowledge_for_prompt(user_message)),
        }
    ]
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


def _parse_reply(raw: str) -> BarkleyResponse:
    """Turn the model's JSON (tolerantly parsed) into a ``BarkleyResponse``."""
    data = _loads_json_object(raw)
    reply = str(data.get("reply") or "").strip() or FALLBACK_UNREACHABLE
    interview = bool(data.get("interview_requested"))
    return BarkleyResponse(
        reply=reply,
        barkley_state="celebrating" if interview else "speaking",
        interview_requested=interview,
        suggest_questions=bool(data.get("suggest_questions")),
    )


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
    """Consistent, in-character fallback used when no API key is configured."""
    text = user_message.lower()
    if any(hint in text for hint in _INTERVIEW_HINTS):
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