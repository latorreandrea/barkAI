"""Project-level views: they belong to the deployment, not to the chat app."""
from __future__ import annotations

from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Liveness/readiness probe for the platform (Cloud Run, k8s, uptime checks).

    Deliberately cheap and boring: one round-trip to the database plus a count of
    the embedded chunks. It never calls the LLM providers, so a Groq or
    Cloudflare outage cannot make the container look dead, and it exposes no
    personal data. Returns ``503`` when the database is unreachable.
    """
    from chat.models import KnowledgeChunk  # local import keeps boot light

    database_ok = True
    indexed_chunks = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        indexed_chunks = KnowledgeChunk.objects.filter(
            embedding__isnull=False
        ).count()
    except Exception:  # noqa: BLE001 - any database problem means "not ready"
        database_ok = False

    payload = {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "indexed_chunks": indexed_chunks,
    }
    return JsonResponse(payload, status=200 if database_ok else 503)
