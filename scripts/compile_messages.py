#!/usr/bin/env python
"""Compile every ``locale/**/LC_MESSAGES/*.po`` into a sibling ``.mo`` file.

Django reads ``.mo`` catalogs at runtime, but its own ``compilemessages``
command shells out to the gettext ``msgfmt`` binary, which is not available in
every environment. This script does the same job in pure Python (stdlib only),
so translations can be compiled anywhere:

    python scripts/compile_messages.py

On a machine with gettext installed, ``django-admin compilemessages`` works too
(and ``django-admin makemessages`` can (re)generate the ``.po`` sources).
"""
from __future__ import annotations

import struct
from array import array
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _unquote(fragment: str) -> str:
    """Decode one .po string fragment (the bit between the quotes)."""
    fragment = fragment.strip()
    if fragment.startswith('"') and fragment.endswith('"'):
        fragment = fragment[1:-1]
    return (
        fragment.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def parse_po(path: Path) -> list[tuple[str, str]]:
    """Minimal .po reader returning ``[(msgid, msgstr), ...]``.

    ``msgctxt``/``msgid_plural``/``msgstr[n]`` entries are intentionally
    ignored: BarklAI's copy has no contextual or plural forms.
    """
    entries: list[tuple[str, str]] = []
    msgid: list[str] = []
    msgstr: list[str] = []
    section: str | None = None

    def flush() -> None:
        if section is not None:
            entries.append(("".join(msgid), "".join(msgstr)))

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr, section = [_unquote(line[6:])], [], "id"
        elif line.startswith("msgstr "):
            msgstr, section = [_unquote(line[7:])], "str"
        elif line.startswith('"'):
            (msgid if section == "id" else msgstr).append(_unquote(line))
    flush()
    return entries


def build_mo(entries: list[tuple[str, str]]) -> bytes:
    """Serialise ``(msgid, msgstr)`` pairs into the GNU .mo binary format."""
    catalogue = {
        msgid.encode("utf-8"): msgstr.encode("utf-8") for msgid, msgstr in entries
    }
    keys = sorted(catalogue)
    offsets: list[tuple[int, int, int, int]] = []
    ids = strs = b""
    for key in keys:
        value = catalogue[key]
        offsets.append((len(ids), len(key), len(strs), len(value)))
        ids += key + b"\x00"
        strs += value + b"\x00"

    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets: list[int] = []
    voffsets: list[int] = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]

    output = struct.pack(
        "Iiiiiii",
        0x950412DE,  # magic number
        0,  # format revision
        len(keys),  # number of entries
        7 * 4,  # offset of the key index
        7 * 4 + len(keys) * 8,  # offset of the value index
        0,  # hash table size
        0,  # hash table offset
    )
    output += array("i", koffsets).tobytes()
    output += array("i", voffsets).tobytes()
    output += ids
    output += strs
    return output


def main() -> None:
    compiled = 0
    for po_path in sorted(BASE_DIR.glob("locale/**/LC_MESSAGES/*.po")):
        entries = parse_po(po_path)
        mo_path = po_path.with_suffix(".mo")
        mo_path.write_bytes(build_mo(entries))
        compiled += 1
        rel = po_path.relative_to(BASE_DIR)
        print(f"compiled {rel} -> {mo_path.name} ({len(entries)} entries)")
    print(f"done: {compiled} catalog(s)")


if __name__ == "__main__":
    main()
