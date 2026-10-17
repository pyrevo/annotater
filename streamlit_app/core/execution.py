"""Framework-independent scientific execution service for AnnotateR.

This is the single scientific execution workflow shared by every frontend
(the Streamlit GUI, Jyo's FastAPI backend and the future dual-engine CLI).
It imports neither Streamlit nor FastAPI and knows nothing about HTTP,
cookies or session state: a caller translates its own input into an
:class:`AnnotationRequest` and reads the returned :class:`AnnotationOutcome`.

Workflow (identical for every caller):

    validation -> feature filtering -> chromosome normalization
        -> no-shared-identifier warning -> engine dispatch
        -> canonical result -> outcome

The behaviour reference is the released Streamlit RC3 implementation; the
FastAPI backend adopts exactly these semantics. Callers keep their own
presentation (spinners, captions, HTTP status codes); this module only
computes and reports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from . import chromosome_inputs
from .chrom_registry import ChromosomeRegistry, load_registry
from .chromosome_normalization import ChromosomeNormalizationReport
from .engine_registry import (
    EngineUnavailableError,
    build_engine,
    engine_label,
)
from .schema import HAS_OVERLAP_COLUMN, canonicalize_annotation_result
from .vcf_contigs import header_contig_renames
from streamlit_app.config import Settings
from streamlit_app.utils.validators import DataValidator

#: Formats whose ``feature`` column the feature filter applies to.
GFF_LIKE_FORMATS = frozenset({"gff", "gtf"})

#: Operations and join directions the workflow accepts. Validated up front so
#: an invalid HTTP-supplied option is a client error, never a backend failure
#: and never silently coerced to a different operation.
VALID_MODES = frozenset(Settings.ANNOTATION_MODES)
VALID_JOINS = frozenset({"inner", "left"})

#: Private query-row identity column used to derive the matched-coverage
#: metric. It is injected into a *copy* of the normalized query (never the
#: caller's frame) and races the existing canonical metadata re-attachment
#: channel back out of the engine; it is stripped from the public result and
#: never participates in matching. Distinct values in this column among
#: matched rows are exactly the distinct original query rows with >= 1 match,
#: so duplicate query coordinates with distinct row identities are counted
#: separately and a single query matching many annotations is counted once.
_QUERY_ROW_UID_COLUMN = "annotater_query_row_uid"

#: Directional UTR choices are user-facing labels; each maps to the exact,
#: case-sensitive source ``feature`` strings it accepts: the GFF3 /
#: Sequence Ontology terms (five_prime_UTR, three_prime_UTR) and the
#: lowercase spelling used before GFF3 v1.16. A generic ``UTR`` (e.g.
#: GENCODE GTF) carries no direction and is deliberately not matched. All
#: other choices are matched literally. Source values are never rewritten.
#:
#: ``transcript`` means transcript-level annotation records, matched only
#: against this explicit list of source values (no regex, substring,
#: case-insensitive, fuzzy or Sequence Ontology expansion). Each value is
#: named as a transcript-level feature by a primary source:
#:   transcript, mRNA, lnc_RNA, snoRNA, pseudogenic_transcript - Ensembl
#:       GFF3 README ("type of transcript features");
#:   transcript, mRNA, ncRNA, rRNA, tRNA, primary_transcript - NCBI RefSeq
#:       GFF3 documentation (gene-RNA-exon conventions);
#:   transcript - GENCODE; mRNA, noncoding_transcript - GFF3 specification.
#: Ambiguous or undocumented RNA-like types (snRNA, miRNA, lincRNA, RNA,
#: processed_transcript, NMD_transcript_variant, ...) are deliberately
#: excluded. See docs/using/feature-filtering.md.
FEATURE_TYPE_SOURCE_VALUES = {
    "transcript": (
        "transcript", "mRNA", "lnc_RNA", "ncRNA", "rRNA", "tRNA", "snoRNA",
        "primary_transcript", "pseudogenic_transcript",
        "noncoding_transcript",
    ),
    "5' UTR": ("five_prime_UTR", "five_prime_utr"),
    "3' UTR": ("three_prime_UTR", "three_prime_utr"),
}


def expand_feature_types(selected) -> set:
    """Map selected filter choices to the set of accepted source values."""
    accepted = set()
    for choice in selected:
        accepted.update(FEATURE_TYPE_SOURCE_VALUES.get(choice, (choice,)))
    return accepted


class AnnotationError(Exception):
    """The request cannot produce a result.

    ``message`` is user-facing and safe to display verbatim. ``severity``
    distinguishes a truly invalid request (``"error"``) from a valid request
    that legitimately yields nothing (``"warning"``, e.g. a feature filter
    that matches no annotation), so each frontend presents it as it does
    today (Streamlit ``st.error`` vs ``st.warning``; HTTP 400 either way).
    """

    def __init__(self, code: str, message: str, severity: str = "error"):
        self.code = code
        self.message = message
        self.severity = severity
        super().__init__(message)


class AnnotationExecutionError(Exception):
    """A backend execution/canonicalization failure (never an empty result).

    Carries the frontend-agnostic message plus the engine label, mode and
    join needed by a caller that wants to log context.
    """

    def __init__(
        self,
        message: str,
        *,
        engine_label: str,
        mode: str,
        join: str,
        original: Optional[BaseException] = None,
    ):
        self.message = message
        self.engine_label = engine_label
        self.mode = mode
        self.join = join
        self.original = original
        super().__init__(message)


@dataclass(frozen=True)
class AnnotationWarning:
    """A structured, non-fatal note produced by a completed run."""

    code: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class FeatureFilterReport:
    """What the feature filter selected, for a caption or response field."""

    applied: bool
    total_rows: int
    used_rows: int
    selected: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "total_rows": self.total_rows,
            "used_rows": self.used_rows,
            "selected": list(self.selected),
        }


@dataclass(frozen=True)
class ChromosomeNormalizationOutcome:
    """Assembly-aware chromosome normalization result for both input tables."""

    assembly_id: Optional[str]
    registry_name: str
    target: str
    coord_report: ChromosomeNormalizationReport
    annot_report: ChromosomeNormalizationReport

    def as_dict(self) -> Dict[str, Any]:
        return {
            "assembly": self.assembly_id,
            "registry_name": self.registry_name,
            "target": self.target,
            "coord_report": _report_as_dict(self.coord_report),
            "annot_report": _report_as_dict(self.annot_report),
        }


def _report_as_dict(report: ChromosomeNormalizationReport) -> Dict[str, Any]:
    return {
        "assembly": report.assembly,
        "registry_name": report.registry_name,
        "target": report.target,
        "total_rows": report.total_rows,
        "unique_identifiers": report.unique_identifiers,
        "resolved_changed_identifiers": report.resolved_changed_identifiers,
        "resolved_unchanged_identifiers": report.resolved_unchanged_identifiers,
        "changed_rows": report.changed_rows,
        "renames": dict(report.renames),
        "unknown": dict(report.unknown),
        "no_alias_for_target": dict(report.no_alias_for_target),
        "collapses": {k: list(v) for k, v in report.collapses.items()},
        "unresolved_identifiers": report.unresolved_identifiers,
        "unresolved_rows": report.unresolved_rows,
        "complete": report.complete,
    }


@dataclass(frozen=True)
class AnnotationRequest:
    """A framework-independent request for one annotation run.

    ``query`` and ``annotation`` are already parsed into the canonical
    interval model (parsing is an upstream, caller-specific concern). Either
    ``registry`` (an already-loaded ``ChromosomeRegistry``) or ``assembly``
    (a bundled assembly id) supplies chromosome identity when ``chr_naming``
    is set; exactly one is used and neither is ever inferred.
    """

    query: pd.DataFrame
    annotation: pd.DataFrame
    annotation_format: Optional[str] = None
    engine: str = "bedtools"
    mode: str = "overlap"
    join: str = "left"
    use_strand: bool = False
    min_overlap: Optional[float] = None
    feature_types: Tuple[str, ...] = ()
    chr_naming: Optional[str] = None
    assembly: Optional[str] = None
    registry: Optional[ChromosomeRegistry] = None
    coord_vcf_header_lines: Optional[Sequence[str]] = None


@dataclass(frozen=True)
class AnnotationOutcome:
    """Everything one completed run produced, framework-independent."""

    result_df: pd.DataFrame
    coord_df: pd.DataFrame
    annot_df: pd.DataFrame
    engine: str
    engine_label: str
    mode: str
    join: str
    elapsed_seconds: float
    feature_filter: Optional[FeatureFilterReport]
    chromosome_normalization: Optional[ChromosomeNormalizationOutcome]
    coord_renames: Mapping[str, str]
    annot_renames: Mapping[str, str]
    coord_collapses: Mapping[str, Tuple[str, ...]]
    annot_collapses: Mapping[str, Tuple[str, ...]]
    vcf_header_lines: Optional[List[str]]
    vcf_contig_renames: Mapping[str, str]
    warnings: Tuple[AnnotationWarning, ...] = field(default_factory=tuple)
    #: Distinct original query rows (row identity, not coordinates) with at
    #: least one match, for both join directions. Display/reporting only; the
    #: public result schema is unchanged.
    matched_query_count: int = 0


def _min_overlap_for(mode: str, value) -> Optional[float]:
    """Engine-facing min_overlap: overlap mode only, ``0`` -> ``None``."""
    if mode != "overlap" or not value:
        return None
    return float(value)


def _noncolliding_column(columns, preferred: str) -> str:
    """A metadata column name guaranteed absent from ``columns``."""
    name = preferred
    suffix = 2
    existing = set(columns)
    while name in existing:
        name = f"{preferred}_{suffix}"
        suffix += 1
    return name


def _dispatch_engine(
    engine, coord_df: pd.DataFrame, annot_df: pd.DataFrame, join: str, mode: str
):
    """Run one annotation and return ``(result_df, matched_query_count)``.

    ``matched_query_count`` is the number of distinct original query rows
    with at least one match (0..len(coord_df)). It is derived from per-query
    row identity, never from the number of result rows, so a query matching
    many annotations counts once and a query matching none counts zero for
    both join directions. The public result schema is unchanged: the private
    identity column is stripped before returning.
    """
    extra_columns = ("distance",) if mode == "closest" else ()

    if len(coord_df) == 0:
        raw_result = engine.intersect(coord_df, annot_df, how=join)
        result_df = canonicalize_annotation_result(
            raw_result, coord_df, annot_df, extra_columns=extra_columns
        )
        return result_df, 0

    uid = _noncolliding_column(coord_df.columns, _QUERY_ROW_UID_COLUMN)
    engine_coord_df = coord_df.copy()
    engine_coord_df[uid] = list(range(len(engine_coord_df)))

    raw_result = engine.intersect(engine_coord_df, annot_df, how=join)
    result_df = canonicalize_annotation_result(
        raw_result, engine_coord_df, annot_df, extra_columns=extra_columns
    )

    uid_result_column = f"coord_{uid}"
    matched_query_count = int(
        result_df.loc[result_df[HAS_OVERLAP_COLUMN], uid_result_column].nunique()
    ) if uid_result_column in result_df.columns else 0
    result_df = result_df.drop(columns=[uid_result_column])
    return result_df, matched_query_count


def execute_annotation(request: AnnotationRequest) -> AnnotationOutcome:
    """Run the single scientific workflow and return its outcome.

    Raises:
        AnnotationError: the request is invalid or legitimately yields no
            run (see ``code``/``severity``).
        AnnotationExecutionError: a backend or canonicalization failure; a
            backend exception is never reported as an empty result.
    """
    coord_df = request.query
    annot_df = request.annotation

    if coord_df is None:
        raise AnnotationError(
            "no_query",
            "No usable query table: upload a coordinate file, and if it is "
            "in a custom format, apply the column mapping first.",
        )
    if annot_df is None:
        raise AnnotationError("no_annotation", "Upload an annotation file first.")

    # --- Request shape (invalid option, not a backend error) ---
    if request.mode not in VALID_MODES:
        raise AnnotationError(
            "invalid_mode",
            f"Invalid operation {request.mode!r}; choose one of "
            f"{sorted(VALID_MODES)}.",
        )
    if request.join not in VALID_JOINS:
        raise AnnotationError(
            "invalid_join",
            f"Invalid join {request.join!r}; choose one of "
            f"{sorted(VALID_JOINS)}.",
        )

    # --- Validation (invalid user input, not a backend error) ---
    is_valid, error = DataValidator.validate_coordinates(coord_df)
    if not is_valid:
        raise AnnotationError(
            "invalid_query_coordinates",
            f"Query coordinate file is not valid: {error}",
        )
    is_valid, error = DataValidator.validate_coordinates(annot_df)
    if not is_valid:
        raise AnnotationError(
            "invalid_annotation_coordinates",
            f"Annotation file is not valid: {error}",
        )

    # --- Feature filter (GFF/GTF only) ---
    feature_report: Optional[FeatureFilterReport] = None
    selected = tuple(request.feature_types or ())
    if (
        request.annotation_format in GFF_LIKE_FORMATS
        and selected
        and "feature" in annot_df.columns
    ):
        original_count = len(annot_df)
        annot_df = annot_df[
            annot_df["feature"].isin(expand_feature_types(selected))
        ].copy()
        feature_report = FeatureFilterReport(
            applied=True,
            total_rows=original_count,
            used_rows=len(annot_df),
            selected=selected,
        )
        if len(annot_df) == 0:
            raise AnnotationError(
                "no_feature_match",
                f"No annotations match the selected feature types "
                f"(filtered {original_count:,} features). Adjust the feature "
                f"filter and run again.",
                severity="warning",
            )

    # --- Chromosome normalization ---
    chr_outcome: Optional[ChromosomeNormalizationOutcome] = None
    coord_renames: Mapping[str, str] = {}
    annot_renames: Mapping[str, str] = {}
    coord_collapses: Mapping[str, Tuple[str, ...]] = {}
    annot_collapses: Mapping[str, Tuple[str, ...]] = {}
    vcf_contig_renames: Mapping[str, str] = {}
    if request.chr_naming is not None:
        registry = request.registry
        if registry is None:
            if request.assembly is None:
                raise AnnotationError(
                    "assembly_required",
                    "Select the genome assembly before normalizing chromosome "
                    "names.",
                )
            registry = load_registry(request.assembly)
        normalized = chromosome_inputs.normalize_input_chromosomes(
            coord_df, annot_df, registry=registry, target=request.chr_naming
        )
        coord_df, annot_df = normalized.coord_df, normalized.annot_df
        coord_renames = dict(normalized.coord_renames)
        annot_renames = dict(normalized.annot_renames)
        coord_collapses = dict(normalized.coord_collapses)
        annot_collapses = dict(normalized.annot_collapses)
        chr_outcome = ChromosomeNormalizationOutcome(
            assembly_id=registry.assembly_id,
            registry_name=registry.name,
            target=request.chr_naming,
            coord_report=normalized.coord_report,
            annot_report=normalized.annot_report,
        )
        # Row-derived renames come from the normalization report, never
        # re-derived; header ##contig declarations are normalized through the
        # same registry and target (also for contigs no row uses), and the
        # row answer wins on conflict (same registry, so they agree).
        if request.coord_vcf_header_lines:
            vcf_contig_renames = {
                **header_contig_renames(
                    request.coord_vcf_header_lines, registry, request.chr_naming
                ),
                **coord_renames,
            }
        else:
            vcf_contig_renames = dict(coord_renames)

    # --- No-shared-identifiers warning (non-fatal) ---
    warnings: List[AnnotationWarning] = []
    if len(coord_df) > 0 and len(annot_df) > 0:
        shared = set(coord_df["chr"].unique()) & set(annot_df["chr"].unique())
        if not shared:
            warnings.append(
                AnnotationWarning(
                    "no_shared_identifiers",
                    "No shared chromosome identifiers remain between query and "
                    "annotation data. Select the genome assembly and a "
                    "chromosome naming above to normalize names, or check the "
                    "names used by each file.",
                )
            )

    # --- Engine dispatch (explicit; no automatic fallback) ---
    try:
        engine = build_engine(
            request.engine,
            mode=request.mode,
            use_strand=request.use_strand,
            min_overlap=_min_overlap_for(request.mode, request.min_overlap),
        )
    except EngineUnavailableError as exc:
        raise AnnotationError("engine_unavailable", str(exc))
    except ValueError as exc:
        raise AnnotationError("invalid_option", f"Invalid option: {exc}")
    label = engine_label(request.engine)

    # --- Execution + canonicalization ---
    started = time.perf_counter()
    try:
        result_df, matched_query_count = _dispatch_engine(
            engine, coord_df, annot_df, request.join, request.mode
        )
    except Exception as exc:
        raise AnnotationExecutionError(
            f"{label} failed during {request.mode} annotation "
            f"({request.join} join): {exc}",
            engine_label=label,
            mode=request.mode,
            join=request.join,
            original=exc,
        ) from exc
    elapsed = time.perf_counter() - started

    return AnnotationOutcome(
        result_df=result_df,
        coord_df=coord_df,
        annot_df=annot_df,
        engine=request.engine,
        engine_label=label,
        mode=request.mode,
        join=request.join,
        elapsed_seconds=elapsed,
        feature_filter=feature_report,
        chromosome_normalization=chr_outcome,
        coord_renames=coord_renames,
        annot_renames=annot_renames,
        coord_collapses=coord_collapses,
        annot_collapses=annot_collapses,
        vcf_header_lines=(
            list(request.coord_vcf_header_lines)
            if request.coord_vcf_header_lines
            else None
        ),
        vcf_contig_renames=vcf_contig_renames,
        warnings=tuple(warnings),
        matched_query_count=matched_query_count,
    )
