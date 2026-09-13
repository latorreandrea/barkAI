"""Outbound notifications for high-intent events (interview requests).

Deliberately small: it never raises into the request cycle — a mail outage must
not break the recruiter's chat. When ``INTERVIEW_NOTIFY_EMAIL`` is blank the
notification is skipped, which is what local development and the test suite want.

The outcome is recorded on the request itself (``notified_at`` /
``notification_error``), so `python manage.py retry_interview_notifications` can
re-send whatever is still pending after an SMTP hiccup.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from chat.interviews import mark_notification_failed, mark_notified
from chat.models import InterviewRequest

logger = logging.getLogger(__name__)

# Subject of the "a recruiter wants an interview" email.
SUBJECT = "🐾 BarkAI: a recruiter requested an interview"


def interview_admin_url(request_obj: InterviewRequest) -> str:
    """Deep link to the request in the admin (empty without ``SITE_BASE_URL``)."""
    base = getattr(settings, "SITE_BASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/admin/chat/interviewrequest/{request_obj.pk}/change/"


def interview_email_body(request_obj: InterviewRequest) -> str:
    """Plain-text body: everything Andrea needs to reply to the recruiter."""
    lines = [
        "BarklAI caught an interview request. 🐾",
        "",
        f"Name:      {request_obj.hr_name or '—'}",
        f"Email:     {request_obj.hr_email or '—'}",
        f"Company:   {request_obj.company_name or '—'}",
        f"Language:  {request_obj.language or '—'}",
        f"Requested: {request_obj.created_at:%Y-%m-%d %H:%M} UTC",
        "",
        "Message that triggered it:",
        request_obj.message or "(not stored)",
        "",
        f"Session:   {request_obj.session_id}",
    ]
    url = interview_admin_url(request_obj)
    if url:
        lines += ["", f"Open in the admin: {url}"]
    return "\n".join(lines)


def notify_interview_requested(request_obj: InterviewRequest) -> bool:
    """Email Andrea about an interview request. Never raises.

    Returns ``True`` when the message was handed to the mail backend (the
    request is then stamped with ``notified_at``); ``False`` when notifications
    are disabled or the send failed. Calling it twice for the same request is
    safe: an already-notified request is never sent again.
    """
    if request_obj.notified_at is not None:
        logger.info("Interview request %s was already notified.", request_obj.pk)
        return True

    recipient = getattr(settings, "INTERVIEW_NOTIFY_EMAIL", "").strip()
    if not recipient:
        logger.info("Interview notification skipped: INTERVIEW_NOTIFY_EMAIL is blank.")
        return False

    try:
        send_mail(
            subject=SUBJECT,
            message=interview_email_body(request_obj),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - SMTP problems must not bubble up
        logger.warning("Interview notification failed: %s", exc)
        mark_notification_failed(request_obj, str(exc))
        return False

    mark_notified(request_obj)
    return True
