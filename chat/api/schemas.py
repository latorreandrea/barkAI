"""Pydantic schemas (request/response contracts) for the chat REST API."""
from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import Field


class MessageOut(Schema):
    """A single chat message returned to the browser."""

    id: int
    sender: str  # "user" | "assistant"
    content: str
    # Knowledge-base labels BarklAI cited (always empty on a user turn).
    sources: list[str] = []
    created_at: datetime


class ContactInfo(Schema):
    """Who to answer with: the contact details the conversation has collected.

    All three are optional and the UI never invents them: they come from the
    hand-off form or from an address the recruiter typed in a message. The chat
    page shows them back in the form (prefilled for confirmation) instead of
    asking the recruiter to type what it already knows.
    """

    hr_name: str = ""
    hr_email: str = ""
    company_name: str = ""


class HistoryOut(Schema):
    """Full persisted history of one ChatSession."""

    session_id: UUID
    interview_requested: bool
    messages: list[MessageOut]
    contact: ContactInfo = Field(default_factory=ContactInfo)


class SendIn(Schema):
    """Payload for POST /api/chat/send."""

    session_id: UUID
    # Hard caps mirroring the composer's maxlength; oversized input is a 422.
    message: str = Field(..., min_length=1, max_length=2000)
    hr_name: str = Field("", max_length=120)
    hr_email: str = Field("", max_length=254)
    company_name: str = Field("", max_length=160)


class BarkleyOut(Schema):
    """BarklAI's reply plus the mascot animation state."""

    session_id: UUID
    reply: str
    barkley_state: str  # e.g. "speaking", "celebrating", "searching", "typing"
    interview_requested: bool
    # True when the agent thinks the recruiter is unsure what to ask, so the UI
    # can offer the quick-question chips inside the speech bubble.
    suggest_questions: bool = False
    # Knowledge-base labels the reply is grounded in (already validated against
    # the retrieved chunks, so an invented label can never appear here).
    sources: list[str] = []
    # What the conversation knows about the recruiter (see ContactInfo): the UI
    # uses it to prefill the hand-off form for confirmation.
    contact: ContactInfo = Field(default_factory=ContactInfo)


class ContactIn(Schema):
    """Payload for POST /api/chat/contact (the interview hand-off form).

    An email is required: the whole point of the form is giving Andrea a way to
    reply to the recruiter.
    """

    session_id: UUID
    hr_name: str = Field("", max_length=120)
    hr_email: str = Field(..., min_length=1, max_length=254)
    company_name: str = Field("", max_length=160)


class ContactOut(Schema):
    """Confirmation that the recruiter's details were stored."""

    session_id: UUID
    saved: bool
    # False when notifications are disabled (INTERVIEW_NOTIFY_EMAIL blank) or the
    # SMTP send failed; the details are stored either way.
    notified: bool