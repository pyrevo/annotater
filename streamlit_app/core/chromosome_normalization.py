"""Assembly-aware chromosome identifier normalization for interval tables.

Normalization is alias resolution within one explicit genome assembly
(SPEC 5.1): every distinct identifier is resolved to a sequence record of
that assembly and replaced by the record's verified alias for the requested
target authority. It is not liftover and never touches anything but the
``chr`` column.

Identifiers that do not resolve (``unknown``) or whose sequence has no alias
for the target (``no_alias_for_target``) are kept verbatim and reported; the
result never implies they were validated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from .chrom_registry import (
    AUTHORITIES,
    UnsupportedAuthorityError,
    load_registry,
)

CHR_COLUMN = "chr"


class ChromosomeNormalizationError(ValueError):
    """The input to normalization violates the interval-table contract."""


class StrictChromosomeNormalizationError(ChromosomeNormalizationError):
    """``strict=True`` and some identifiers could not be normalized.

    ``report`` holds the complete structured report.
    """

    def __init__(self, report: ChromosomeNormalizationReport):
        self.report = report
        examples = list(report.unknown)[:3] + list(report.no_alias_for_target)[:3]
        super().__init__(
            f"{report.assembly}/{report.target}: "
            f"{len(report.unknown)} unknown and "
            f"{len(report.no_alias_for_target)} identifiers without a "
            f"{report.target} alias (e.g. {examples})"
        )


def _frozen(mapping) -> Mapping:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class ChromosomeNormalizationReport:
    """Immutable outcome of one normalization, at unique-identifier level.

    ``renames`` maps each source identifier whose string actually changed to
    its target alias (resolved-unchanged and unresolved identifiers are
    absent); it is the single source of truth for downstream metadata
    reconciliation. ``unknown`` and ``no_alias_for_target`` map each
    unresolved source identifier to its row count. ``collapses`` maps a
    target alias to the (two or more) distinct source identifiers that were
    rendered to it.
    """

    assembly: str
    target: str
    total_rows: int
    unique_identifiers: int
    resolved_changed_identifiers: int
    resolved_unchanged_identifiers: int
    changed_rows: int
    renames: Mapping[str, str]
    unknown: Mapping[str, int]
    no_alias_for_target: Mapping[str, int]
    collapses: Mapping[str, tuple[str, ...]]

    @property
    def resolved_identifiers(self) -> int:
        return (self.resolved_changed_identifiers
                + self.resolved_unchanged_identifiers)

    @property
    def unresolved_identifiers(self) -> int:
        return len(self.unknown) + len(self.no_alias_for_target)

    @property
    def unresolved_rows(self) -> int:
        return (sum(self.unknown.values())
                + sum(self.no_alias_for_target.values()))

    @property
    def complete(self) -> bool:
        """True only if every identifier was resolved and rendered."""
        return self.unresolved_identifiers == 0


@dataclass(frozen=True)
class NormalizationResult:
    dataframe: pd.DataFrame
    report: ChromosomeNormalizationReport


def _check_arguments(df, assembly, target) -> None:
    if not isinstance(assembly, str) or not assembly:
        raise ChromosomeNormalizationError(
            "an explicit, non-empty assembly is required; it is never "
            "defaulted or inferred"
        )
    if target not in AUTHORITIES:
        raise UnsupportedAuthorityError(
            f"unsupported target authority {target!r}; "
            f"expected one of {AUTHORITIES}"
        )
    if not isinstance(df, pd.DataFrame):
        raise ChromosomeNormalizationError("df must be a pandas DataFrame")
    if CHR_COLUMN not in df.columns:
        raise ChromosomeNormalizationError(
            f"dataframe has no {CHR_COLUMN!r} column"
        )


def _check_identifiers(series: pd.Series, uniques) -> None:
    if series.isna().any():
        raise ChromosomeNormalizationError(
            "chromosome identifiers must be present on every row; null "
            "values are invalid data, not unknown identifiers"
        )
    for value in uniques:
        if not isinstance(value, str):
            raise ChromosomeNormalizationError(
                f"chromosome identifiers must be str, got "
                f"{type(value).__name__} ({value!r}); they are not coerced"
            )


def normalize_chromosomes(
    df: pd.DataFrame,
    *,
    assembly: str,
    target: str,
    strict: bool = False,
) -> NormalizationResult:
    """Render every chromosome identifier of ``df`` as its verified alias for
    the ``target`` authority within ``assembly``.

    Returns a new dataframe (the input is not modified) plus a structured
    report. With ``strict=True``, any unknown identifier or missing target
    alias raises ``StrictChromosomeNormalizationError`` carrying the report
    instead of returning a partially normalized table.
    """
    _check_arguments(df, assembly, target)
    registry = load_registry(assembly)

    series = df[CHR_COLUMN]
    uniques = list(pd.unique(series)) if len(series) else []
    _check_identifiers(series, uniques)
    counts = series.value_counts(sort=False).to_dict() if uniques else {}

    # Resolve and render once per distinct identifier, never per row.
    replacement: dict[str, str] = {}
    unknown: dict[str, int] = {}
    no_alias: dict[str, int] = {}
    sources_by_target: dict[str, list[str]] = {}
    changed = unchanged = changed_rows = 0
    sources_changed: set[str] = set()
    for identifier in uniques:
        resolved = registry.resolve(identifier)
        if not resolved.resolved:
            unknown[identifier] = counts[identifier]
            replacement[identifier] = identifier
            continue
        rendered = registry.render(resolved.seq_id, target)
        if not rendered.rendered:
            no_alias[identifier] = counts[identifier]
            replacement[identifier] = identifier
            continue
        replacement[identifier] = rendered.alias
        sources_by_target.setdefault(rendered.alias, []).append(identifier)
        if rendered.alias == identifier:
            unchanged += 1
        else:
            changed += 1
            sources_changed.add(identifier)
            changed_rows += counts[identifier]

    report = ChromosomeNormalizationReport(
        assembly=assembly,
        target=target,
        total_rows=len(df),
        unique_identifiers=len(uniques),
        resolved_changed_identifiers=changed,
        resolved_unchanged_identifiers=unchanged,
        changed_rows=changed_rows,
        renames=_frozen({i: a for i, a in replacement.items()
                         if i in sources_changed}),
        unknown=_frozen(unknown),
        no_alias_for_target=_frozen(no_alias),
        collapses=_frozen({alias: tuple(sources)
                           for alias, sources in sources_by_target.items()
                           if len(sources) > 1}),
    )
    if strict and not report.complete:
        raise StrictChromosomeNormalizationError(report)

    out = df.copy()
    if uniques:
        # Map plain strings (a categorical would map unseen categories to
        # NaN), then restore the column's dtype.
        mapped = series.astype(object).map(replacement)
        out[CHR_COLUMN] = (mapped.astype("category")
                           if isinstance(series.dtype, pd.CategoricalDtype)
                           else mapped.astype(series.dtype))
    return NormalizationResult(dataframe=out, report=report)
