"""Re-send interview notifications that are still pending.

A request is pending when ``notified_at`` is NULL and an email was captured.
That happens when ``INTERVIEW_NOTIFY_EMAIL`` was blank, when the SMTP send
failed, or when the notification was added after the request was first stored.

    python manage.py retry_interview_notifications
    python manage.py retry_interview_notifications --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from chat.models import InterviewRequest
from chat.notifications import notify_interview_requested


class Command(BaseCommand):
    help = "Re-send the notification for every pending interview request."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list what would be sent.",
        )

    def handle(self, *args, **options):
        pending = (
            InterviewRequest.objects.filter(notified_at__isnull=True)
            .exclude(hr_email="")
            .select_related("session")
        )
        total = pending.count()
        if not total:
            self.stdout.write("Nothing pending: every request has been notified.")
            return

        sent = 0
        for interview_request in pending:
            if options["dry_run"]:
                self.stdout.write(
                    f"[dry-run] would notify {interview_request.hr_email} "
                    f"({interview_request.session_id})"
                )
                continue
            if notify_interview_requested(interview_request):
                sent += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Notified {interview_request.hr_email} "
                        f"({interview_request.session_id})"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Still pending: {interview_request.session_id} "
                        f"({interview_request.notification_error or 'notifications disabled'})"
                    )
                )

        if not options["dry_run"]:
            self.stdout.write(f"Done: {sent}/{total} notification(s) sent.")
