"""Django Ninja router with the chat endpoints.

Endpoint paths are relative to the /api prefix configured in ``config/urls.py``,
so the full paths are ``/api/chat/history/{session_id}`` and ``/api/chat/send``.
"""
from uuid import UUID

from ninja import Router

from chat.api.schemas import BarkleyOut, HistoryOut, MessageOut, SendIn
from chat.models import ChatMessage, ChatSession
from chat.services import generate_reply

router = Router(tags=["chat"])


def _serialize_message(message: ChatMessage) -> MessageOut:
    """Map an ORM ChatMessage onto its response schema."""
    return MessageOut(
        id=message.id,
        sender=message.sender,
        content=message.content,
        created_at=message.created_at,
    )


def _get_or_create_session(session_id: UUID) -> ChatSession:
    """Return the requested session, creating it on first contact.

    Recruiters never log in: the UUID itself is the identity. This mirrors the
    product requirement of friction-free, persistent conversations.
    """
    return ChatSession.objects.get_or_create(session_id=session_id)[0]


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

    # 4) Persist Barkley's reply.
    ChatMessage.objects.create(
        session=session,
        sender=ChatMessage.Sender.ASSISTANT,
        content=result.reply,
    )

    # 5) Flag the session when an interview was requested; bump last_active.
    if result.interview_requested:
        session.interview_requested = True
    session.save()

    return BarkleyOut(
        session_id=session.session_id,
        reply=result.reply,
        barkley_state=result.barkley_state,
        interview_requested=session.interview_requested,
        suggest_questions=result.suggest_questions,
    )