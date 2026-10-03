"""User-supplied chromosome mappings as a runtime registry (offline).

A custom mapping is a plain UTF-8 TSV with exactly this header::

    assembly<TAB>ucsc<TAB>ensembl<TAB>genbank<TAB>refseq

One row is one sequence; each cell is the name of that sequence in one
naming system, or empty when the user has none. The user supplies no
sequence id: records get the deterministic, opaque ids ``custom:000001``,
``custom:000002``, ... in file row order (never parsed for meaning).

Validation is *structural*: the mapping must be unambiguous (no alias on two
rows, no duplicate rows, no empty rows, clean cells). AnnotateR does not
certify that the names are biologically right and does not restrict them:
no accession-shape, naming-syntax, provenance or source-label rules apply,
so non-model and non-standard identifiers are fine. Matching is exact and
case-sensitive; identifiers are never trimmed, case-folded or inferred, and
a leading/trailing space is rejected rather than silently removed.

The result is an ordinary immutable ``ChromosomeRegistry`` (no assembly
identity), so resolve/render and normalization behave exactly as for the
bundled registries. Nothing is persisted and nothing uses the network.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import BinaryIO, TextIO

from .loader import (
    AUTHORITIES,
    ChromosomeRegistry,
    RegistryError,
    SequenceRecord,
)

# Header of a custom mapping, in the one accepted order. (The runtime
# registry's authority order is the same: ucsc is one of the five names.)
CUSTOM_HEADER = ("assembly", "ucsc", "ensembl", "genbank", "refseq")
CUSTOM_REGISTRY_NAME = "Custom chromosome mapping"
SEQ_ID_PREFIX = "custom:"

# Resource limits (overridable arguments). A loaded registry costs roughly
# 1.4 KB and 13 microseconds per sequence (measured: 622,000 sequences took
# 8 s and ~0.9 GB), so the row limit is the binding one: 500,000 sequences
# (~0.7 GB) covers nearly every assembly, including heavily fragmented ones,
# yet keeps one mistaken upload from exhausting a small deployment. The byte
# limit allows ~100 bytes per row. Both are arguments of
# ``load_custom_registry`` for callers with larger needs and sit below
# Streamlit's default 200 MB per-file upload limit, which is the separate
# transport limit. Oversized input is refused before it is parsed.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ROWS = 500_000
MAX_REPORTED_ISSUES = 20

# Presentation bounds for validation messages (the registry itself never
# truncates anything). One offending value is shown up to MAX_VALUE_PREVIEW
# characters and one issue lists at most MAX_LISTED_PLACES lines/places, so
# a multi-megabyte value or an alias repeated on every row still yields a
# message of a few kilobytes.
MAX_VALUE_PREVIEW = 80
MAX_LISTED_PLACES = 10

# Unicode general category Cc (control): exactly U+0000-U+001F and
# U+007F-U+009F (C0, DEL and C1 controls, e.g. U+0085). Format characters
# (Cf, e.g. zero-width space) are not control characters and are kept, as
# names are matched exactly and never normalized.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f]")

_UTF8_BOM = "﻿"

# Issue codes (stable, machine-readable).
EMPTY_FILE = "EMPTY_FILE"
ENCODING = "ENCODING"
TOO_LARGE = "TOO_LARGE"
TOO_MANY_ROWS = "TOO_MANY_ROWS"
HEADER = "HEADER"
FIELD_COUNT = "FIELD_COUNT"
EMPTY_ROW = "EMPTY_ROW"
NO_ALIAS = "NO_ALIAS"
COMMENT = "COMMENT"
WHITESPACE = "WHITESPACE"
CONTROL_CHARACTER = "CONTROL_CHARACTER"
DUPLICATE_ROW = "DUPLICATE_ROW"
ALIAS_COLLISION = "ALIAS_COLLISION"
NO_DATA = "NO_DATA"


@dataclass(frozen=True)
class CustomRegistryIssue:
    """One structural problem. ``rows`` are 1-based file line numbers (the
    header is line 1); ``columns`` name the cells involved."""

    code: str
    message: str
    rows: tuple[int, ...] = ()
    columns: tuple[str, ...] = ()
    alias: str | None = None


class CustomRegistryError(RegistryError):
    """The custom mapping is structurally invalid; ``issues`` lists why."""

    def __init__(self, issues: list[CustomRegistryIssue], more: int = 0):
        self.issues = tuple(issues)
        self.more = more
        lines = [describe_issue(i) for i in self.issues]
        if more:
            lines.append(f"... and {more} more problem(s)")
        super().__init__("invalid custom chromosome mapping: "
                         + "; ".join(lines))

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(i.code for i in self.issues)


def preview(value: str) -> str:
    """``repr`` of a user value for a message, cut to ``MAX_VALUE_PREVIEW``
    characters (with the full length stated) so input is never echoed in
    bulk."""
    if len(value) <= MAX_VALUE_PREVIEW:
        return repr(value)
    return (f"{value[:MAX_VALUE_PREVIEW]!r}... [truncated, "
            f"{len(value):,} characters]")


def listed(items) -> str:
    """At most ``MAX_LISTED_PLACES`` items, then the total count."""
    items = list(items)
    text = ", ".join(map(str, items[:MAX_LISTED_PLACES]))
    if len(items) > MAX_LISTED_PLACES:
        text += f", ... ({len(items):,} in total)"
    return text


def describe_issue(issue: CustomRegistryIssue) -> str:
    """One bounded, plain-text line: lines, columns, code and message."""
    where = f"line {listed(issue.rows)}" if issue.rows else "file"
    if issue.columns:
        where += f" [{', '.join(dict.fromkeys(issue.columns))}]"
    return f"{where}: {issue.code}: {issue.message}"


def _read(source, max_bytes: int) -> str:
    """Decode ``source`` (bytes, binary or text file-like) to text.

    Reads at most ``max_bytes`` + 1 characters/bytes, so an oversized input
    is refused without being loaded in full.
    """
    if isinstance(source, str):
        raise TypeError(
            "pass the file content as bytes or a file object, not a str "
            "(a str would be ambiguous between content and a path)"
        )
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    elif hasattr(source, "read"):
        data = source.read(max_bytes + 1)
    else:
        raise TypeError("source must be bytes or a binary/text file object")
    if isinstance(data, str):
        # A text file object yields characters, but the limit is in bytes
        # (as for a binary source): measure the UTF-8 size when it could
        # exceed the limit (at most 4 bytes per character).
        if len(data) * 4 > max_bytes:
            try:
                size = len(data.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise CustomRegistryError([CustomRegistryIssue(
                    ENCODING, f"the text is not valid UTF-8 ({exc.reason})"
                )]) from None
        else:
            size = len(data)
    else:
        size = len(data)
    if size > max_bytes:
        raise CustomRegistryError([CustomRegistryIssue(
            TOO_LARGE, f"the mapping file is larger than {max_bytes:,} bytes"
        )])
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CustomRegistryError([CustomRegistryIssue(
            ENCODING, f"the file is not valid UTF-8 ({exc.reason} at byte "
                      f"{exc.start})")]) from None


def _header_issue(fields: list[str]) -> CustomRegistryIssue | None:
    if tuple(fields) == CUSTOM_HEADER:
        return None
    expected = "\t".join(CUSTOM_HEADER)
    seen = set()
    duplicated = sorted({f for f in fields if f in seen or seen.add(f)})
    missing = [c for c in CUSTOM_HEADER if c not in fields]
    extra = [f for f in fields if f not in CUSTOM_HEADER]
    detail = []
    if missing:
        detail.append(f"missing {missing}")
    if extra:
        detail.append(f"unexpected [{listed(map(preview, extra))}]")
    if duplicated:
        detail.append(f"duplicated [{listed(map(preview, duplicated))}]")
    if not detail:
        detail.append("columns are in a different order")
    return CustomRegistryIssue(
        HEADER, f"the first line must be exactly the tab-separated header "
                f"{expected!r} ({'; '.join(detail)})", rows=(1,))


def _control_character(cell: str) -> str | None:
    found = _CONTROL.search(cell)
    return found.group() if found else None


def parse_custom_tsv(text: str, *, max_rows: int = DEFAULT_MAX_ROWS):
    """Validate a custom mapping and return its rows.

    Returns ``[(line_number, (assembly, ucsc, ensembl, genbank, refseq))]``.
    Raises ``CustomRegistryError`` with every structural problem found (the
    first ``MAX_REPORTED_ISSUES`` are listed).
    """
    if text.startswith(_UTF8_BOM):
        text = text[1:]               # a byte-order mark is not part of a name
    if not text.strip("\n\r"):
        raise CustomRegistryError([CustomRegistryIssue(
            EMPTY_FILE, "the mapping file is empty")])
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()                   # the final newline, not an empty row
    if len(lines) - 1 > max_rows:
        raise CustomRegistryError([CustomRegistryIssue(
            TOO_MANY_ROWS, f"the mapping has {len(lines) - 1:,} rows; the "
                           f"limit is {max_rows:,}")])
    lines = [line.removesuffix("\r") for line in lines]
    issues: list[CustomRegistryIssue] = []
    total = 0

    def add(issue):
        nonlocal total
        total += 1
        if len(issues) < MAX_REPORTED_ISSUES:
            issues.append(issue)

    header = _header_issue(lines[0].split("\t"))
    if header:
        raise CustomRegistryError([header])     # nothing else is meaningful
    rows: list[tuple[int, tuple[str, ...]]] = []
    for number, line in enumerate(lines[1:], start=2):
        if line == "":
            add(CustomRegistryIssue(
                EMPTY_ROW, "empty line (remove it)", rows=(number,)))
            continue
        if line.startswith("#"):
            add(CustomRegistryIssue(
                COMMENT, "comment/metadata lines are not supported; the "
                         "file is a plain TSV", rows=(number,)))
            continue
        cells = line.split("\t")
        if len(cells) != len(CUSTOM_HEADER):
            add(CustomRegistryIssue(
                FIELD_COUNT, f"expected {len(CUSTOM_HEADER)} tab-separated "
                             f"fields, found {len(cells)}", rows=(number,)))
            continue
        clean = True
        for column, cell in zip(CUSTOM_HEADER, cells):
            control = _control_character(cell) if cell else None
            if control is not None:
                add(CustomRegistryIssue(
                    CONTROL_CHARACTER, f"{column}: control character "
                                       f"U+{ord(control):04X} in "
                                       f"{preview(cell)}", rows=(number,),
                    columns=(column,)))
                clean = False
            elif cell != cell.strip():
                add(CustomRegistryIssue(
                    WHITESPACE, f"{column}: leading or trailing whitespace "
                                f"in {preview(cell)} (names are never "
                                "trimmed)",
                    rows=(number,), columns=(column,)))
                clean = False
        if not clean:
            continue
        if not any(cells):
            add(CustomRegistryIssue(
                NO_ALIAS, "the row has no alias in any column",
                rows=(number,)))
            continue
        rows.append((number, tuple(cells)))

    first_row: dict[tuple[str, ...], int] = {}
    unique: list[tuple[int, tuple[str, ...]]] = []
    for number, cells in rows:
        if cells in first_row:
            add(CustomRegistryIssue(
                DUPLICATE_ROW, f"identical to line {first_row[cells]} "
                               "(duplicate rows are not merged)",
                rows=(first_row[cells], number)))
        else:
            first_row[cells] = number
            unique.append((number, cells))

    owners: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for number, cells in unique:
        for column, cell in zip(CUSTOM_HEADER, cells):
            if cell:    # one string in several columns of one row is fine
                owners[cell].append((number, column))
    for alias, places in owners.items():
        lines_of = tuple(sorted({n for n, _ in places}))
        if len(lines_of) > 1:
            where = listed(f"line {n} {c}" for n, c in places)
            add(CustomRegistryIssue(
                ALIAS_COLLISION,
                f"alias {preview(alias)} names more than one sequence "
                f"({where})",
                rows=lines_of, columns=tuple(c for _, c in places),
                alias=alias))
    if issues:
        raise CustomRegistryError(issues, more=total - len(issues))
    if not unique:
        raise CustomRegistryError([CustomRegistryIssue(
            NO_DATA, "the mapping has a header but no rows")])
    return unique


def load_custom_registry(
    source: bytes | BinaryIO | TextIO,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> ChromosomeRegistry:
    """Build a runtime registry from the content of a custom mapping TSV.

    ``source`` is the file content as ``bytes`` or an open binary/text file
    object (so a GUI upload and a command-line file both fit; no path or
    framework type is involved). Raises ``CustomRegistryError`` when the
    mapping is structurally ambiguous or malformed.
    """
    rows = parse_custom_tsv(_read(source, max_bytes), max_rows=max_rows)
    width = len(str(len(rows)))
    records = {}
    for index, (_, cells) in enumerate(rows, start=1):
        seq_id = f"{SEQ_ID_PREFIX}{index:0{max(6, width)}d}"
        by_column = dict(zip(CUSTOM_HEADER, cells))
        aliases = {a: by_column[a] for a in AUTHORITIES if by_column[a]}
        records[seq_id] = SequenceRecord(seq_id, MappingProxyType(aliases))
    return ChromosomeRegistry(None, records, name=CUSTOM_REGISTRY_NAME)
