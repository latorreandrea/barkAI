"""Golden-set evaluation for the BarklAI agent.

The unit tests in ``chat/tests.py`` prove the *plumbing* (JSON parsing, friendly
fallbacks, the language guard, the hand-off) with the model mocked. This package
answers a different question: **is the agent still telling the truth?**

It runs a curated, versioned set of recruiter questions through the live agent
and checks the answers against the knowledge base::

    python manage.py eval_agent --check-only   # validate the file, no network
    python manage.py eval_agent                # score a live run

Matching is case-insensitive. The expectation fields are:

* ``must_contain``     — every string must appear in the reply;
* ``must_contain_any`` — at least one of the alternatives must appear;
* ``must_not_contain`` — none may appear. Use it only for claims that must never
  be made (personal identifiers, invented technologies), **never** for a word the
  answer legitimately mentions while denying it;
* ``cites_any``        — at least one of these labels must be cited by the reply
  (see ``sources`` in :func:`evaluate_case`);
* ``cites_something``  — ``true`` requires at least one citation, ``false``
  requires an empty ``sources`` array;
* ``language``         — the reply must be detected in this language;
* ``interview_requested`` — the structured flag must match.

One check is not opt-in: **every** reply must respect the prose contract (no
bullet points, no ``sources:`` line, no bracketed list — see
:func:`format_reasons`), because a citation list leaking into the prose is the
regression this suite is meant to catch.

The set is data, not code: ``golden_set.json`` sits next to this module so it can
be reviewed, diffed and extended like documentation. This module deliberately has
no Django imports (only the stdlib) so the evaluator is trivially unit testable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Where the curated cases live (next to this package).
GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"

# Languages the site supports; the EN/DA parity is the point of the suite.
SUPPORTED_LANGUAGES = ("en", "da")

# Fields that hold the expectations, checked by validate_golden_set().
_EXPECTATION_FIELDS = (
    "must_contain",
    "must_contain_any",
    "must_not_contain",
    "cites_any",
)

# The prose contract (see chat/prompts.py): the answer is written in sentences,
# so a bullet list, a "Sources: …" line or a bracketed list of passage numbers
# means the model slipped back into the older, list-shaped contract.
_CITATION_LINE_RE = re.compile(
    r"^[ \t]*(?:sources?|kilder?|kilde|references?|referencer|fonti|quellen)"
    r"[ \t]*[:\-–—]",
    re.IGNORECASE | re.MULTILINE,
)
_QUOTED_LIST_LINE_RE = re.compile(
    r"^[ \t]*[\[\(][^\n]*['\"][^\n]*[\]\)][ \t]*\.?[ \t]*$", re.MULTILINE
)
_NUMBER_LIST_LINE_RE = re.compile(
    r"^[ \t]*[\[\(][ \t]*\d[ \t\d,]*[\]\)][ \t]*\.?[ \t]*$", re.MULTILINE
)
_BULLET_LINE_RE = re.compile(r"^[ \t]*[-*•·][ \t]+", re.MULTILINE)


def format_reasons(reply: str) -> list[str]:
    """Reasons the reply broke the prose contract (checked on every case)."""
    reasons: list[str] = []
    if _CITATION_LINE_RE.search(reply or ""):
        reasons.append("prose: the reply contains a citation list")
    if _QUOTED_LIST_LINE_RE.search(reply or ""):
        reasons.append("prose: the reply contains a bracketed list of sources")
    if _NUMBER_LIST_LINE_RE.search(reply or ""):
        reasons.append("prose: the reply contains a bracketed list of numbers")
    if _BULLET_LINE_RE.search(reply or ""):
        reasons.append("prose: the reply contains bullet points")
    return reasons


def citation_labels(sources) -> list[str]:
    """Labels of the citations a reply carries (tolerating the legacy shape)."""
    labels: list[str] = []
    for item in sources or []:
        label = item.get("label", "") if isinstance(item, dict) else item
        if label:
            labels.append(str(label))
    return labels


class GoldenSetError(ValueError):
    """Raised when the golden-set file is missing or not valid JSON."""


def load_golden_set(path: Path | None = None) -> dict:
    """Load and shape-check the golden set, returning the parsed document."""
    target = path or GOLDEN_SET_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoldenSetError(f"Golden set not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise GoldenSetError(f"Golden set is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise GoldenSetError('The golden set must be an object with a "cases" list.')
    return data


def validate_golden_set(data: dict) -> list[str]:
    """Return the problems found in ``data`` (an empty list means well formed).

    Kept separate from :func:`evaluate_case` so the file can be checked in CI
    without a network call or an API key.
    """
    problems: list[str] = []
    cases = data.get("cases", [])
    if not cases:
        problems.append("the golden set has no cases")

    seen: set[str] = set()
    for index, case in enumerate(cases):
        where = f"case #{index}"
        if not isinstance(case, dict):
            problems.append(f"{where}: must be an object")
            continue

        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            problems.append(f"{where}: missing a string 'id'")
        elif case_id in seen:
            problems.append(f"{where}: duplicate id {case_id!r}")
        else:
            seen.add(case_id)

        if case.get("language") not in SUPPORTED_LANGUAGES:
            problems.append(
                f"{where}: 'language' must be one of {list(SUPPORTED_LANGUAGES)}"
            )
        if not str(case.get("question") or "").strip():
            problems.append(f"{where}: empty 'question'")

        for field in _EXPECTATION_FIELDS:
            value = case.get(field, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                problems.append(f"{where}: {field!r} must be a list of strings")

        if "cites_something" in case and not isinstance(
            case["cites_something"], bool
        ):
            problems.append(f"{where}: 'cites_something' must be a boolean")

        has_expectation = (
            any(case.get(field) for field in _EXPECTATION_FIELDS)
            or "interview_requested" in case
            or "cites_something" in case
        )
        if not has_expectation:
            problems.append(f"{where}: needs at least one expectation")

    for language, label in (("en", "English"), ("da", "Danish")):
        if not any(
            case.get("language") == language
            for case in cases
            if isinstance(case, dict)
        ):
            problems.append(f"no {label} case: EN/DA parity is the point of this suite")

    return problems


def evaluate_case(
    case: dict,
    *,
    reply: str,
    interview_requested: bool,
    detected_language: str | None,
    sources: list | None = None,
) -> list[str]:
    """Failure reasons for one case (an empty list means it passed).

    Takes plain values instead of a ``BarkleyResponse`` so it can be tested
    without Django and without a model call. ``sources`` are the citations the
    reply carries (the API shape: ``{"label", "title", "url", "lines"}`` dicts).
    """
    text = (reply or "").lower()
    reasons: list[str] = list(format_reasons(reply or ""))

    expected_language = case.get("language")
    if expected_language and detected_language != expected_language:
        reasons.append(
            f"language: expected {expected_language}, "
            f"detected {detected_language or 'unknown'}"
        )

    for needle in case.get("must_contain", []):
        if needle.lower() not in text:
            reasons.append(f"missing {needle!r}")

    alternatives = case.get("must_contain_any", [])
    if alternatives and not any(alt.lower() in text for alt in alternatives):
        reasons.append("none of " + ", ".join(repr(alt) for alt in alternatives))

    for banned in case.get("must_not_contain", []):
        if banned.lower() in text:
            reasons.append(f"forbidden {banned!r}")

    if "interview_requested" in case and bool(case["interview_requested"]) != bool(
        interview_requested
    ):
        reasons.append(
            f"interview_requested: expected {bool(case['interview_requested'])}"
        )

    labels = {label.lower() for label in citation_labels(sources)}
    expected_any = case.get("cites_any", [])
    if expected_any and not any(item.lower() in labels for item in expected_any):
        reasons.append(
            "cites: expected one of "
            + ", ".join(repr(item) for item in expected_any)
            + " (got "
            + (", ".join(repr(item) for item in sorted(labels)) or "nothing")
            + ")"
        )
    if "cites_something" in case:
        if bool(case["cites_something"]) != bool(labels):
            expected = "a citation" if case["cites_something"] else "no citation"
            reasons.append(f"cites: expected {expected}, got {len(labels)}")

    return reasons

