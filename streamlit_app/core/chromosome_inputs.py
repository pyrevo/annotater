"""Backend orchestration: normalize both input tables of one annotation run.

One explicit assembly and one target authority govern the coordinate and
the annotation table; each table is normalized once through
``normalize_chromosomes`` and keeps its own report. Nothing here reads UI
state or produces UI text, and nothing is inferred or defaulted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from .chromosome_normalization import (
    ChromosomeNormalizationError,
    ChromosomeNormalizationReport,
    normalize_chromosomes,
)


class StrictInputNormalizationError(ChromosomeNormalizationError):
    """``strict=True`` and at least one table has unresolved identifiers.

    Both complete reports are attached (``coord_report``, ``annot_report``).
    """

    def __init__(self, coord_report, annot_report):
        self.coord_report = coord_report
        self.annot_report = annot_report
        super().__init__(
            f"{coord_report.assembly}/{coord_report.target}: unresolved "
            f"identifiers (coordinates: {coord_report.unresolved_identifiers}"
            f", annotations: {annot_report.unresolved_identifiers})"
        )


@dataclass(frozen=True)
class InputChromosomeNormalization:
    assembly: str
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
    assembly: str,
    target: str,
    strict: bool = False,
) -> InputChromosomeNormalization:
    """Normalize the coordinate and annotation tables under one explicit
    ``assembly`` and ``target`` authority.

    Non-strict (default): resolvable identifiers are normalized, the others
    stay verbatim, and each table's report carries its own unresolved and
    collapse information. ``strict=True`` raises
    ``StrictInputNormalizationError`` (with both reports) instead of
    returning when either table is incomplete.
    """
    coord = normalize_chromosomes(coord_df, assembly=assembly, target=target)
    annot = normalize_chromosomes(annot_df, assembly=assembly, target=target)
    if strict and not (coord.report.complete and annot.report.complete):
        raise StrictInputNormalizationError(coord.report, annot.report)
    return InputChromosomeNormalization(
        assembly=assembly,
        target=target,
        coord_df=coord.dataframe,
        annot_df=annot.dataframe,
        coord_report=coord.report,
        annot_report=annot.report,
    )
