"""BarklAI's reply service layer.

This module is the seam where the future Groq (Qwen 2.5) + RAG pipeline will be
plugged in. For now ``generate_reply()`` returns deterministic mock answers so
the UI, persistence layer, and REST API can be developed and tested end to end.
"""
from dataclasses import dataclass

# Words that strongly suggest a recruiter wants to book an interview.
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
)

_GREETINGS = ("hello", "hi", "hey", "howdy", "good morning", "good afternoon", "good evening")


@dataclass(frozen=True)
class BarkleyResponse:
    """Payload returned to the API and used to drive the mascot video."""

    reply: str
    barkley_state: str  # One of: "speaking", "celebrating", "searching", "typing".
    interview_requested: bool


def generate_reply(user_message: str) -> BarkleyResponse:
    """Produce BarklAI's (mock) reply for a given user message."""
    text = (user_message or "").strip().lower()

    if any(hint in text for hint in _INTERVIEW_HINTS):
        return BarkleyResponse(
            reply=(
                "Woof - wonderful! 🎉 It sounds like you would like to schedule an "
                "interview. I have flagged this opportunity for Andrea and sent a "
                "notification. This is a mock response for now: the real agent will "
                "collect your details and confirm a slot shortly."
            ),
            barkley_state="celebrating",
            interview_requested=True,
        )

    if text in _GREETINGS or any(text.startswith(prefix) for prefix in _GREETINGS):
        return BarkleyResponse(
            reply=(
                "Woof! 👋 I am BarklAI, Andrea's AI career companion. Ask me anything "
                "about his open-source projects, Python/cloud architecture, or RAG "
                "pipelines - or request an interview right here in the chat!"
            ),
            barkley_state="speaking",
            interview_requested=False,
        )

    return BarkleyResponse(
        reply=(
            "Woof! Great question. 🐾 Andrea is a Python/Django engineer who builds "
            "RAG-powered agents and cloud architectures. I searched the indexed "
            "repositories and career docs to fetch the most accurate answer - this "
            "mock reply will soon be backed by the Groq (Qwen 2.5) pipeline. Ask me "
            "about his tech stack, past projects, or to schedule an interview!"
        ),
        barkley_state="speaking",
        interview_requested=False,
    )