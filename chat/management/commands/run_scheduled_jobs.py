"""Run the daily maintenance chain inside a single Cloud Run job.

Cloud Scheduler triggers one Cloud Run Job (see the README) and this command is
what that job runs: refresh the knowledge base, re-index it, recover pending
interview notifications, then report freshness and fail if the corpus is stale.

Why a command instead of a shell ``&&`` chain:

* a failing step used to abort the rest of the chain silently. Here every step
  runs, each outcome is reported, and the command exits non-zero if any of them
  failed -- which is what turns the Cloud Scheduler execution red;
* ``sync_knowledge`` raises ``SystemExit(1)`` on a GitHub error, and
  ``SystemExit`` derives from ``BaseException``: a plain ``except Exception``
  would not catch it and the process would die before printing the summary. It is
  therefore caught explicitly below.

    python manage.py run_scheduled_jobs
    python manage.py run_scheduled_jobs --dry-run
    python manage.py run_scheduled_jobs --only knowledge_status
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


@dataclass(frozen=True)
class Step:
    """One management command inside the chain."""

    name: str
    kwargs: dict = field(default_factory=dict)

    def describe(self) -> str:
        """Human-readable form, used by --dry-run and the step banner."""
        parts = [self.name]
        for key, value in self.kwargs.items():
            flag = "--" + key.replace("_", "-")
            parts.append(flag if value is True else f"{flag}={value}")
        return " ".join(parts)


# Order matters: the freshness check runs last so it reports on the corpus the
# previous steps just refreshed.
#
# ``prune=True`` is safe to run unattended: sync_knowledge deletes stale
# documents only *after* a fully successful GitHub fetch, so a network failure
# aborts the run before anything is removed (see the command's own source).
STEPS: tuple[Step, ...] = (
    Step("sync_knowledge", {"prune": True}),
    Step("build_index"),
    Step("retry_interview_notifications"),
    Step("knowledge_status", {"fail_on_stale": True}),
)

# Substrings that mean "the step ran, but something is off". Without them an
# unattended job can report a healthy run while the corpus silently stops
# updating: a job whose environment is missing GITHUB_USERNAME, for instance,
# only syncs the profile, and this warning is the only trace of it.
_WARNING_MARKERS = (
    "skipping github",
    "embedding_provider is 'none'",
)


class Command(BaseCommand):
    help = "Run the daily maintenance chain (knowledge, notifications, freshness)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the steps without running them.",
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            help="Run only the named step(s); repeatable.",
        )
        parser.add_argument(
            "--no-prune",
            action="store_true",
            help=(
                "Do not delete knowledge documents that are no longer sourced. "
                "Pruning is on by default because the daily job is what keeps the "
                "corpus honest."
            ),
        )

    def handle(self, *args, **options):
        steps = self._selected_steps(options)

        if options["dry_run"]:
            for step in steps:
                self.stdout.write(f"would run: {step.describe()}")
            return

        failures: list[str] = []
        warnings: list[str] = []

        for step in steps:
            self.stdout.write(self.style.MIGRATE_HEADING(f"=== {step.describe()}"))

            # The sub-command output must land in Cloud Logging *and* be scanned
            # for warning markers, so it is captured explicitly.
            captured = StringIO()
            error = ""
            try:
                call_command(
                    step.name, stdout=captured, stderr=captured, **step.kwargs
                )
            except SystemExit as exc:  # sync_knowledge signals GitHub errors this way
                error = f"exited with status {exc.code}"
            except Exception as exc:  # noqa: BLE001 - one bad step must not stop the chain
                error = f"{type(exc).__name__}: {exc}"

            output = captured.getvalue()
            if output:
                self.stdout.write(output.rstrip())

            if error:
                failures.append(step.name)
                self.stderr.write(self.style.ERROR(f"[FAIL] {step.name}: {error}"))
                continue

            markers = self._warning_markers_in(output)
            if markers:
                warnings.append(step.name)
                for marker in markers:
                    self.stderr.write(
                        self.style.WARNING(f"[WARN] {step.name}: {marker}")
                    )
                continue

            self.stdout.write(self.style.SUCCESS(f"[OK] {step.name}"))

        self._report(steps, failures, warnings)

    # -- helpers ----------------------------------------------------------
    def _selected_steps(self, options: dict) -> tuple[Step, ...]:
        """The chain to run, honouring --only and --no-prune."""
        requested = options["only"]
        steps = STEPS
        if requested:
            known = {step.name for step in STEPS}
            unknown = [name for name in requested if name not in known]
            if unknown:
                raise CommandError(
                    f"Unknown step(s): {', '.join(unknown)}. "
                    f"Known: {', '.join(sorted(known))}."
                )
            steps = tuple(step for step in steps if step.name in requested)

        if options["no_prune"]:
            steps = tuple(
                Step(step.name, {k: v for k, v in step.kwargs.items() if k != "prune"})
                if "prune" in step.kwargs
                else step
                for step in steps
            )
        return steps

    @staticmethod
    def _warning_markers_in(output: str) -> list[str]:
        lowered = (output or "").lower()
        return [marker for marker in _WARNING_MARKERS if marker in lowered]

    def _report(
        self, steps: tuple[Step, ...], failures: list[str], warnings: list[str]
    ) -> None:
        """Summary plus the exit code Cloud Scheduler reacts to."""
        self.stdout.write("")
        self.stdout.write(f"Steps run: {len(steps)}")
        if warnings:
            self.stdout.write(self.style.WARNING(f"Warnings: {', '.join(warnings)}"))
        if failures:
            self.stderr.write(self.style.ERROR(f"Failures: {', '.join(failures)}"))
            raise CommandError("Maintenance chain failed: " + ", ".join(failures))
        self.stdout.write(self.style.SUCCESS("Maintenance chain completed."))
