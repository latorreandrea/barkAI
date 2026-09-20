"""Interview-request capture: the durable record Andrea acts on.

The agent only *detects* intent (``interview_requested`` in its JSON reply).
This module turns that intent — plus the recruiter's contact details, whenever
the form in the composer provides them — into an :class:`InterviewRequest` row.

Capture rule (deliberately simple and predictable):

* the session's **pending** request (``notified_at`` is ``NULL``) is reused and
  updated, so editing the form does not pile up duplicates;
* an already-notified request is reused while the email is unchanged (or still
  unknown), so a repeated ``/send`` cannot re-notify Andrea;
* a genuinely **different** email is a new event row — the recruiter corrected
  their address and Andrea must hear about it.

The ``hr_*`` columns on ``ChatSession`` are refreshed too: they are the
denormalised "latest contact" cache used by the admin list and its search box.
"""
from __future__ import annotations

import re

from django.utils import timezone

from chat.models import ChatMessage, InterviewRequest

# Longest triggering message kept for context (the rest is dropped).
_MESSAGE_MAX_CHARS = 1000

# An address the recruiter typed in the chat itself ("I'm Jane, jane@acme.com").
# Deliberately permissive and punctuation-free at the end: the hand-off form
# shows the address back for confirmation, so a stray capture costs one edit.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def extract_contact(text: str) -> dict[str, str]:
    """Contact details volunteered in a message — the email, when there is one.

    The agent asks for name, email and company in the same reply that flags an
    interview, so recruiters often just *write* the address in the chat instead
    of using the form. Reading it back is deterministic (no LLM call), and the
    form shows it prefilled for confirmation. A name or a company written in
    prose ("I'm Jane from Acme") is left to the form rather than guessed with a
    pattern; only the address is needed to answer the recruiter.
    """
    match = _EMAIL_RE.search(text or "")
    if not match:
        return {}
    return {"hr_email": match.group(0)[:254]}


def capture_interview_request(
    session,
    *,
    hr_name: str = "",
    hr_email: str = "",
    company_name: str = "",
    message: str = "",
    language: str = "",
) -> InterviewRequest:
    """Record (or update) the session's interview request and return it."""
    request_obj = _target_request(session, hr_email)

    if hr_name:
        request_obj.hr_name = hr_name[:120]
    if hr_email:
        request_obj.hr_email = hr_email
    if company_name:
        request_obj.company_name = company_name[:160]
    if message:
        request_obj.message = message[:_MESSAGE_MAX_CHARS]
    if language:
        request_obj.language = language[:8]
    request_obj.save()

    _sync_session_contact(session, request_obj)
    return request_obj


def _target_request(session, hr_email: str) -> InterviewRequest:
    """Which row this capture belongs to (see the capture rule above)."""
    latest = session.interview_requests.order_by("-created_at").first()
    if latest is None:
        return InterviewRequest(session=session)
    if latest.notified_at is None:
        return latest
    # Already notified: only a *different* address starts a new event.
    if not hr_email or hr_email == latest.hr_email:
        return latest
    return InterviewRequest(session=session)


def mark_notified(request_obj: InterviewRequest) -> None:
    """Stamp a successful notification."""
    request_obj.notified_at = timezone.now()
    request_obj.notification_error = ""
    request_obj.save(update_fields=["notified_at", "notification_error"])


def mark_notification_failed(request_obj: InterviewRequest, error: str) -> None:
    """Remember why the notification failed (surfaced by the retry command)."""
    request_obj.notification_error = (error or "")[:255]
    request_obj.save(update_fields=["notification_error"])


def last_user_message(session) -> str:
    """The most recent recruiter message, used as the request's context."""
    message = (
        session.messages.filter(sender=ChatMessage.Sender.USER)
        .order_by("-created_at", "-id")
        .first()
    )
    return message.content if message else ""


def _sync_session_contact(session, request_obj: InterviewRequest) -> None:
    """Mirror the latest contact onto the session (admin list + search)."""
    if request_obj.hr_name:
        session.hr_name = request_obj.hr_name
    if request_obj.hr_email:
        session.hr_email = request_obj.hr_email
    if request_obj.company_name:
        session.company_name = request_obj.company_name
    session.interview_requested = True
    session.save()
