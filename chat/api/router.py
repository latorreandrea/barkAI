"""Django Ninja router with the chat endpoints.

Endpoint paths are relative to the /api prefix configured in ``barkai/urls.py``,
so the full paths are ``/api/chat/history/{session_id}``, ``/api/chat/send`` and
``/api/chat/contact`` (the interview hand-off form).
"""
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import get_language
from ninja import Router
from ninja.errors import HttpError

from chat.api.schemas import (
    BarkleyOut,
    ContactIn,
    ContactOut,
    HistoryOut,
    MessageOut,
    SendIn,
)
from chat.interviews import capture_interview_request, last_user_message
from chat.models import ChatMessage, ChatSession
from chat.notifications import notify_interview_requested
from chat.services import generate_reply
from chat.throttle import too_many_requests

router = Router(tags=["chat"])


def _serialize_message(message: ChatMessage) -> MessageOut:
    """Map an ORM ChatMessage onto its response schema."""
    return MessageOut(
        id=message.id,
        sender=message.sender,
        content=message.content,
        sources=message.sources or [],
        created_at=message.created_at,
    )


def _get_or_create_session(session_id: UUID) -> ChatSession:
    """Return the requested session, creating it on first contact.

    Recruiters never log in: the UUID itself is the identity. This mirrors the
    product requirement of friction-free, persistent conversations.
    """
    return ChatSession.objects.get_or_create(session_id=session_id)[0]


def _client_ip(request) -> str:
    """Best-effort client IP (honours a reverse proxy's ``X-Forwarded-For``)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _enforce_rate_limit(request, session_id: UUID) -> None:
    """429 when this session or client IP hammers the public chat endpoints."""
    window = settings.CHAT_RATE_LIMIT_WINDOW_SECONDS
    hit_session = too_many_requests(
        f"session:{session_id}", settings.CHAT_RATE_LIMIT_PER_SESSION, window
    )
    hit_ip = too_many_requests(
        f"ip:{_client_ip(request)}", settings.CHAT_RATE_LIMIT_PER_IP, window
    )
    if hit_session or hit_ip:
        raise HttpError(
            429, "Too many messages in a short time. Please wait a moment. 🐾"
        )


@router.get("/history/{session_id}", response=HistoryOut)
def get_chat_history(request, session_id: UUID) -> HistoryOut:
    """Return the persisted conversation for a session (creating it if needed)."""
    session = _get_or_create_session(session_id)
    return HistoryOut(
        session_id=session.session_id,
        interview_requested=session.interview_requested,
        messages=[_serialize_message(message) for message in session.messages.all()],
    )


@router.post("/send", response=BarkleyOut)
def send_message(request, payload: SendIn) -> BarkleyOut:
    """Persist a user turn, generate Barkley's reply, and persist that too."""
    _enforce_rate_limit(request, payload.session_id)
    session = _get_or_create_session(payload.session_id)

    # Optionally enrich the session with recruiter metadata supplied by the UI.
    if payload.hr_name:
        session.hr_name = payload.hr_name
    if payload.hr_email:
        session.hr_email = payload.hr_email
    if payload.company_name:
        session.company_name = payload.company_name

    # 1) Persist the user's message.
    user_message = ChatMessage.objects.create(
        session=session,
        sender=ChatMessage.Sender.USER,
        content=payload.message.strip(),
    )

    # 2) Hand the model the previous turns (chronological, excluding the one we
    #    just stored) so BarklAI keeps the conversation context.
    history = [
        {
            "role": "assistant"
            if message.sender == ChatMessage.Sender.ASSISTANT
            else "user",
            "content": message.content,
        }
        for message in session.messages.exclude(pk=user_message.pk)
    ]

    # 3) Ask the agent service for Barkley's reply.
    result = generate_reply(payload.message, history)

    # 4) Persist Barkley's reply (with the sources it cited, so the citations
    #    survive a page reload and stay visible in the history).
    ChatMessage.objects.create(
        session=session,
        sender=ChatMessage.Sender.ASSISTANT,
        content=result.reply,
        sources=list(result.sources),
    )

    # 5) Flag the session when an interview was requested; bump last_active.
    if result.interview_requested:
        # Record the request as an event, then notify Andrea as soon as we have
        # an email for the recruiter (the hand-off form fills it in afterwards).
        interview_request = capture_interview_request(
            session,
            hr_name=payload.hr_name,
            hr_email=payload.hr_email,
            company_name=payload.company_name,
            message=payload.message,
            language=get_language() or "",
        )
        if interview_request.hr_email:
            notify_interview_requested(interview_request)
    else:
        session.save()

    return BarkleyOut(
        session_id=session.session_id,
        reply=result.reply,
        barkley_state=result.barkley_state,
        interview_requested=session.interview_requested,
        suggest_questions=result.suggest_questions,
        sources=list(result.sources),
    )


@router.post("/contact", response=ContactOut)
def save_contact(request, payload: ContactIn) -> ContactOut:
    """Store the recruiter's details for an interview request.

    Called by the hand-off form BarklAI reveals once an interview is requested.
    It does **not** invoke the LLM: it only records the contact and emails Andrea
    (when notifications are configured), so leaving the details is free.
    """
    _enforce_rate_limit(request, payload.session_id)

    email = payload.hr_email.strip()
    try:
        validate_email(email)
    except ValidationError:
        raise HttpError(422, "Please provide a valid email address.")

    session = _get_or_create_session(payload.session_id)
    interview_request = capture_interview_request(
        session,
        hr_name=payload.hr_name.strip(),
        hr_email=email,
        company_name=payload.company_name.strip(),
        message=last_user_message(session),
        language=get_language() or "",
    )
    notified = notify_interview_requested(interview_request)
    return ContactOut(session_id=session.session_id, saved=True, notified=notified)