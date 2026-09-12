"""HTTP views for the chat application (each app owns its views)."""
import json
from uuid import UUID

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import ChatSession


def index(request):
    """Render the single-page Barkley chat interface.

    A session_id may arrive through the ``?session_id=`` query string (e.g. when
    a recruiter opens a shared link). Otherwise the browser generates a UUID on
    the client side, so Barkley's conversation survives page reloads.
    """
    session_id = None
    raw_session_id = request.GET.get("session_id")
    if raw_session_id:
        try:
            session_id = str(UUID(raw_session_id))
        except (ValueError, AttributeError):
            session_id = None

    return render(
        request,
        "chat/index.html",  # App-scoped template: chat/templates/chat/index.html
        {"initial_session_id": session_id},
    )


def privacy(request):
    """Render the privacy notice (GDPR transparency, art. 13)."""
    return render(
        request,
        "chat/privacy.html",
        {
            "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
            "retention_days": settings.SESSION_RETENTION_DAYS,
        },
    )


@require_POST
def delete_session(request):
    """Erase the requester's conversation (GDPR right to erasure, art. 17).

    The browser posts the session UUID it holds in localStorage; the session and
    its messages are deleted from the database. CSRF is enforced by middleware,
    so the caller must send the ``X-CSRFToken`` header (like the chat API).
    """
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        payload = {}

    raw_session_id = payload.get("session_id") or request.POST.get("session_id")
    try:
        session_uuid = UUID(str(raw_session_id))
    except (ValueError, TypeError):
        return JsonResponse({"deleted": False, "error": "invalid session_id"}, status=400)

    deleted, _ = ChatSession.objects.filter(session_id=session_uuid).delete()
    return JsonResponse({"deleted": bool(deleted)})
