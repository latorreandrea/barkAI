"""Retrieval helpers for the RAG layer.

The knowledge base is stored as ``KnowledgeChunk`` rows with a pgvector
``embedding`` column. On PostgreSQL the nearest neighbours are found with the
native ``<=>`` operator; on other backends (SQLite while developing, the test
suite) a Python cosine similarity is used so everything stays portable.
"""
from __future__ import annotations

import logging
import math
import re

from django.conf import settings
from django.db import connection

from chat.embeddings import EmbeddingError, embed_text
from chat.models import KnowledgeChunk, KnowledgeDocument
from chat.prompts import passage_description

logger = logging.getLogger(__name__)

# ``## Deployment`` → the section a chunk belongs to, shown in the citation.
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)

# The career profile is passage 1 of every prompt (see the builders below).
PROFILE_PASSAGE_ID = 1


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


def chunk_title(content: str) -> str:
    """The markdown section a chunk starts in (empty when it has no heading)."""
    match = _HEADING_RE.search(content or "")
    return match.group(1).strip() if match else ""


def line_range_label(start_line: int, end_line: int) -> str:
    """``"120-148"``, ``"120"`` or ``""``: how a citation shows its lines."""
    if not start_line or not end_line:
        return ""
    return f"{start_line}-{end_line}" if end_line != start_line else str(start_line)


def _candidate(chunk: KnowledgeChunk, score: float) -> dict:
    """One retrieval hit, carrying everything a citation needs.

    The URL and the line span come from the index rather than from the model, so
    a link can never be invented: the model only ever cites the passage number.
    """
    document = chunk.document
    return {
        "chunk_id": chunk.pk,
        "content": chunk.content,
        "source": document.source,
        "title": chunk_title(chunk.content),
        "url": document.url or "",
        "lines": line_range_label(chunk.start_line, chunk.end_line),
        "score": score,
    }


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


def profile_document() -> KnowledgeDocument | None:
    """The curated career profile document, or ``None`` when it is not synced."""
    return (
        KnowledgeDocument.objects.filter(kind=KnowledgeDocument.Kind.PROFILE)
        .order_by("source")
        .first()
    )


def profile_context() -> str:
    """The curated career profile, always sent to the model as ground truth."""
    document = profile_document()
    if document is None:
        logger.warning("No career profile synced: run `python manage.py sync_knowledge`.")
        return ""
    header = document.title or "Career profile"
    return f"### {header}\n{document.content}"


def build_retrieved_context_with_citations(query: str) -> tuple[str, list[dict]]:
    """Prompt section plus the numbered passages BarklAI may cite.

    The profile is passage ``1`` (it is always injected) and the retrieved chunks
    follow, so the model cites integers while the application keeps the URL and
    the line range of every citation. Both come from a single ``retrieve()`` call
    on purpose: embedding is an HTTP request, so a second one would only add cost
    and latency.
    """
    chunks = retrieve(query)
    sections: list[str] = []
    citations: list[dict] = []

    document = profile_document()
    if document is not None:
        citation = {
            "id": PROFILE_PASSAGE_ID,
            "label": document.source,
            "title": document.title or "Career profile",
            "url": document.url or "",
            "lines": "",
        }
        citations.append(citation)
        sections.append(
            f"[{PROFILE_PASSAGE_ID}] {passage_description(citation)}\n{document.content}"
        )

    for offset, chunk in enumerate(chunks, start=PROFILE_PASSAGE_ID + 1):
        citation = {
            "id": offset,
            "label": chunk["source"],
            "title": chunk["title"],
            "url": chunk["url"],
            "lines": chunk["lines"],
        }
        citations.append(citation)
        sections.append(
            f"[{offset}] {passage_description(citation)} "
            f"(relevance {chunk['score']:.2f})\n{chunk['content']}"
        )

    return "\n\n".join(sections), citations


def build_retrieved_context(query: str) -> str:
    """Prompt section: the career profile plus the most relevant project chunks."""
    return build_retrieved_context_with_citations(query)[0]


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
            results.append(_candidate(chunk, score))
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
        _candidate(chunk, score)
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
