"""Report how complete and how fresh the knowledge base is.

    python manage.py knowledge_status
    python manage.py knowledge_status --days 7 --fail-on-stale

Designed to run as a scheduled job: the exit code turns red when a document has
not been re-synced within ``KNOWLEDGE_STALE_DAYS`` (or when chunks are still
unembedded), which is exactly how a README change silently fails to reach
BarklAI.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from chat.models import KnowledgeChunk, KnowledgeDocument


class Command(BaseCommand):
    help = "Report knowledge-base coverage/freshness and alert on stale documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override KNOWLEDGE_STALE_DAYS for this run.",
        )
        parser.add_argument(
            "--fail-on-stale",
            action="store_true",
            help="Exit non-zero when a document (or its embeddings) is stale.",
        )

    def handle(self, *args, **options):
        days = options["days"] or getattr(settings, "KNOWLEDGE_STALE_DAYS", 30)
        documents = KnowledgeDocument.objects.all()
        total_documents = documents.count()
        chunks = KnowledgeChunk.objects.all()
        total_chunks = chunks.count()
        embedded = chunks.filter(embedding__isnull=False).count()

        self.stdout.write(f"Documents: {total_documents}")
        for kind, label in KnowledgeDocument.Kind.choices:
            self.stdout.write(f"  {label}: {documents.filter(kind=kind).count()}")
        self.stdout.write(
            f"Chunks:    {total_chunks} ({embedded} embedded, "
            f"{self._percent(embedded, total_chunks)})"
        )

        if not total_documents:
            raise CommandError(
                "The knowledge base is empty: run `sync_knowledge` then `build_index`."
            )

        cutoff = timezone.now() - timedelta(days=days)
        stale = documents.filter(fetched_at__lt=cutoff).order_by("fetched_at")
        newest = documents.order_by("-fetched_at").values_list("fetched_at", flat=True).first()
        oldest = documents.order_by("fetched_at").values_list("fetched_at", flat=True).first()
        self.stdout.write(
            f"Fetched:   newest {newest:%Y-%m-%d}, oldest {oldest:%Y-%m-%d} "
            f"(stale after {days} day(s))"
        )

        problems: list[str] = []
        if embedded < total_chunks:
            problems.append(
                f"{total_chunks - embedded} chunk(s) are not embedded: run `build_index`."
            )
        for document in stale:
            self.stdout.write(
                self.style.WARNING(
                    f"Stale:     {document.source} (fetched {document.fetched_at:%Y-%m-%d})"
                )
            )
        if stale:
            problems.append(
                f"{stale.count()} document(s) were not synced within {days} day(s): "
                "run `sync_knowledge && build_index`."
            )

        if not problems:
            self.stdout.write(self.style.SUCCESS("Fresh: nothing to do."))
            return
        for problem in problems:
            self.stdout.write(self.style.WARNING(problem))
        if options["fail_on_stale"]:
            raise CommandError(" ".join(problems))

    @staticmethod
    def _percent(part: int, whole: int) -> str:
        return f"{100 * part / whole:.0f}%" if whole else "n/a"
