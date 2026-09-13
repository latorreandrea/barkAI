"""Send a test email with the configured backend, to verify the setup.

    python manage.py send_test_email
    python manage.py send_test_email --to someone@example.com

Handy before trusting the interview notifications: it proves the SMTP
credentials work without waiting for a recruiter to ask for an interview.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email using the configured EMAIL_BACKEND / SMTP settings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            default="",
            help="Recipient (defaults to INTERVIEW_NOTIFY_EMAIL when set).",
        )

    def handle(self, *args, **options):
        recipient = options["to"] or settings.INTERVIEW_NOTIFY_EMAIL
        if not recipient:
            raise CommandError(
                "No recipient: pass --to or set INTERVIEW_NOTIFY_EMAIL."
            )

        self.stdout.write(f"Backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(
            f"Host:    {settings.EMAIL_HOST or '(not set)'} "
            f"port {settings.EMAIL_PORT} TLS={settings.EMAIL_USE_TLS}"
        )
        self.stdout.write(f"From:    {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"To:      {recipient}")

        try:
            sent = send_mail(
                subject="🐾 BarkAI test email",
                message=(
                    "BarklAI here! If you can read this, the interview "
                    "notifications are wired up correctly. 🐾"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 - reporting it IS the job
            raise CommandError(f"Sending failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} message(s)."))
