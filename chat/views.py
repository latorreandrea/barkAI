"""HTTP views for the chat application (each app owns its views)."""
from uuid import UUID

from django.shortcuts import render


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
