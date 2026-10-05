import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self) -> None:
        """Say so when the process starts without ``GROQ_API_KEY``.

        A key-less server does not crash: every reply becomes the in-character
        ``FALLBACK_NO_KEY`` copy and interview detection degrades to the keyword
        heuristics. That is fine for a demo and costly in production — a real
        session ran that way, and the recruiter's address was never notified.
        Settings are read from the environment only (python-dotenv is deliberately
        not used), so a server started without ``set -a; source .env; set +a``
        silently loses every value in the file.
        """
        from django.conf import settings

        if not str(getattr(settings, "GROQ_API_KEY", "") or "").strip():
            logger.warning(
                "GROQ_API_KEY is empty: BarklAI answers with the offline fallback "
                "and interview intent falls back to the keyword heuristics. Export "
                "the environment before starting the server "
                "(set -a; source .env; set +a)."
            )
