"""Framework-independent annotated-VCF export.

This is the single source of truth for turning a canonical result frame
(``coord_*`` / ``annot_*`` columns) back into a VCF. Both the Streamlit and
FastAPI frontends call :func:`build_annotated_vcf`; neither keeps a second,
divergent writer. The module imports only the standard library, ``pandas``,
the app config and the collision-safe contig reconciler in
:mod:`streamlit_app.core.vcf_contigs` — never Streamlit, FastAPI or React.

Fidelity contract (identical to the canonical Streamlit exporter it replaces):

- original record fields the parse/result path retained are exported
  verbatim: ID, REF, ALT, FILTER, the raw INFO field (including END) and,
  when present, the FORMAT column and per-sample columns in #CHROM order.
  No sample or genotype field is silently discarded and none is invented
  (e.g. a FORMAT is never replaced by a hard-coded ``GT``);
- annotation metadata is APPENDED to INFO under the ``ANNOT_*`` namespace;
  every emitted key is declared by a generated ``##INFO`` line
  (conservative ``Number=.,Type=String``) and never overwrites or duplicates
  an original INFO key;
- ``original_header_lines`` (the source file's ``##`` metadata, retained by
  the parser once per source file) is preserved verbatim in stable source
  order. Exactly one ``##fileformat`` line is emitted — the source's version
  when present, else the ``VCFv4.2`` fallback; duplicate identical lines are
  emitted once. The exporter then adds ``##source=AnnotateR <version>`` and
  ``##date`` (additions, never replacements) and the ``ANNOT_*``
  declarations. Original definitions are never re-synthesized;
- ``contig_renames`` renames only the ID of matching ``##contig`` lines,
  keeping every other attribute; collision-safe reconciliation and conflict
  detection are delegated to :func:`vcf_contigs.reconcile_contig_lines`;
- one output record per canonical result row. Unmatched rows keep the
  original record fields and carry no ``ANNOT_*`` entries. ``POS`` =
  ``coord_start + 1`` (canonical 0-based start -> 1-based VCF POS); REF/ALT/
  END are never rewritten from annotation coordinates.

Failures are explicit. A frame that cannot be turned into a valid VCF raises
:class:`UnrecoverableVCFError` rather than returning a ``"##Error: ..."``
string; an ``ANNOT_*`` declaration whose original type is not ``String``
raises :class:`VCFInfoDeclarationConflict`. Both are subclasses of
:class:`VCFExportError`, itself a :class:`ValueError`, so a frontend can
catch one type or treat them as client/data problems.

Timestamps are deterministic where it matters: ``##date`` honors an explicit
``date_stamp`` argument, then ``$SOURCE_DATE_EPOCH`` (UTC), then the current
local date. It is AnnotateR's own provenance line, never a scientific field.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from streamlit_app.config import Settings

from .vcf_contigs import header_contig_renames, reconcile_contig_lines

#: ``coord_*`` metadata columns that map to fixed VCF fields (or the
#: canonical interval keys) rather than to sample columns: every other
#: ``coord_*`` column in a VCF query result is an original sample column.
VCF_FIXED_COORD_COLUMNS = frozenset({
    "coord_chr", "coord_start", "coord_end", "coord_id", "coord_ref",
    "coord_alt", "coord_qual", "coord_filter", "coord_info",
    "coord_format", "coord_strand",
})

#: ``annot_*`` columns carrying interval/derived values rather than
#: annotation metadata: never serialized into VCF INFO.
VCF_NONINFO_ANNOT_COLUMNS = frozenset({
    "annot_chr", "annot_start", "annot_end", "has_overlap",
})

#: VCF INFO ID is a valid VCF key (``[A-Za-z_][A-Za-z0-9_]*``); anything else
#: is deterministically prefixed with ``x_``.
_INFO_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class VCFExportError(ValueError):
    """Base class for all annotated-VCF export failures.

    A :class:`ValueError` on purpose: these are client/data problems (a frame
    that cannot be reconstructed, or conflicting metadata), not internal
    errors, and the Streamlit exporter has historically surfaced them as
    ``ValueError``.
    """


class UnrecoverableVCFError(VCFExportError):
    """The result frame has no coordinate columns to build a VCF from."""


class VCFInfoDeclarationConflict(VCFExportError):
    """The original header declares an ``ANNOT_*`` INFO ID with a type other
    than ``String``; the original definition is not overwritten."""


def vcf_field(value) -> str:
    """Render a value as a VCF field: canonical missing
    (``pd.NA``/``NaN``/``None``) becomes the VCF MISSING value ``.``; anything
    else is stringified as-is. Prevents ``"<NA>"``/``"nan"`` sentinels from
    leaking into exports."""
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return "."
    return str(value)


def vcf_qual(value) -> str:
    """Render a QUAL value. Missing becomes the VCF MISSING value ``.``.

    The parser stores QUAL as a float (source ``50`` becomes ``50.0``);
    integer-valued numbers are written back without a fractional part so an
    integer source QUAL round-trips verbatim, while genuinely fractional
    values and non-numeric text are written as stored.
    """
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return "."
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(value)


def vcf_info_key(annotation_column: str) -> str:
    """``ANNOT_*``-namespaced INFO identifier for an annotation column.

    The namespace is what keeps emitted keys from colliding with original VCF
    INFO IDs; a suffix that is not a valid VCF INFO ID (must match
    ``[A-Za-z_][A-Za-z0-9_]*``) is deterministically prefixed with ``x_``.
    """
    suffix = annotation_column[len("annot_"):]
    if not _INFO_ID_RE.fullmatch(suffix):
        suffix = f"x_{suffix}"
    return f"ANNOT_{suffix}"


def escape_vcf_info_value(value: str) -> str:
    """Encode an annotation value for VCF INFO. VCF INFO values may not
    contain ``;`` (field separator), ``=`` (key/value separator), or
    whitespace, so the repository's established mapping applies:
    ``;`` -> ``|``, `` `` -> ``_``, ``=`` -> ``:``. Commas are valid in
    String values and pass through. This is a documented lossy encoding:
    re-importing the exported file yields the escaped form, not the original
    value text."""
    return value.replace(";", "|").replace(" ", "_").replace("=", ":")


def _info_contains_key(info_text: str, key: str) -> bool:
    """True if an original INFO field already carries ``key`` (as a flag or a
    ``key=value`` token)."""
    for token in info_text.split(";"):
        if token == key or token.startswith(f"{key}="):
            return True
    return False


def vcf_sample_name(coord_column: str) -> str:
    """Original #CHROM header name for a ``coord_*`` sample column.

    Reverses the parser's deterministic collision rename: a sample whose name
    collides with a parser/core column is stored as ``sample_<name>`` (e.g. a
    sample literally named ``start``). Pathological sample names that already
    start with ``sample_`` cannot be distinguished from renamed columns; the
    renamed form wins.
    """
    name = coord_column[len("coord_"):]
    if name.startswith("sample_"):
        name = name[len("sample_"):]
    return name


def original_header_declarations(original_header_lines) -> dict:
    """Original ``##INFO`` declarations from retained header lines, mapped by
    INFO ID (first declaration wins, source order)."""
    decls = {}
    for line in original_header_lines or []:
        if not isinstance(line, str):
            continue
        m = re.match(r"##INFO=<ID=([A-Za-z0-9_]+)", line)
        if m:
            decls.setdefault(m.group(1), line)
    return decls


def derive_vcf_contig_renames(lines, registry, target: str) -> dict:
    """``{declared ID: new ID}`` for the ``##contig`` IDs of ``lines`` that the
    ``registry`` renders for ``target`` under a different name, whether or not
    any data row uses that contig. Thin wrapper over
    :func:`vcf_contigs.header_contig_renames` (the shared normalization
    contract; unknown IDs and IDs without a target alias are left alone)."""
    return header_contig_renames(lines, registry, target)


def deterministic_date_stamp(date_stamp: Optional[str] = None) -> str:
    """``##date`` value: explicit ``date_stamp`` (``YYYYMMDD``) wins, then
    ``$SOURCE_DATE_EPOCH`` rendered in UTC, then the current local date. Only
    AnnotateR's own provenance line is affected."""
    if date_stamp:
        return date_stamp
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None:
        try:
            return datetime.fromtimestamp(
                int(epoch), tz=timezone.utc
            ).strftime("%Y%m%d")
        except (ValueError, OverflowError, OSError):
            pass
    return pd.Timestamp.now().strftime("%Y%m%d")


