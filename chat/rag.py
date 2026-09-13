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
from chat.models import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
    max_per_source: int | None = None,
) -> list[dict]:
    """Return the most relevant knowledge chunks for a query.

    Each item is ``{"content", "source", "score"}``; ``score`` is the cosine
    similarity (1.0 = identical direction). At most ``max_per_source`` chunks of
    a single document are kept, so one long README cannot fill the prompt.
    """
    query = (query or "").strip()
    if not query:
        return []
    top_k = top_k or getattr(settings, "RAG_TOP_K", 5)
    min_score = getattr(settings, "RAG_MIN_SCORE", 0.35)
    max_per_source = max_per_source or getattr(settings, "RAG_MAX_PER_SOURCE", 2)

    try:
        query_vector = embed_text(query)
    except EmbeddingError as exc:
        logger.warning("Retrieval skipped (embedding failed): %s", exc)
        return []

    if connection.vendor == "postgresql":
        candidates = _retrieve_postgres(query_vector, top_k, min_score)
    else:
        candidates = _retrieve_python(query_vector, top_k, min_score)
    return _limit_per_source(candidates, top_k, max_per_source)


def _limit_per_source(
    candidates: list[dict], top_k: int, max_per_source: int
) -> list[dict]:
    """Keep the best candidates while capping how many share a source."""
    seen: dict[str, int] = {}
    kept: list[dict] = []
    for item in candidates:
        source = item["source"]
        if seen.get(source, 0) >= max_per_source:
            continue
        seen[source] = seen.get(source, 0) + 1
        kept.append(item)
        if len(kept) >= top_k:
            break
    return kept


def retrievable_chunks():
    """Chunks that may take part in the similarity search.

    The curated career profile is deliberately excluded: it is short, it applies
    to *every* question and it matches even the vaguest query, so it would crowd
    out the project chunks (2 of the top-3 slots in practice). It is injected
    verbatim instead — see :func:`profile_context`.
    """
    return KnowledgeChunk.objects.filter(
        embedding__isnull=False,
        document__kind=KnowledgeDocument.Kind.GITHUB_README,
    )


def profile_context() -> str:
    """The curated career profile, always sent to the model as ground truth."""
    document = (
        KnowledgeDocument.objects.filter(kind=KnowledgeDocument.Kind.PROFILE)
        .order_by("source")
        .first()
    )
    if document is None:
        logger.warning("No career profile synced: run `python manage.py sync_knowledge`.")
        return ""
    header = document.title or "Career profile"
    return f"### {header}\n{document.content}"


def build_retrieved_context(query: str) -> str:
    """Prompt section: the career profile plus the most relevant project chunks."""
    sections = []
    profile = profile_context()
    if profile:
        sections.append(profile)
    sections.extend(
        f"### {chunk['source']} (relevance {chunk['score']:.2f})\n{chunk['content']}"
        for chunk in retrieve(query)
    )
    return "\n\n".join(sections)


def _retrieve_postgres(query_vector: list[float], top_k: int, min_score: float) -> list[dict]:
    from pgvector.django import CosineDistance

    rows = (
        retrievable_chunks()
        .select_related("document")
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[: top_k * 4]
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
    for chunk in retrievable_chunks().select_related("document"):
        vector = chunk.embedding
        if not vector:
            continue
        scored.append((_cosine(query_vector, vector), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"content": chunk.content, "source": chunk.document.source, "score": score}
        for score, chunk in scored[: top_k * 4]
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
