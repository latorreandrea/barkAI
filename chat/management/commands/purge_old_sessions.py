"""Delete conversations older than the retention window (GDPR minimisation).

    python manage.py purge_old_sessions                 # uses SESSION_RETENTION_DAYS
    python manage.py purge_old_sessions --days 30
    python manage.py purge_old_sessions --days 30 --dry-run

Deleting a ``ChatSession`` cascades to its ``ChatMessage`` rows, so a recruiter's
conversation — and everything derived from it — is erased in one shot. Schedule
this (cron / Cloud Scheduler) so data is not kept longer than declared in the
privacy notice.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from chat.models import ChatSession


class Command(BaseCommand):
    help = "Delete conversations older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention window in days (defaults to SESSION_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be deleted.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is None:
            days = getattr(settings, "SESSION_RETENTION_DAYS", 90)

        cutoff = timezone.now() - timedelta(days=days)
        old_sessions = ChatSession.objects.filter(last_active__lt=cutoff)
        count = old_sessions.count()

        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: {count} conversation(s) older than {days} day(s) would be deleted."
            )
            return

        old_sessions.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {count} conversation(s) older than {days} day(s)."
            )
        )
