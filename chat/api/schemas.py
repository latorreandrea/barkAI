"""Pydantic schemas (request/response contracts) for the chat REST API."""
from datetime import datetime
from uuid import UUID

from ninja import Schema


class MessageOut(Schema):
    """A single chat message returned to the browser."""

    id: int
    sender: str  # "user" | "assistant"
    content: str
    created_at: datetime


class HistoryOut(Schema):
    """Full persisted history of one ChatSession."""

    session_id: UUID
    interview_requested: bool
    messages: list[MessageOut]


class SendIn(Schema):
    """Payload for POST /api/chat/send."""

    session_id: UUID
    message: str
    hr_name: str = ""
    hr_email: str = ""
    company_name: str = ""


class BarkleyOut(Schema):
    """BarklAI's reply plus the mascot animation state."""

    session_id: UUID
    reply: str
    barkley_state: str  # e.g. "speaking", "celebrating", "searching", "typing"
    interview_requested: bool