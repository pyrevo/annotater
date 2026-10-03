"""Collision-safe ``##contig`` reconciliation for chromosome renames.

Only the contig ``ID`` is rewritten; every other attribute is preserved
verbatim. If several declarations end up with the same ID after renaming,
they are merged only when their remaining attributes are identical;
otherwise ``ChromosomeContigCollisionError`` is raised (SPEC 5.1): metadata
is never silently discarded.
"""

from __future__ import annotations

from collections.abc import Mapping


class ChromosomeContigCollisionError(ValueError):
    """Contig declarations collapsing to one ID carry conflicting metadata.

    ``target``: the shared contig ID. ``sources``: the source IDs of the
    colliding declarations. ``conflicts``: attribute name -> tuple of
    ``(source ID, value or None)`` pairs for every attribute that differs.
    """

    def __init__(self, target, sources, conflicts):
        self.target = target
        self.sources = tuple(sources)
        self.conflicts = {k: tuple(v) for k, v in conflicts.items()}
        super().__init__(
            f"##contig declarations {list(self.sources)} all become "
            f"{target!r} but disagree on {sorted(self.conflicts)}"
        )


def parse_contig_attributes(line: str) -> list[tuple[str, str]]:
    """Attributes of a ``##contig=<...>`` line as ordered ``(key, value)``
    pairs, values kept exactly as written (quotes included). Commas inside
    double quotes do not split."""
    # A declaration without its closing ">" is malformed but must not crash
    # the export: its attributes are read up to the end of the line.
    stop = line.rindex(">") if ">" in line else len(line)
    body = line[line.index("<") + 1:stop]
    parts, current, quoted = [], [], False
    for ch in body:
        if ch == '"':
            quoted = not quoted
        if ch == "," and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [tuple(part.split("=", 1)) if "=" in part else (part, "")
            for part in parts]


def _find_id(line: str):
    """``(start, end, quote, value)`` of the ``ID`` attribute of a contig
    line, located by walking the attributes quote-aware: an ``ID=`` inside a
    quoted value (for example a description) is not the contig ID."""
    i = line.index("<") + 1
    quoted = False
    attribute_start = True
    n = len(line)
    while i < n:
        ch = line[i]
        if attribute_start and not quoted and line.startswith("ID=", i):
            j = i + 3
            if j < n and line[j] == '"':
                close = line.find('"', j + 1)
                if close == -1:
                    return None
                return i, close + 1, '"', line[j + 1:close]
            end = j
            while end < n and line[end] not in ",>":
                end += 1
            return i, end, "", line[j:end]
        attribute_start = False
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch == ",":
                attribute_start = True
            elif ch == ">":
                return None
        i += 1
    return None


def _attributes_without_id(line: str) -> dict[str, tuple[str, ...]]:
    attrs: dict[str, list[str]] = {}
    for key, value in parse_contig_attributes(line):
        if key != "ID":
            attrs.setdefault(key, []).append(value)
    return {k: tuple(sorted(v)) for k, v in attrs.items()}


def reconcile_contig_lines(lines, contig_renames: Mapping[str, str] | None):
    """Apply ``contig_renames`` (old -> new ID) to ``##contig`` lines.

    Header order is preserved and unrelated lines are untouched. Of several
    declarations that share a final ID, the first is kept (with its ID
    renamed if needed) and the rest are dropped only if their other
    attributes are identical to it; a conflict raises. Without renames the
    lines are returned unchanged.
    """
    if not contig_renames:
        return list(lines)
    out: list[str] = []
    survivor: dict[str, tuple[str, str]] = {}  # final ID -> (source, line)
    group: dict[str, list[tuple[str, str]]] = {}
    for line in lines:
        if line.startswith("##contig=<"):
            found = _find_id(line)
            if found:
                start, end, quote, source = found
                new_id = contig_renames.get(source, source)
                if new_id != source:
                    line = (line[:start] + f"ID={quote}{new_id}{quote}"
                            + line[end:])
                group.setdefault(new_id, []).append((source, line))
                if new_id in survivor:
                    continue
                survivor[new_id] = (source, line)
        out.append(line)
    for target, members in group.items():
        if len(members) < 2:
            continue
        attrs = [_attributes_without_id(line) for _, line in members]
        conflicts = {}
        for key in sorted({k for a in attrs for k in a}):
            values = [a.get(key) for a in attrs]
            if len(set(values)) > 1:
                conflicts[key] = [
                    (src, None if v is None else ",".join(v))
                    for (src, _), v in zip(members, values)]
        if conflicts:
            raise ChromosomeContigCollisionError(
                target, [src for src, _ in members], conflicts)
    return out
