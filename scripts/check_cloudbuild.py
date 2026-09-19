#!/usr/bin/env python
"""Validate a Cloud Build config before it reaches Cloud Build.

Cloud Build applies substitutions to every *value* of the build config before it
runs anything, so a literal ``$`` must be written ``$$``. A stray ``$NAME`` that is
neither a built-in nor one of your own ``_PREFIXED`` substitutions makes the whole
build fail, and the only place you see it is a red build::

    invalid argument: invalid value for 'build.substitutions':
    key in the template "NAME" is not a valid built-in substitution

This script reproduces that check locally and in CI, so the mistake costs a second
instead of a build cycle.

    python scripts/check_cloudbuild.py [path]

Details worth knowing:

* **Comments are ignored**, exactly like Cloud Build does: the YAML parser drops
  them before the substitution pass, so a ``$WORD`` inside a comment is harmless.
  (Evidence: a config whose only problems were ``$IMAGE`` in a comment and ``$JOB``
  in a script failed on ``JOB``, not on the earlier ``IMAGE``.)
* ``$$NAME`` is the escape and is accepted whatever the name is.
* Only the standard library is used, so CI needs no extra dependency.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "cloudbuild.yaml"

# Substitutions Cloud Build provides itself.
BUILT_IN_SUBSTITUTIONS = frozenset(
    {
        "PROJECT_ID",
        "PROJECT_NUMBER",
        "BUILD_ID",
        "LOCATION",
        "REGION",
        "TRIGGER_NAME",
        "COMMIT_SHA",
        "SHORT_SHA",
        "REVISION_ID",
        "REPO_NAME",
        "BRANCH_NAME",
        "TAG_NAME",
        "REF_NAME",
        "SERVICE_ACCOUNT",
        "SERVICE_ACCOUNT_EMAIL",
        "BUILD_TRIGGER_LOCATION",
    }
)

# $NAME, ${NAME}, $$NAME
_REFERENCE = re.compile(r"\$\$?(?:\{)?([A-Za-z_][A-Za-z0-9_]*)(?:\})?")
# Keys of the `substitutions:` block, which start with an underscore by contract.
_DECLARED_KEY = re.compile(r"^\s{2}(_\w+)\s*:", re.MULTILINE)


def strip_comments(text: str) -> str:
    """Remove YAML comments, keeping the line count intact.

    A ``#`` starts a comment only at the beginning of a line or after whitespace
    outside a quoted string -- which is all this config needs. The quote count is a
    heuristic, deliberately kept simple rather than pulling in a YAML parser.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            kept.append("")
            continue
        cut = len(line)
        for index, char in enumerate(line):
            if char != "#" or index == 0 or line[index - 1] not in " \t":
                continue
            if line.count('"', 0, index) % 2 == 0 and line.count("'", 0, index) % 2 == 0:
                cut = index
                break
        kept.append(line[:cut])
    return "\n".join(kept)


def declared_substitutions(text: str) -> set[str]:
    """User substitutions declared in the file's ``substitutions:`` block."""
    return set(_DECLARED_KEY.findall(text))


def find_problems(text: str) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for every invalid ``$`` reference."""
    body = strip_comments(text)
    allowed = BUILT_IN_SUBSTITUTIONS | declared_substitutions(text)
    problems: list[tuple[int, str]] = []
    for match in _REFERENCE.finditer(body):
        escaped = body[match.start() : match.start() + 2] == "$$"
        name = match.group(1)
        if escaped or name in allowed:
            continue
        line = body[: match.start()].count("\n") + 1
        problems.append((line, name))
    return problems


def self_test() -> int:
    """Prove the checker both catches bad input and accepts good input.

    A validator that silently stopped matching would give false confidence, so the
    behaviour is asserted on fixtures instead of only being exercised once by hand.
    """
    fixtures = [
        # name, config, expected problems as (line, variable)
        ("escaped/declared/built-in -> clean", GOOD_FIXTURE, []),
        ("bare shell variable -> flagged", BAD_FIXTURE, [(6, "OOPS")]),
        ("$ in a comment -> ignored", COMMENT_FIXTURE, []),
    ]
    failures = 0
    for name, config, expected in fixtures:
        got = find_problems(config)
        if got == expected:
            print(f"  ok   {name}")
        else:
            print(f"  FAIL {name}: expected {expected}, got {got}", file=sys.stderr)
            failures += 1
    print(f"self-test: {len(fixtures) - failures}/{len(fixtures)} passed")
    return 1 if failures else 0


GOOD_FIXTURE = """\
substitutions:
  _REGION: europe-west1
steps:
  - id: x
    args:
      - |
        echo ${_REGION} $$LITERAL $PROJECT_ID
"""

BAD_FIXTURE = """\
steps:
  - id: x
    args:
      - -c
      - |
        echo "$OOPS"
substitutions:
  _OK: fine
"""

# Cloud Build drops comments before substituting, so this must never be flagged.
COMMENT_FIXTURE = """\
steps:
  - id: x
    args:
      - |
        # see $IMAGE for the tag
        echo ok   # and $ALSO_IMAGE here
"""


def main(argv: list[str]) -> int:
    if "--self-test" in argv[1:]:
        return self_test()

    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"{path}: not found", file=sys.stderr)
        return 1

    problems = find_problems(text)
    if not problems:
        print(f"{path.name}: no invalid substitutions")
        return 0

    print(
        f"{path.name}: {len(problems)} invalid $ reference(s). A literal $ must be "
        "written $$ (Cloud Build substitutes every value before running).",
        file=sys.stderr,
    )
    for line, name in problems:
        print(f"  line {line}: ${name}", file=sys.stderr)
    print(
        "  Fix: write $$%s, or declare _%s in the substitutions block, or use a "
        "built-in name." % ("NAME", "NAME"),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
