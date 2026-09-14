"""Score the live agent against the curated golden set.

    python manage.py eval_agent --check-only   # validate the file (no network)
    python manage.py eval_agent                # live run, needs GROQ_API_KEY
    python manage.py eval_agent --only da-     # subset by id prefix
    python manage.py eval_agent --verbose      # also print every reply

The command exits non-zero when a case fails, so it can gate a release the same
way the test suite gates a commit. The cases themselves live in
``chat/evals/golden_set.json`` and the matching logic in ``chat/evals``.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat.evals import (
    GoldenSetError,
    evaluate_case,
    load_golden_set,
    validate_golden_set,
)
from chat.services import detect_language, generate_reply

# How much of a failing reply to echo, so the output stays readable.
_REPLY_PREVIEW_CHARS = 400


class Command(BaseCommand):
    help = "Run the curated golden set (EN/DA) through the live agent and score it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Only validate the golden-set file: no model call, no API key.",
        )
        parser.add_argument(
            "--only",
            default="",
            help="Run only the cases whose id starts with this prefix (e.g. 'da-').",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print each reply next to its result.",
        )

    def handle(self, *args, **options):
        try:
            data = load_golden_set()
        except GoldenSetError as exc:
            raise CommandError(str(exc)) from exc

        problems = validate_golden_set(data)
        if problems:
            for problem in problems:
                self.stderr.write(self.style.ERROR(f"  - {problem}"))
            raise CommandError(f"The golden set is malformed ({len(problems)} problem(s)).")

        cases = data["cases"]
        prefix = options["only"]
        if prefix:
            cases = [case for case in cases if case["id"].startswith(prefix)]
        language_counts = {
            language: sum(1 for case in cases if case["language"] == language)
            for language in sorted({case["language"] for case in cases})
        }
        self.stdout.write(
            f"Golden set: {len(cases)} case(s) "
            + ", ".join(f"{count} {lang}" for lang, count in language_counts.items())
        )

        if options["check_only"]:
            self.stdout.write(self.style.SUCCESS("Golden set is well formed."))
            return

        if not cases:
            raise CommandError(f"No case matches --only={prefix!r}.")
        if not getattr(settings, "GROQ_API_KEY", ""):
            raise CommandError("GROQ_API_KEY is empty: the eval needs the live model.")
        if not getattr(settings, "RAG_ENABLED", False):
            self.stdout.write(
                self.style.WARNING(
                    "RAG_ENABLED is off: answers will not be grounded in the "
                    "retrieved chunks, so expect knowledge failures."
                )
            )

        passed = 0
        failed: list[str] = []
        for case in cases:
            result = generate_reply(case["question"], [])
            reasons = evaluate_case(
                case,
                reply=result.reply,
                interview_requested=result.interview_requested,
                detected_language=detect_language(result.reply),
            )
            if reasons:
                failed.append(case["id"])
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] {case['id']} -> " + "; ".join(reasons))
                )
            else:
                passed += 1
                self.stdout.write(self.style.SUCCESS(f"[PASS] {case['id']}"))
            if options["verbose"]:
                preview = result.reply.replace("\n", " ")[:_REPLY_PREVIEW_CHARS]
                self.stdout.write(f"       {preview}")

        total = len(cases)
        score = (passed / total) * 100 if total else 0.0
        self.stdout.write("")
        self.stdout.write(f"Score: {passed}/{total} ({score:.0f}%)")
        if failed:
            raise CommandError("Failed case(s): " + ", ".join(failed))
