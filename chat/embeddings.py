"""Embedding providers for the RAG retrieval layer.

The provider is pluggable through ``EMBEDDING_PROVIDER``:

* ``cloudflare`` (default once configured) — Cloudflare Workers AI, model
  ``@cf/baai/bge-m3`` (multilingual: Danish + English, 1024 dimensions),
  called over its REST API with httpx. Cloudflare keeps the models on their own
  infrastructure and does **not** train on the content (no consent needed).
* ``none`` — embeddings disabled; the agent falls back to context stuffing.

Documents and queries MUST be embedded with the same provider/model, otherwise
the vectors are not comparable.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

CLOUDFLARE_RUN_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
)


class EmbeddingError(RuntimeError):
    """Raised when an embedding request cannot be completed."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; returns one vector per input, in order."""
    if not texts:
        return []
    provider = getattr(settings, "EMBEDDING_PROVIDER", "none")
    if provider == "cloudflare":
        return _embed_cloudflare(texts)
    raise EmbeddingError(f"Unsupported EMBEDDING_PROVIDER: {provider!r}")


def embed_text(text: str) -> list[float]:
    """Embed a single text (used for the retrieval query)."""
    vectors = embed_texts([text])
    if not vectors:
        raise EmbeddingError("The embedding provider returned no vector.")
    return vectors[0]


def _embed_cloudflare(texts: list[str]) -> list[list[float]]:
    """Call Cloudflare Workers AI and return the embedding vectors."""
    account = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
    token = getattr(settings, "CLOUDFLARE_API_TOKEN", "")
    if not account or not token:
        raise EmbeddingError(
            "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must both be set."
        )

    url = CLOUDFLARE_RUN_URL.format(account=account, model=settings.EMBEDDING_MODEL)
    batch_size = getattr(settings, "EMBEDDING_BATCH_SIZE", 32)
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=settings.EMBEDDING_TIMEOUT_SECONDS) as client:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"text": batch},
                )
                response.raise_for_status()
                body = response.json()
                if not body.get("success"):
                    raise EmbeddingError(f"Cloudflare error: {body.get('errors')}")
                vectors.extend(body["result"]["data"])
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Cloudflare embedding request failed: {exc}") from exc
    return vectors
