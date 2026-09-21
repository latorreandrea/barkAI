"""Build/refresh the RAG index: chunk the knowledge documents and embed them.

    python manage.py build_index              # only new/changed chunks
    python manage.py build_index --force      # re-embed everything
    python manage.py build_index --source owner/repo --no-embed

Chunks live in ``KnowledgeChunk`` (content + ``content_hash`` + embedding + the
line span of the passage inside its document, which is what a citation links to).
Re-running is cheap: unchanged chunks are skipped thanks to the hash, and when only
their position moved the command refreshes the span without re-embedding. The
command can run from anywhere (e.g. your laptop) as long as the database and the
embedding credentials are reachable — handy to index production.
"""
from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from chat.embeddings import EmbeddingError, embed_texts
from chat.models import KnowledgeChunk, KnowledgeDocument

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_html_comments(text: str) -> str:
    """Drop ``<!-- ... -->`` comments — they are authoring notes, not knowledge."""
    return _HTML_COMMENT.sub("", text)


def _line_of(text: str, offset: int) -> int:
    """1-based line number of a character offset inside ``text``."""
    return text.count("\n", 0, max(offset, 0)) + 1


def iter_chunk_spans(text: str, max_chars: int) -> list[tuple[str, int, int]]:
    """Split text into chunks, remembering the line span of each one.

    Returns ``(chunk_text, start_line, end_line)`` tuples with 1-based, inclusive
    line numbers relative to ``text``, so a citation can link the passage itself
    (``…/README.md#L120-L148``). The chunk *text* is accumulated exactly as
    :func:`split_into_chunks` always did, so re-indexing keeps the same hashes and
    unchanged chunks are never re-embedded — only their line span is refreshed.
    """
    # Walk the same ``\n\n`` separated blocks, but keep each one's line span so the
    # lines can be derived from the original text (a paragraph split loses them).
    blocks: list[tuple[str, int, int, int]] = []
    offset = 0
    for part in text.split("\n\n"):
        stripped = part.strip()
        if stripped:
            leading = len(part) - len(part.lstrip())
            trailing = len(part) - len(part.rstrip())
            start_offset = offset + leading
            blocks.append(
                (
                    stripped,
                    _line_of(text, start_offset),
                    _line_of(text, offset + len(part) - trailing - 1),
                    start_offset,
                )
            )
        offset += len(part) + 2  # the "\n\n" separator itself

    pieces: list[tuple[str, int, int]] = []
    current = ""
    current_start = 0
    current_end = 0
    for block, block_start, block_end, block_offset in blocks:
        if len(block) > max_chars:
            # One paragraph larger than a chunk: split it by characters, keeping
            # each slice's own line span.
            if current:
                pieces.append((current, current_start, current_end))
                current = ""
            for start in range(0, len(block), max_chars):
                piece = block[start : start + max_chars]
                first = block_offset + start
                pieces.append(
                    (piece, _line_of(text, first), _line_of(text, first + len(piece) - 1))
                )
            continue
        if not current:
            current, current_start, current_end = block, block_start, block_end
            continue
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= max_chars:
            current = candidate
            current_end = block_end
        else:
            pieces.append((current, current_start, current_end))
            current, current_start, current_end = block, block_start, block_end
    if current:
        pieces.append((current, current_start, current_end))
    return pieces


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into paragraph-aware chunks of at most ``max_chars`` chars."""
    return [piece for piece, _start, _end in iter_chunk_spans(text, max_chars)]


def content_hash(text: str) -> str:
    """SHA-256 of a chunk, so unchanged chunks can be skipped."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = "Chunk the knowledge documents and (re)embed the chunks (RAG index)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-embed every chunk, even the unchanged ones.",
        )
        parser.add_argument(
            "--source",
            default="",
            help="Only index the document with this source (e.g. owner/repo).",
        )
        parser.add_argument(
            "--no-embed",
            action="store_true",
            help="Only (re)chunk the documents; skip the embedding requests.",
        )

    def handle(self, *args, **options):
        if settings.EMBEDDING_PROVIDER == "none" and not options["no_embed"]:
            self.stderr.write(
                self.style.ERROR(
                    "EMBEDDING_PROVIDER is 'none': set it (e.g. 'cloudflare') "
                    "or run with --no-embed."
                )
            )
            raise SystemExit(1)

        documents = KnowledgeDocument.objects.all()
        if options["source"]:
            documents = documents.filter(source=options["source"])

        max_chars = settings.RAG_CHUNK_MAX_CHARS
        tally = {"created": 0, "updated": 0, "unchanged": 0}

        for document in documents:
            pieces = iter_chunk_spans(strip_html_comments(document.content), max_chars)
            existing = {chunk.ordinal: chunk for chunk in document.chunks.all()}
            pending: list[KnowledgeChunk] = []

            for ordinal, (piece, start_line, end_line) in enumerate(pieces):
                digest = content_hash(piece)
                chunk = existing.get(ordinal)
                span = (start_line, end_line)
                if chunk is None:
                    chunk = KnowledgeChunk(document=document, ordinal=ordinal)
                    tally["created"] += 1
                elif chunk.content_hash != digest or options["force"]:
                    tally["updated"] += 1
                elif (chunk.start_line, chunk.end_line) != span:
                    # Only the position moved (say, lines added above): the text is
                    # byte-identical, so the stored embedding is still valid and a
                    # cheap UPDATE keeps the citation ranges honest.
                    chunk.start_line, chunk.end_line = span
                    chunk.save(update_fields=["start_line", "end_line", "indexed_at"])
                    tally["unchanged"] += 1
                    continue
                else:
                    tally["unchanged"] += 1
                    continue
                chunk.content = piece
                chunk.content_hash = digest
                chunk.token_count = max(1, len(piece) // 4)  # rough estimate
                chunk.start_line, chunk.end_line = span
                chunk.save()
                pending.append(chunk)

            # Drop trailing chunks when the document shrank.
            for ordinal, chunk in existing.items():
                if ordinal >= len(pieces):
                    chunk.delete()

            if pending and not options["no_embed"]:
                self._embed(pending)

        self.stdout.write(
            self.style.SUCCESS(
                "Index complete: "
                f"{tally['created']} created, {tally['updated']} updated, "
                f"{tally['unchanged']} unchanged."
            )
        )

    def _embed(self, chunks: list[KnowledgeChunk]) -> None:
        """Embed the pending chunks in one batch and store the vectors."""
        try:
            vectors = embed_texts([chunk.content for chunk in chunks])
        except EmbeddingError as exc:
            self.stderr.write(self.style.ERROR(f"Embedding failed: {exc}"))
            raise SystemExit(1) from exc
        if len(vectors) != len(chunks):
            self.stderr.write(self.style.ERROR("Embedding count mismatch."))
            raise SystemExit(1)
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = vector
            chunk.save(update_fields=["embedding", "indexed_at"])
