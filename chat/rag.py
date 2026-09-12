"""Retrieval helpers for the RAG layer.

The knowledge base is stored as ``KnowledgeChunk`` rows with a pgvector
``embedding`` column. On PostgreSQL the nearest neighbours are found with the
native ``<=>`` operator; on other backends (SQLite while developing, the test
suite) a Python cosine similarity is used so everything stays portable.
"""
from __future__ import annotations

import logging
import math

from django.conf import settings
from django.db import connection

from chat.embeddings import EmbeddingError, embed_text
from chat.models import KnowledgeChunk

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[dict]:
    """Return the most relevant knowledge chunks for a query.

    Each item is ``{"content", "source", "score"}``; ``score`` is the cosine
    similarity (1.0 = identical direction).
    """
    query = (query or "").strip()
    if not query:
        return []
    top_k = top_k or getattr(settings, "RAG_TOP_K", 5)
    min_score = getattr(settings, "RAG_MIN_SCORE", 0.25)

    try:
        query_vector = embed_text(query)
    except EmbeddingError as exc:
        logger.warning("Retrieval skipped (embedding failed): %s", exc)
        return []

    if connection.vendor == "postgresql":
        return _retrieve_postgres(query_vector, top_k, min_score)
    return _retrieve_python(query_vector, top_k, min_score)


def build_retrieved_context(query: str) -> str:
    """Format the retrieved chunks as a prompt section ('' when nothing matches)."""
    chunks = retrieve(query)
    if not chunks:
        return ""
    sections = [
        f"### {chunk['source']} (relevance {chunk['score']:.2f})\n{chunk['content']}"
        for chunk in chunks
    ]
    return "\n\n".join(sections)


def _retrieve_postgres(query_vector: list[float], top_k: int, min_score: float) -> list[dict]:
    from pgvector.django import CosineDistance

    rows = (
        KnowledgeChunk.objects.filter(embedding__isnull=False)
        .select_related("document")
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[:top_k]
    )
    results = []
    for chunk in rows:
        score = 1.0 - float(chunk.distance)
        if score >= min_score:
            results.append(
                {"content": chunk.content, "source": chunk.document.source, "score": score}
            )
    return results


def _retrieve_python(query_vector: list[float], top_k: int, min_score: float) -> list[dict]:
    scored = []
    for chunk in KnowledgeChunk.objects.filter(embedding__isnull=False).select_related(
        "document"
    ):
        vector = chunk.embedding
        if not vector:
            continue
        scored.append((_cosine(query_vector, vector), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"content": chunk.content, "source": chunk.document.source, "score": score}
        for score, chunk in scored[:top_k]
        if score >= min_score
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (0.0 when either is empty)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)
