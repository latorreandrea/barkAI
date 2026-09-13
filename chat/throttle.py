"""Fixed-window rate limiting for the public chat endpoints.

Simple by design: Django's cache keeps a per-key counter for the configured
window. It is best-effort — a multi-process deployment without a shared cache
enforces the limit per worker — but it is enough to stop one client from burning
the Groq / Cloudflare quota, which is the point.
"""
from __future__ import annotations

from django.core.cache import cache

_KEY_PREFIX = "barkai:throttle:"


def _bump(key: str, window_seconds: int) -> int:
    """Increment the counter for ``key`` and return the new value."""
    cache.add(key, 0, window_seconds)
    try:
        return cache.incr(key)
    except ValueError:
        # The key expired between add() and incr(): restart the window.
        cache.set(key, 1, window_seconds)
        return 1


def too_many_requests(identifier: str, limit: int, window_seconds: int) -> bool:
    """True once ``identifier`` exceeds ``limit`` hits inside the window.

    A non-positive ``limit`` disables the check (handy for tests and for local
    development, where ``CHAT_RATE_LIMIT_*`` can be set to ``0``).
    """
    if limit <= 0:
        return False
    return _bump(f"{_KEY_PREFIX}{identifier}", window_seconds) > limit
