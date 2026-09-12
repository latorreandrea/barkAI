"""Build/refresh the RAG index: chunk the knowledge documents and embed them.

    python manage.py build_index              # only new/changed chunks
    python manage.py build_index --force      # re-embed everything
    python manage.py build_index --source owner/repo --no-embed

Chunks live in ``KnowledgeChunk`` (content + ``content_hash`` + embedding).
Re-running is cheap: unchanged chunks are skipped thanks to the hash. The
command can run from anywhere (e.g. your laptop) as long as the database and
the embedding credentials are reachable — handy to index production.
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


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into paragraph-aware chunks of at most ``max_chars`` chars."""
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(block), max_chars):
                chunks.append(block[start : start + max_chars])
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks


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
            pieces = split_into_chunks(strip_html_comments(document.content), max_chars)
            existing = {chunk.ordinal: chunk for chunk in document.chunks.all()}
            pending: list[KnowledgeChunk] = []

            for ordinal, piece in enumerate(pieces):
                digest = content_hash(piece)
                chunk = existing.get(ordinal)
                if chunk is None:
                    chunk = KnowledgeChunk(document=document, ordinal=ordinal)
                    tally["created"] += 1
                elif chunk.content_hash != digest or options["force"]:
                    tally["updated"] += 1
                else:
                    tally["unchanged"] += 1
                    continue
                chunk.content = piece
                chunk.content_hash = digest
                chunk.token_count = max(1, len(piece) // 4)  # rough estimate
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