def build_annotated_vcf(
    df: pd.DataFrame,
    original_header_lines: Optional[Sequence[str]] = None,
    contig_renames: Optional[Mapping[str, str]] = None,
    *,
    source_label: Optional[str] = None,
    date_stamp: Optional[str] = None,
) -> str:
    """Build the annotated-VCF export of a canonical result frame.

    See the module docstring for the fidelity contract. Raises
    :class:`UnrecoverableVCFError` when no coordinate columns are present and
    :class:`VCFInfoDeclarationConflict` when an original ``ANNOT_*``
    declaration is not String-typed; contig metadata conflicts raise
    :class:`~streamlit_app.core.vcf_contigs.ChromosomeContigCollisionError`
    from the reconciler.
    """
    original = reconcile_contig_lines(
        [
            line for line in (original_header_lines or [])
            if isinstance(line, str) and line.startswith("##")
        ],
        contig_renames,
    )

    # Exactly one ##fileformat: the source's version when present, so the
    # export is never silently upgraded or downgraded; VCFv4.2 is only the
    # fallback for a source without a fileformat line.
    fileformat = "##fileformat=VCFv4.2"
    for line in original:
        if line.lower().startswith("##fileformat"):
            fileformat = line
            break
    lines = [fileformat]
    seen = {fileformat}
    for line in original:
        if line.lower().startswith("##fileformat"):
            # Exactly one fileformat line: the source's first, already
            # emitted above; any further (already invalid) declaration is
            # dropped rather than emitted twice.
            continue
        if line in seen:
            # Duplicate identical metadata lines are emitted once.
            continue
        seen.add(line)
        lines.append(line)
    # AnnotateR provenance: additions, never replacements — an original
    # ##source/##date line (if any) was already retained above.
    label = source_label if source_label is not None else f"AnnotateR {Settings.VERSION}"
    lines.append(f"##source={label}")
    lines.append(f"##date={deterministic_date_stamp(date_stamp)}")

    # Check which coordinate columns we actually have. The canonical frame
    # carries ``coord_*`` names; the bare fallbacks keep the function usable
    # on a hand-built frame.
    available = False
    for int_col in ("coord_chr", "coord_start", "coord_id", "coord_ref",
                    "coord_alt", "coord_qual", "coord_filter"):
        bare = int_col.replace("coord_", "")
        if int_col in df.columns or bare in df.columns:
            available = True
            break
    if not available:
        raise UnrecoverableVCFError(
            "Cannot reconstruct the annotated VCF: the result frame carries "
            "no coordinate columns (coord_chr / chr, coord_start / start, "
            "...). Run an annotation first."
        )

    # Identify annotation columns for INFO field.
    annot_cols = [
        c for c in df.columns
        if c.startswith("annot_") and c not in VCF_NONINFO_ANNOT_COLUMNS
    ]

    # Declare every ANNOT_* key the exporter can emit, in frame column order
    # (deterministic; de-duplicated after ID sanitization).
    info_keys: dict = {}
    for col in annot_cols:
        key = vcf_info_key(col)
        if key not in info_keys:
            info_keys[key] = col
    # ANNOT_* declarations, honoring the collision policy: a pre-existing
    # original declaration of the same ID stands — a String-typed one is kept
    # as-is (no generated duplicate); any other type is refused with an
    # explicit error rather than silently overwritten.
    original_decls = original_header_declarations(original)
    conflicts = []
    declarations = []
    for key, col in info_keys.items():
        decl = original_decls.get(key)
        if decl is None:
            declarations.append(
                f"##INFO=<ID={key},Number=.,Type=String,"
                f'Description="AnnotateR annotation (source column: {col})">'
            )
            continue
        type_match = re.search(r"Type=([A-Za-z0-9_]+)", decl)
        if not type_match or type_match.group(1) != "String":
            conflicts.append(key)
    if conflicts:
        raise VCFInfoDeclarationConflict(
            "Cannot export the annotated VCF: the original header "
            "declares INFO ID(s) "
            f"{', '.join(sorted(conflicts))} with a type other than "
            "String, which conflicts with AnnotateR's ANNOT_* string "
            "annotation values. The original definitions are not "
            "overwritten; remove or rename those IDs in the source VCF."
        )
    lines.extend(declarations)

    # Original FORMAT/sample columns: any coord_* column beyond the fixed
    # ones, in frame order (= the original #CHROM sample order).
    has_format = "coord_format" in df.columns
    sample_columns = [
        c for c in df.columns
        if c.startswith("coord_") and c not in VCF_FIXED_COORD_COLUMNS
    ]
    chrom_header = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if has_format:
        chrom_header.append("FORMAT")
    chrom_header.extend(vcf_sample_name(c) for c in sample_columns)
    lines.append("\t".join(chrom_header))

    vcf_rows = []

    for _, row in df.iterrows():
        # Build standard fields
        fields = []
        fields.append(vcf_field(row.get("coord_chr", row.get("chr", "."))))

        # POS: reconstruct the 1-based VCF position from the canonical start
        # (POS = coord_start + 1). (Using coord_end would be wrong for
        # multi-base variants.)
        pos_value = row.get("coord_start", row.get("start", "."))
        try:
            fields.append(str(int(pos_value) + 1))
        except (TypeError, ValueError):
            fields.append(".")

        # ID/REF/ALT: canonical missing must export as '.', never '<NA>'.
        fields.append(vcf_field(row.get("coord_id", row.get("id", "."))))
        fields.append(vcf_field(row.get("coord_ref", row.get("ref", "."))))
        fields.append(vcf_field(row.get("coord_alt", row.get("alt", "."))))
        # QUAL: canonical missing -> '.', integer-valued floats written back
        # as integers (see vcf_qual); FILTER: canonical missing (e.g. VCF
        # FILTER "." = filters not applied) exports as '.', never a rendered
        # "<NA>"/"nan" token.
        fields.append(vcf_qual(row.get("coord_qual", row.get("qual", "."))))
        fields.append(vcf_field(row.get("coord_filter", row.get("filter", "."))))

        # Build INFO field: the original field is preserved VERBATIM
        # (including END for symbolic variants); ANNOT_* entries are appended,
        # never replacing or duplicating original keys.
        original_info = vcf_field(row.get("coord_info", pd.NA))
        # Empty/missing original INFO must not emit a bare empty field: a
        # record with no original INFO and no annotations gets a bare '.'.
        info_parts = [original_info] if original_info and original_info != "." else []
        emitted_keys = set()
        for col in annot_cols:
            key = vcf_info_key(col)
            if key in emitted_keys:
                # Two columns sanitizing to the same INFO ID: the first in
                # frame order wins, deterministically.
                continue
            if _info_contains_key(original_info, key):
                # The source INFO already carries this key: the original
                # value wins and is never silently overwritten.
                continue
            raw_val = row[col]
            # Canonical missing (unmatched rows after canonicalization) must
            # not leak into INFO as 'Key=<NA>'.
            if pd.api.types.is_scalar(raw_val) and pd.isna(raw_val):
                continue
            val = str(raw_val)
            if val and val not in [".", "nan", "-1", "None", "<NA>"]:
                info_parts.append(f"{key}={escape_vcf_info_value(val)}")
                emitted_keys.add(key)

        fields.append(";".join(info_parts) if info_parts else ".")

        # Original FORMAT and sample columns, preserved verbatim (VCF '.' is
        # already canonical missing and renders back to '.').
        if has_format:
            fields.append(vcf_field(row.get("coord_format", pd.NA)))
        for c in sample_columns:
            fields.append(vcf_field(row[c]))

        vcf_rows.append("\t".join(fields))

    return "\n".join(lines + vcf_rows)