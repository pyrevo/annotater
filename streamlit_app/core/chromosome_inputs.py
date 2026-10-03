"""Backend orchestration: normalize both input tables of one annotation run.

One explicit registry (a bundled assembly or a loaded custom mapping) and
one target authority govern the coordinate and the annotation table; each
table is normalized once through the shared registry-based normalization and
keeps its own report. Nothing here reads UI
state or produces UI text, and nothing is inferred or defaulted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from .chrom_registry import ChromosomeRegistry, load_registry
from .chromosome_normalization import (
    ChromosomeNormalizationError,
    ChromosomeNormalizationReport,
    _check_assembly,
    _check_target,
    normalize_chromosomes_with_registry,
)


class StrictInputNormalizationError(ChromosomeNormalizationError):
    """``strict=True`` and at least one table has unresolved identifiers.

    Both complete reports are attached (``coord_report``, ``annot_report``).
    """

    def __init__(self, coord_report, annot_report):
        self.coord_report = coord_report
        self.annot_report = annot_report
        super().__init__(
            f"{coord_report.registry_name}/{coord_report.target}: unresolved "
            f"identifiers (coordinates: {coord_report.unresolved_identifiers}"
            f", annotations: {annot_report.unresolved_identifiers})"
        )


@dataclass(frozen=True)
class InputChromosomeNormalization:
    assembly: str | None          # None when a custom registry was used
    registry_name: str
    target: str
    coord_df: pd.DataFrame
    annot_df: pd.DataFrame
    coord_report: ChromosomeNormalizationReport
    annot_report: ChromosomeNormalizationReport

    @property
    def coord_renames(self) -> Mapping[str, str]:
        """Query-side old -> new identifiers (for export metadata)."""
        return self.coord_report.renames

    @property
    def annot_renames(self) -> Mapping[str, str]:
        return self.annot_report.renames

    @property
    def coord_collapses(self) -> Mapping[str, tuple[str, ...]]:
        return self.coord_report.collapses

    @property
    def annot_collapses(self) -> Mapping[str, tuple[str, ...]]:
        return self.annot_report.collapses

    @property
    def complete(self) -> bool:
        return self.coord_report.complete and self.annot_report.complete


def normalize_input_chromosomes(
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    *,
    assembly: str | None = None,
    registry: ChromosomeRegistry | None = None,
    target: str,
    strict: bool = False,
) -> InputChromosomeNormalization:
    """Normalize the coordinate and annotation tables under one explicit
    registry and ``target`` authority.

    Give exactly one of ``assembly`` (a bundled assembly id) or ``registry``
    (an already-loaded registry, e.g. from ``load_custom_registry``); neither
    is ever defaulted or inferred.

    Non-strict (default): resolvable identifiers are normalized, the others
    stay verbatim, and each table's report carries its own unresolved and
    collapse information. ``strict=True`` raises
    ``StrictInputNormalizationError`` (with both reports) instead of
    returning when either table is incomplete.
    """
    if (assembly is None) == (registry is None):
        raise ChromosomeNormalizationError(
            "give exactly one of assembly (bundled) or registry (loaded); "
            "neither is defaulted or inferred"
        )
    if registry is None:
        # same precedence as normalize_chromosomes: assembly, target, load
        _check_assembly(assembly)
        _check_target(target)
        registry = load_registry(assembly)
    coord = normalize_chromosomes_with_registry(
        coord_df, registry=registry, target=target)
    annot = normalize_chromosomes_with_registry(
        annot_df, registry=registry, target=target)
    if strict and not (coord.report.complete and annot.report.complete):
        raise StrictInputNormalizationError(coord.report, annot.report)
    return InputChromosomeNormalization(
        assembly=registry.assembly_id,
        registry_name=registry.name,
        target=target,
        coord_df=coord.dataframe,
        annot_df=annot.dataframe,
        coord_report=coord.report,
        annot_report=annot.report,
    )
