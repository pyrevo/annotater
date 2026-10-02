"""
AnnotateR - Genomic Coordinate Annotation Tool

Main Streamlit application.

Pipeline (Task 7): the engine choice changes execution only.

    upload -> detect/parse format -> canonical normalize
            -> [engine selector: Bedtools | Polars-Bio]
            -> canonical result -> preview / metrics / downloads

Parser selection, coordinate interpretation, metadata handling, result
schema, and export semantics are identical for both backends; only the
interval engine differs.
"""

import hashlib
import logging
import re
import sys
from pathlib import Path

# Ensure the repository root is on the Python path so the
# streamlit_app package (and its subpackages) can be imported
# no matter where `streamlit run` is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app.config import Settings
from streamlit_app.core import (
    CustomParser,
    FormatDetector,
    canonicalize_annotation_result,
    coordinate_system_for,
    extension_authoritative_for,
    normalize_intervals,
    parse_and_normalize,
    CanonicalSchemaError,
)
from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
from streamlit_app.core.vcf_contigs import (
    ChromosomeContigCollisionError,
    reconcile_contig_lines,
)
from streamlit_app.core.engine_registry import (
    DEFAULT_ENGINE,
    ENGINE_OPTIONS,
    EngineUnavailableError,
    build_engine,
    engine_available,
    engine_label,
    unavailable_message,
)
from streamlit_app.utils import (
    DataValidator,
    format_file_size,
    save_uploaded_file,
)

logger = logging.getLogger("annotater.app")

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title=f"{Settings.APP_NAME} - {Settings.DESCRIPTION}",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

#: Typography polish (v0.1.0 maintainer browser review): raise the small
#: supporting text 1-2 px toward the readable 16 px body/footer size while
#: preserving the hierarchy (supporting text < widget labels < headings).
#: Streamlit's theme configuration exposes no font-size controls, so a
#: minimal, testid-scoped, typography-only CSS block is injected once. It
#: only sets font-size on the stable data-testid hooks for widget labels
#: (14 -> 16 px), captions (14 -> 15 px), and help-text tooltip bodies
#: (14 -> 15 px); no layout, colors, headings, controls, or metrics change.
_TYPOGRAPHY_CSS = """<style>
[data-testid="stWidgetLabel"] { font-size: 1rem; }
[data-testid="stCaptionContainer"] { font-size: 0.9375rem; }
[data-testid="stTooltipContent"] { font-size: 0.9375rem; }
</style>"""

# Developer chrome (Rerun / Deploy / Clear cache, top-right toolbar): use
# the official Streamlit `client.toolbarMode` setting. "auto" shows the
# developer options only for local (localhost / community-cloud developer)
# access, so a deployed (SciLifeLab Serve) audience sees a clean toolbar
# while local development ergonomics are preserved. Setting it explicitly
# here documents that choice and pins it against upstream default changes.
st.set_option("client.toolbarMode", "auto")

#: UI option labels in display order (user-facing, no internal class names).
ENGINE_UI_OPTIONS = [label for _, label in ENGINE_OPTIONS]
_ENGINE_LABEL_TO_KEY = {label: key for key, label in ENGINE_OPTIONS}

_RESULT_STATE_KEYS = (
    "result_signature",
    "result_df",
    "result_coord_df",
    "result_engine",
    "result_mode",
    "result_join",
    "result_coord_format",
    "result_vcf_header_lines",
    "result_vcf_contig_renames",
    "result_chr_normalization",
)

_COORD_SYSTEM_OPTIONS = [
    "Auto-detect",
    "0-based (BED)",
    "1-based (GFF/GTF/VCF)",
]

# Genome assemblies offered for chromosome-name normalization: display
# label -> assembly id. The label names the species only for the reader;
# nothing is inferred from it or from the input files.
_ASSEMBLY_PLACEHOLDER = "Select genome assembly"
_ASSEMBLY_OPTIONS = {
    "Human \u2014 GRCh38": "GRCh38",
    "Human \u2014 hg19": "hg19",
    "Mouse \u2014 GRCm39": "GRCm39",
    "Fruit fly \u2014 dm6": "dm6",
    "Zebrafish \u2014 GRCz11": "GRCz11",
    "Rat \u2014 mRatBN7.2 (rn7)": "rn7",
}
_ASSEMBLY_LABELS = {v: k for k, v in _ASSEMBLY_OPTIONS.items()}

# Chromosome naming choices: display label -> naming system (None = keep
# the names exactly as provided).
_NAMING_OPTIONS = {
    "Keep original names": None,
    "UCSC names": "ucsc",
    "Ensembl names": "ensembl",
    "NCBI RefSeq accessions": "refseq",
    "GenBank accessions": "genbank",
    "Assembly names": "assembly",
}
_NAMING_LABELS = {v: k for k, v in _NAMING_OPTIONS.items()}

_ASSEMBLY_REQUIRED_MESSAGE = (
    "Select the genome assembly before normalizing chromosome names."
)

_FEATURE_TYPE_OPTIONS = [
    "gene", "transcript", "exon", "CDS", "5' UTR", "3' UTR",
    "start_codon", "stop_codon",
]

# Directional UTR choices are user-facing labels; each maps to the exact,
# case-sensitive source ``feature`` strings it accepts: the GFF3 /
# Sequence Ontology terms (five_prime_UTR, three_prime_UTR) and the
# lowercase spelling used before GFF3 v1.16. A generic ``UTR`` (e.g.
# GENCODE GTF) carries no direction and is deliberately not matched. All
# other choices are matched literally. Source values are never rewritten.
#
# ``transcript`` means transcript-level annotation records, matched only
# against this explicit list of source values (no regex, substring,
# case-insensitive, fuzzy or Sequence Ontology expansion). Each value is
# named as a transcript-level feature by a primary source:
#   transcript, mRNA, lnc_RNA, snoRNA, pseudogenic_transcript - Ensembl
#       GFF3 README ("type of transcript features");
#   transcript, mRNA, ncRNA, rRNA, tRNA, primary_transcript - NCBI RefSeq
#       GFF3 documentation (gene-RNA-exon conventions);
#   transcript - GENCODE; mRNA, noncoding_transcript - GFF3 specification.
# Ambiguous or undocumented RNA-like types (snRNA, miRNA, lincRNA, RNA,
# processed_transcript, NMD_transcript_variant, ...) are deliberately
# excluded. See docs/using/feature-filtering.md.
_FEATURE_TYPE_SOURCE_VALUES = {
    "transcript": (
        "transcript", "mRNA", "lnc_RNA", "ncRNA", "rRNA", "tRNA", "snoRNA",
        "primary_transcript", "pseudogenic_transcript",
        "noncoding_transcript",
    ),
    "5' UTR": ("five_prime_UTR", "five_prime_utr"),
    "3' UTR": ("three_prime_UTR", "three_prime_utr"),
}


def _expand_feature_types(selected):
    """Map selected filter choices to the set of accepted source values."""
    accepted = set()
    for choice in selected:
        accepted.update(_FEATURE_TYPE_SOURCE_VALUES.get(choice, (choice,)))
    return accepted


# ---------------------------------------------------------------------------
# Small helpers (backend-independent)
# ---------------------------------------------------------------------------

def _declared_coordinate_system(option: str):
    """Map a UI coordinate-system selector to an explicit system (or None)."""
    if option.startswith("0-based"):
        return "0-based"
    if option.startswith("1-based"):
        return "1-based"
    return None


def _file_identity(uploaded):
    """Identity of an uploaded file for cache/invalidation purposes.

    Content-derived: (name, size, sha256 of the bytes). Filename and
    size alone are NOT an identity — a replacement upload with the
    same name and byte length but different coordinates must invalidate
    the cached parse and any result that depended on it. The content is
    already fully in memory (UploadedFile), so hashing it creates no
    persistent copy; modification time and object identity are never
    used.
    """
    if uploaded is None:
        return None
    digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
    return (uploaded.name, uploaded.size, digest)


def _clear_results_state():
    """Explicit invalidation of stored results (Task 7, state safety)."""
    for key in _RESULT_STATE_KEYS:
        st.session_state.pop(key, None)


def _config_signature(cfg: dict, coord_identity, annot_identity, coord_format):
    """
    Signature of every semantics-affecting input of one run.

    Any change — engine, mode, inputs, join-relevant options, min_overlap,
    strand, coordinate systems, chromosome naming (and the genome assembly
    it is normalized under), feature filter, or
    file/mapping identity — changes the signature, so stored results can
    never be displayed as if they belonged to the new configuration.
    """
    return (
        cfg["engine"],
        cfg["mode"],
        cfg["join"],
        cfg["use_strand"],
        cfg["min_overlap"] if cfg["mode"] == "overlap" else None,
        cfg["coord_system"],
        cfg["annot_system"],
        cfg["chr_naming"],
        # The assembly only matters when names are actually normalized.
        cfg["chr_assembly"] if cfg["chr_naming"] else None,
        tuple(cfg["feature_types"]),
        coord_identity,
        annot_identity,
        coord_format,
        st.session_state.get("coord_mapping"),
    )


def _min_overlap_for(cfg: dict):
    """
    Engine-facing min_overlap value.

    min_overlap is meaningful for the overlap mode only (SPEC 8.2); other
    modes never receive it, so a stale slider value cannot leak into a
    contains/within/closest run. ``0`` maps to ``None`` (ordinary positive
    overlap) per the existing UI/API policy.
    """
    value = cfg["min_overlap"]
    if cfg["mode"] != "overlap" or not value:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Parsing (backend-independent; cached per file identity)
# ---------------------------------------------------------------------------

def _get_parsed_frame(state_key: str, uploaded, declared_system,
                      invalidate_mapping: bool = False, role: str = "coord"):
    """
    Parse an uploaded file to its (pre-mapping) DataFrame, caching by
    file identity so unchanged files are not re-parsed on every rerun.

    Custom *annotation* tables already use the canonical column names
    (chr/start/end), so the user's declared coordinate system is applied
    exactly once here, at the canonical boundary; the stored frame is
    then system-dependent and a changed declaration invalidates it.

    Returns {"identity", "format", "df", "system"} or None (nothing
    uploaded, or a parse failure already surfaced as a user-visible
    error). ``system`` is the coordinate system the stored frame
    represents, or None when the parse is system-independent.
    """
    if uploaded is None:
        st.session_state.pop(state_key, None)
        return None

    identity = _file_identity(uploaded)
    current_system = declared_system or "0-based"
    cached = st.session_state.get(state_key)
    if isinstance(cached, dict) and cached["identity"] == identity:
        # A stored frame that depends on the declared coordinate system
        # is only valid for the declaration it was normalized with;
        # system-independent parses are valid for any declaration.
        if cached.get("system") is None or cached["system"] == current_system:
            return cached

    path = save_uploaded_file(uploaded)
    try:
        fmt = FormatDetector.detect(str(path))
        applied_system = None
        if fmt == "custom":
            # No fixed coordinate columns yet; canonical normalization
            # for custom files happens only after explicit column
            # mapping — except custom *annotation* tables, which already
            # carry the canonical chr/start/end column names: their
            # declared coordinate system is applied once, at this
            # boundary.
            try:
                df = CustomParser.parse(str(path))
            except Exception as exc:
                st.error(
                    f"Could not parse the uploaded file `{uploaded.name}`: {exc}"
                )
                return None
            if role == "annot" and all(c in df.columns for c in ("chr", "start", "end")):
                applied_system = current_system
                try:
                    df = normalize_intervals(df, coordinate_system=applied_system)
                except Exception as exc:
                    st.error(
                        f"Could not normalize custom annotation coordinates "
                        f"(declared {applied_system}): {exc}"
                    )
                    return None
        else:
            # Known formats by authoritative extension (.bed, .gff/.gff3,
            # .gtf, .vcf) have a specification-fixed coordinate system:
            # the parse is system-independent. A known format *sniffed
            # from extension-neutral content* (.tsv/.txt/.csv/no
            # extension) is not authoritative: an explicit coordinate
            # declaration takes precedence over content sniffing, so the
            # stored frame depends on the declaration and is invalidated
            # when it changes (Auto-detect keeps the sniffed semantics).
            # This path is independent of the engine choice.
            if not extension_authoritative_for(fmt, Path(path).suffix.lower()):
                applied_system = coordinate_system_for(
                    fmt, declared_system, extension=Path(path).suffix.lower()
                )
            try:
                df = parse_and_normalize(
                    str(path),
                    fmt=fmt,
                    declared_system=declared_system,
                )
            except Exception as exc:
                st.error(f"Could not parse `{uploaded.name}` as {fmt.upper()}: {exc}")
                return None
    finally:
        # The parsed frame is fully in memory at this point (or the
        # parse failed and there is nothing to keep): delete the
        # transient upload copy immediately, on success and on failure,
        # so uploads never accumulate for the lifetime of the session.
        path.unlink(missing_ok=True)

    info = {
        "identity": identity,
        "format": fmt,
        "df": df,
        "system": applied_system,
        # VCF only: original ## metadata lines, retained once per source
        # file (serialization provenance for the annotated VCF export);
        # None for every other format.
        "vcf_header_lines": df.attrs.pop("vcf_header_lines", None),
    }
    st.session_state[state_key] = info
    if invalidate_mapping:
        # A new coordinate file invalidates any previously applied
        # column mapping.
        st.session_state.pop("coord_mapping", None)
        st.session_state.pop("coord_mapped_df", None)
    return info


def _resolve_coord_frame(coord_info, cfg):
    """
    The canonical query frame: parsed frame for known formats, or the
    explicitly mapped + normalized frame for custom files (None when no
    valid mapping has been applied yet).
    """
    if coord_info is None:
        return None
    if coord_info["format"] != "custom":
        return coord_info["df"]
    mapping = st.session_state.get("coord_mapping")
    if not mapping:
        return None
    # If the declared coordinate system changed after the mapping was
    # applied, the mapped frame is stale: require an explicit re-map.
    current_system = _declared_coordinate_system(cfg["coord_system"]) or "0-based"
    if mapping[3] != current_system:
        st.session_state.pop("coord_mapping", None)
        st.session_state.pop("coord_mapped_df", None)
        return None
    return st.session_state.get("coord_mapped_df")


# ---------------------------------------------------------------------------
# Sidebar: configuration (grouped, backend choice isolated)
# ---------------------------------------------------------------------------

def render_sidebar() -> dict:
    with st.sidebar:
        st.header("Configure")

        # --- Annotation: engine, operation, join --------------------
        st.subheader("Annotation")

        engine_label_sel = st.radio(
            "Annotation engine",
            ENGINE_UI_OPTIONS,
            index=ENGINE_UI_OPTIONS.index(engine_label(DEFAULT_ENGINE)),
            key="engine",
            help=(
                "Execution backend for the interval operation. Both backends "
                "implement the same AnnotateR annotation semantics."
            ),
        )
        st.caption(
            "**Bedtools** — established command-line backend. "
            "**Polars-Bio** — dataframe-based backend."
        )
        engine_key = _ENGINE_LABEL_TO_KEY[engine_label_sel]
        if not engine_available(engine_key):
            st.warning(unavailable_message(engine_key))

        mode = st.selectbox(
            "Operation",
            list(Settings.ANNOTATION_MODES.keys()),
            format_func=lambda m: m.title(),
            key="mode",
            help="Interval relation between query and annotation",
        )
        st.caption(Settings.ANNOTATION_MODES[mode]["description"])
        if mode == "closest":
            st.caption(
                "Distance is the number of bases between intervals; "
                "overlapping or touching intervals have distance 0, and "
                "if several annotations tie for the nearest, all of them "
                "are returned."
            )

        join = st.radio(
            "Join behavior",
            ["Keep all query rows (left join)", "Matched rows only (inner join)"],
            key="join",
            help=(
                "Left keeps every query row (unmatched rows carry canonical "
                "missing annotation values); inner keeps only rows with a "
                "qualifying annotation."
            ),
        )
        join = "left" if join.startswith("Keep all") else "inner"

        # --- Input interpretation -----------------------------------
        st.subheader("Input options")
        coord_system = st.selectbox(
            "Query coordinates",
            _COORD_SYSTEM_OPTIONS,
            key="coord_system",
            help=(
                "For known formats (BED/GFF/GTF/VCF) the coordinate system "
                "is fixed by the format specification; for custom files this "
                "declares it (default: 0-based half-open)."
            ),
        )
        annot_system = st.selectbox(
            "Annotation coordinates",
            _COORD_SYSTEM_OPTIONS,
            key="annot_system",
            help=(
                "For known formats (BED/GFF/GTF/VCF) the coordinate system "
                "is fixed by the format specification; for custom files this "
                "declares it (default: 0-based half-open)."
            ),
        )
        chr_assembly_label = st.selectbox(
            "Genome assembly",
            [_ASSEMBLY_PLACEHOLDER, *_ASSEMBLY_OPTIONS],
            key="chr_assembly",
            help=(
                "Chromosome names can refer to different sequences in "
                "different genome assemblies. Select the assembly used by "
                "your input files so AnnotateR can normalize names safely. "
                "Not needed when names are kept as they are."
            ),
        )
        chr_naming_label = st.selectbox(
            "Chromosome naming",
            list(_NAMING_OPTIONS),
            key="chr_naming",
            help=(
                "This changes chromosome identifiers only. Coordinates and "
                "genome assembly are not changed."
            ),
        )
        chr_assembly = _ASSEMBLY_OPTIONS.get(chr_assembly_label)
        chr_naming = _NAMING_OPTIONS[chr_naming_label]
        if chr_naming is not None and chr_assembly is None:
            st.warning(_ASSEMBLY_REQUIRED_MESSAGE)

        # --- Advanced options (collapsed by default) -----------------
        # The strand checkbox applies to all operation modes and a nonzero
        # min_overlap changes semantics, so an active non-default state is
        # reflected in the group label and stays visible even while the
        # expander is collapsed.
        advanced_label = "Advanced options"
        if st.session_state.get("use_strand") is True:
            advanced_label += " (strand required)"
        with st.expander(advanced_label):
            use_strand = st.checkbox(
                "Require query and annotation to have the same explicit strand",
                key="use_strand",
                help=(
                    "Only pairs where both rows carry an explicit strand "
                    "(+ or -) and the strands are equal qualify. Missing "
                    "strand values do not act as wildcards. Applies to all "
                    "operation modes."
                ),
            )

            if mode == "overlap":
                min_overlap = st.slider(
                    "Minimum overlap fraction",
                    0.0,
                    1.0,
                    0.0,
                    0.1,
                    key="min_overlap",
                    help=(
                        "Minimum fraction of each query interval that must "
                        "overlap a single annotation interval. 0 = any "
                        "positive overlap. Applies to the overlap mode only."
                    ),
                )
            else:
                min_overlap = None

        # --- Feature filter (GFF/GTF) -------------------------------
        st.subheader("Feature filter")
        feature_types = st.multiselect(
            "Filter by feature type",
            _FEATURE_TYPE_OPTIONS,
            default=["gene"],
            key="feature_types",
            help=(
                "Only include these feature types from the annotation file "
                "(GFF/GTF). Leave empty to include all features."
            ),
        )
        if not feature_types:
            st.caption("No feature types selected — all features will be included.")

    return {
        "engine": engine_key,
        "coord_system": coord_system,
        "annot_system": annot_system,
        "chr_assembly": chr_assembly,
        "chr_naming": chr_naming,
        "mode": mode,
        "join": join,
        "use_strand": use_strand,
        "min_overlap": min_overlap,
        "feature_types": list(feature_types),
    }


# ---------------------------------------------------------------------------
# Main column: upload, run, results
# ---------------------------------------------------------------------------

def render_upload_section(cfg: dict):
    st.header("1. Upload")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Query coordinates**")
        coord_file = st.file_uploader(
            "Choose coordinate file",
            type=["bed", "txt", "tsv", "csv", "vcf"],
            key="coord_file",
        )
        if coord_file:
            st.caption(f"{coord_file.name} · {format_file_size(coord_file.size)}")

    with col2:
        st.markdown("**Annotation features**")
        annot_file = st.file_uploader(
            "Choose annotation file",
            type=["gtf", "gff", "gff3", "bed", "txt", "tsv", "csv"],
            key="annot_file",
        )
        if annot_file:
            st.caption(f"{annot_file.name} · {format_file_size(annot_file.size)}")

    # Parse (or reuse the cached parse) — independent of the engine.
    coord_info = _get_parsed_frame(
        "coord_parse", coord_file,
        _declared_coordinate_system(cfg["coord_system"]),
        invalidate_mapping=True,
    )
    annot_info = _get_parsed_frame(
        "annot_parse", annot_file,
        _declared_coordinate_system(cfg["annot_system"]),
        role="annot",
    )

    # Previews (backend-independent by construction).
    if coord_info or annot_info:
        pv1, pv2 = st.columns(2)

        with pv1:
            st.markdown("**Coordinate preview**")
            if coord_info:
                st.dataframe(coord_info["df"].head(10), height=220)
                if coord_info["format"] == "custom":
                    st.caption("Custom format — map the columns below before running.")
                else:
                    st.caption(
                        f"Format: {coord_info['format'].upper()} | "
                        f"Rows: {len(coord_info['df']):,} (canonical 0-based half-open)"
                    )
            else:
                st.info("Waiting for upload...")

        with pv2:
            st.markdown("**Annotation preview**")
            if annot_info:
                st.dataframe(annot_info["df"].head(10), height=220)
                if annot_info["format"] == "custom":
                    annot_system = (
                        _declared_coordinate_system(cfg["annot_system"])
                        or "0-based"
                    )
                    st.caption(
                        "Custom format — the file must contain `chr`/`start`/`end` "
                        f"columns; the declared coordinate system ({annot_system}) "
                        "is applied to it."
                    )
                else:
                    st.caption(
                        f"Format: {annot_info['format'].upper()} | "
                        f"Rows: {len(annot_info['df']):,} (canonical 0-based half-open)"
                    )
            else:
                st.info("Waiting for upload...")

    # Resolve the canonical query frame first: this also clears a mapping
    # that became stale because the declared coordinate system changed.
    coord_df = _resolve_coord_frame(coord_info, cfg)

    # Column mapping for custom coordinate files (shown until a mapping
    # has been applied; a stale mapping is cleared in _resolve_coord_frame).
    if (
        coord_info
        and coord_info["format"] == "custom"
        and not st.session_state.get("coord_mapping")
    ):
        with st.expander("Map coordinate columns", expanded=True):
            _render_coord_mapping_ui(coord_info, cfg)

    return coord_info, annot_info, coord_df


def _render_coord_mapping_ui(coord_info, cfg):
    coord_df = coord_info["df"]
    suggestions = CustomParser.suggest_columns(coord_df)
    columns = coord_df.columns.tolist()

    map_col1, map_col2, map_col3 = st.columns(3)

    with map_col1:
        chr_col = st.selectbox(
            "Chromosome column",
            columns,
            index=columns.index(suggestions["chr"]) if suggestions["chr"] in columns else 0,
            key="map_chr_col",
        )
    with map_col2:
        start_col = st.selectbox(
            "Start position",
            columns,
            index=columns.index(suggestions["start"]) if suggestions["start"] in columns else min(1, len(columns) - 1),
            key="map_start_col",
        )
    with map_col3:
        end_options = ["None (single positions)"] + columns
        end_index = 0
        if suggestions["end"] in columns:
            end_index = columns.index(suggestions["end"]) + 1
        end_col = st.selectbox(
            "End position",
            end_options,
            index=end_index,
            key="map_end_col",
        )

    if st.button("Apply column mapping", key="apply_mapping"):
        end_col_name = None if end_col == "None (single positions)" else end_col
        system = _declared_coordinate_system(cfg["coord_system"]) or "0-based"
        try:
            # Every unmapped user column is preserved as metadata (in
            # original input order), with collision safety enforced in
            # CustomParser.map_columns.
            unmapped_cols = [
                c for c in columns if c not in (chr_col, start_col, end_col_name)
            ]
            mapped_df = CustomParser.map_columns(
                coord_df, chr_col, start_col, end_col_name, unmapped_cols
            )
            # A single position is exactly one base in the declared
            # source system: a 1-based position P is the 1-base interval
            # [P, P] (canonical [P-1, P) after the shift below); a
            # 0-based position P is the half-open 1-base interval
            # [P, P+1). Building end = start + 1 first would make a
            # 1-based position 2 bp.
            if end_col_name is None:
                # The raw custom frame is read as text; numeric
                # arithmetic needs an actual numeric start (non-numeric
                # positions fail here with the same clear error that
                # normalize_intervals would produce).
                start_numeric = pd.to_numeric(
                    mapped_df["start"], errors="coerce"
                )
                if system == "1-based":
                    mapped_df["end"] = start_numeric
                else:
                    mapped_df["end"] = start_numeric + 1
            mapped_df = normalize_intervals(mapped_df, coordinate_system=system)
        except (CanonicalSchemaError, ValueError, KeyError) as exc:
            st.error(f"Column mapping failed: {exc}")
        else:
            st.session_state["coord_mapping"] = (chr_col, start_col, end_col_name, system)
            st.session_state["coord_mapped_df"] = mapped_df
            st.success(
                "Column mapping applied — the canonical preview below reflects "
                "the mapped table."
            )
            st.dataframe(mapped_df.head(10), height=220)


def run_annotation(cfg: dict, coord_df, annot_info, signature):
    """Execute the annotation workflow for the current configuration."""
    if coord_df is None:
        st.error(
            "No usable query table: upload a coordinate file, and if it is in "
            "a custom format, apply the column mapping first."
        )
        return
    if annot_info is None:
        st.error("Upload an annotation file first.")
        return
    annot_df = annot_info["df"]
    annot_format = annot_info["format"]

    # --- Validation (invalid user configuration, not a backend error) ---
    is_valid, error = DataValidator.validate_coordinates(coord_df)
    if not is_valid:
        st.error(f"Query coordinate file is not valid: {error}")
        return
    is_valid, error = DataValidator.validate_coordinates(annot_df)
    if not is_valid:
        st.error(f"Annotation file is not valid: {error}")
        return

    # --- Feature filter (GFF/GTF only) ---
    if (
        annot_format in ("gff", "gtf")
        and cfg["feature_types"]
        and "feature" in annot_df.columns
    ):
        original_count = len(annot_df)
        annot_df = annot_df[
            annot_df["feature"].isin(_expand_feature_types(cfg["feature_types"]))
        ].copy()
        if len(annot_df) == 0:
            st.warning(
                f"No annotations match the selected feature types "
                f"(filtered {original_count:,} features). Adjust the feature "
                f"filter and run again."
            )
            return
        st.caption(
            f"Using {len(annot_df):,} of {original_count:,} annotation "
            f"features (feature filter)."
        )

    # --- Chromosome naming ---
    # "Keep original names" is a true no-op (no assembly needed). Any
    # normalization requires an explicitly selected assembly; nothing is
    # inferred from the files.
    chr_summary = None
    contig_renames = {}
    if cfg["chr_naming"] is not None:
        if cfg["chr_assembly"] is None:
            st.error(_ASSEMBLY_REQUIRED_MESSAGE)
            return
        normalized = normalize_input_chromosomes(
            coord_df, annot_df,
            assembly=cfg["chr_assembly"], target=cfg["chr_naming"],
        )
        coord_df, annot_df = normalized.coord_df, normalized.annot_df
        # Renames come from the normalization report, never re-derived.
        contig_renames = dict(normalized.coord_renames)
        chr_summary = {
            "assembly_label": _ASSEMBLY_LABELS[cfg["chr_assembly"]],
            "naming_label": _NAMING_LABELS[cfg["chr_naming"]],
            "coord_report": normalized.coord_report,
            "annot_report": normalized.annot_report,
        }

    # --- No-shared-identifiers warning ---
    # Whatever the conversion outcome, if the two tables share no
    # chromosome identifiers at all, no row can match: say so explicitly
    # instead of silently producing an all-unmatched result.
    if len(coord_df) > 0 and len(annot_df) > 0:
        shared = set(coord_df["chr"].unique()) & set(annot_df["chr"].unique())
        if not shared:
            st.warning(
                "No shared chromosome identifiers remain between query and "
                "annotation data. Select the genome assembly and a "
                "chromosome naming above to normalize names, or check the "
                "names used by each file."
            )

    # --- Engine selection (execution only; explicit failure, no fallback) ---
    try:
        engine = build_engine(
            cfg["engine"],
            mode=cfg["mode"],
            use_strand=cfg["use_strand"],
            min_overlap=_min_overlap_for(cfg),
        )
    except EngineUnavailableError as exc:
        st.error(str(exc))
        return
    except ValueError as exc:
        st.error(f"Invalid option: {exc}")
        return
    label = engine_label(cfg["engine"])

    # --- Execution ---
    try:
        with st.spinner(f"Running {cfg['mode']} annotation with {label}..."):
            raw_result = engine.intersect(coord_df, annot_df, how=cfg["join"])
        # The canonical result contract is the UI/export boundary: both
        # backends must pass the same adapter, so the engine choice can
        # never change the result schema, missing-value representation,
        # or exported content (Task 7 §6, SPEC 6).
        result_df = canonicalize_annotation_result(
            raw_result,
            coord_df,
            annot_df,
            extra_columns=("distance",) if cfg["mode"] == "closest" else (),
        )
    except Exception as exc:
        # Backend execution failure: log the full traceback for developers,
        # show a concise, labeled error to the user (SPEC 9.2).
        logger.exception(
            "%s backend failed during %s annotation (%s join)",
            label, cfg["mode"], cfg["join"],
        )
        st.error(
            f"{label} failed during {cfg['mode']} annotation "
            f"({cfg['join']} join): {exc}"
        )
        return

    # --- Store results with the configuration signature ---
    coord_parse = st.session_state.get("coord_parse")
    vcf_header_lines = (
        coord_parse.get("vcf_header_lines")
        if isinstance(coord_parse, dict)
        else None
    )
    st.session_state.update(
        {
            "result_signature": signature,
            "result_df": result_df,
            "result_coord_df": coord_df,
            "result_engine": label,
            "result_mode": cfg["mode"],
            "result_join": cfg["join"],
            "result_coord_format": _coord_format_of(cfg),
            # Original VCF ## metadata (once per source file), restored
            # verbatim by the annotated VCF export.
            "result_vcf_header_lines": vcf_header_lines,
            # Query chromosome identifiers renamed by normalization
            # (old -> new); reconciles ##contig lines in the VCF export.
            "result_vcf_contig_renames": contig_renames,
            # Chromosome-normalization summary shown with the results
            # (None when names were kept as provided).
            "result_chr_normalization": chr_summary,
        }
    )


def _coord_format_of(cfg: dict):
    """Format of the currently parsed coordinate file (for VCF export)."""
    info = st.session_state.get("coord_parse")
    return info["format"] if isinstance(info, dict) else None


def render_results_section(cfg: dict, coord_identity, annot_identity, coord_format):
    st.header("3. Results")

    signature = _config_signature(cfg, coord_identity, annot_identity, coord_format)
    stored_signature = st.session_state.get("result_signature")

    # State safety: any change to engine/options/inputs invalidates stored
    # results explicitly — a stale result is never displayed as if it
    # belonged to the current configuration.
    if stored_signature is None or stored_signature != signature:
        _clear_results_state()
        st.info(
            "No results yet. Upload both files, configure the operation, "
            "and run the annotation."
        )
        return

    result_df = st.session_state["result_df"]
    coord_df = st.session_state["result_coord_df"]
    engine_name = st.session_state["result_engine"]
    mode = st.session_state["result_mode"]
    coord_format = st.session_state["result_coord_format"]
    vcf_header_lines = st.session_state.get("result_vcf_header_lines")
    vcf_contig_renames = st.session_state.get("result_vcf_contig_renames")

    _render_chromosome_report(st.session_state.get("result_chr_normalization"))

    if result_df.empty:
        how = st.session_state.get("result_join", "left")
        if how == "left":
            st.info(
                "No results to display — the query table contained no "
                "intervals."
            )
        else:
            st.info(
                "No qualifying annotations were found for the selected "
                "operation and options (inner join keeps matched rows "
                "only)."
            )
        return

    # Valid zero-match state: information, NOT an error.
    if not result_df["has_overlap"].any():
        st.info(
            "No qualifying annotations were found for the selected operation "
            "and options."
        )

    _render_summary_metrics(result_df, coord_df, engine_name, mode,
                            st.session_state.get("result_join", "left"))

    # Display filter (cosmetic only; canonical data is never mutated).
    if "has_overlap" in result_df.columns:
        result_filter = st.radio(
            "Show",
            ["All", "Matched only", "Unmatched only"],
            horizontal=True,
            key="result_filter",
        )
        if result_filter == "Matched only":
            display_df = result_df[result_df["has_overlap"] == True]  # noqa: E712
        elif result_filter == "Unmatched only":
            display_df = result_df[result_df["has_overlap"] == False]  # noqa: E712
        else:
            display_df = result_df
        st.caption(f"Showing {len(display_df):,} of {len(result_df):,} rows")
        if display_df.empty:
            # A valid view state, not an error: the stored result is
            # intact and the other views still hold rows.
            st.info(
                f"No {result_filter.split()[0].lower()} rows to display "
                "for the current filter."
            )
    else:
        display_df = result_df

    st.dataframe(display_df, height=400)

    _render_downloads(
        display_df, coord_format, vcf_header_lines, vcf_contig_renames
    )

    if not display_df.empty:
        with st.expander("Charts and gene list"):
            _render_charts_and_gene_list(display_df)


_DETAIL_LIMIT = 20


def _table_summary(label: str, report) -> str:
    """One plain-language line per input table."""
    return (
        f"{label}: {report.resolved_changed_identifiers} names normalized, "
        f"{report.resolved_unchanged_identifiers} already in this naming, "
        f"{report.unresolved_identifiers} not normalized."
    )


def _name_list(counts) -> str:
    items = [f"{name} ({n:,} rows)" for name, n in list(counts.items())[:_DETAIL_LIMIT]]
    extra = len(counts) - _DETAIL_LIMIT
    return ", ".join(items) + (f", and {extra} more" if extra > 0 else "")


def _render_chromosome_report(summary):
    """Show what chromosome normalization did, honestly and briefly."""
    if summary is None:
        st.caption("Chromosome names were kept as provided.")
        return
    tables = (("Query", summary["coord_report"]),
              ("Annotation", summary["annot_report"]))
    st.caption(
        f"Chromosome naming: {summary['naming_label']} \u00b7 Genome "
        f"assembly: {summary['assembly_label']}. Coordinates and genome "
        "assembly are unchanged."
    )
    for label, report in tables:
        st.caption(_table_summary(label, report))
    unresolved = any(r.unresolved_identifiers for _, r in tables)
    merged = any(r.collapses for _, r in tables)
    if unresolved:
        st.warning(
            "Some chromosome names could not be normalized and were left "
            "as provided. See the details below."
        )
    if merged:
        st.info(
            "Some input chromosome names were normalized to the same "
            "output name. See the details below."
        )
    if not (unresolved or merged):
        return
    with st.expander("Chromosome normalization details"):
        for label, report in tables:
            if not (report.unresolved_identifiers or report.collapses):
                continue
            st.markdown(f"**{label}**")
            if report.unknown:
                st.markdown(
                    f"Not recognized in {summary['assembly_label']}: "
                    + _name_list(report.unknown)
                )
            if report.no_alias_for_target:
                st.markdown(
                    "Recognized, but no verified name is available in "
                    f"{summary['naming_label']}: "
                    + _name_list(report.no_alias_for_target)
                )
            for output, sources in list(report.collapses.items())[:_DETAIL_LIMIT]:
                st.markdown(
                    "Multiple input chromosome names were normalized to the "
                    f"same output name: {', '.join(sources)} \u2192 {output}"
                )



def _render_summary_metrics(result_df, coord_df, engine_name, mode, join):
    matched = int(result_df["has_overlap"].sum())
    unmatched = len(result_df) - matched

    # Provenance as compact secondary metadata (not metric typography);
    # the quantitative metrics stay prominent below.
    meta = f"{engine_name} · {mode.title()} · {join.title()} join"
    if mode == "closest":
        meta += (" · distance column included"
                 if "distance" in result_df.columns
                 else " · distance column missing")
    st.caption(meta)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Query rows", f"{len(coord_df):,}")
    m2.metric("Result rows", f"{len(result_df):,}")
    m3.metric(
        "Matched rows",
        f"{matched:,}",
        help="Result rows with an attached annotation (has_overlap = true)",
    )
    m4.metric(
        "Unmatched rows",
        f"{unmatched:,}",
        help="Query rows kept by the left join without a qualifying annotation",
    )


def _render_downloads(
    display_df, coord_format, vcf_header_lines=None, vcf_contig_renames=None
):
    st.subheader("Download results")
    st.caption(
        "Exports the rows currently shown above (use the display filter to "
        "narrow the export)."
    )

    d1, d2, d3, _d4 = st.columns([1, 1, 1, 2])  # trailing spacer keeps the row compact
    with d1:
        st.download_button(
            "CSV",
            data=display_df.to_csv(index=False),
            file_name="annotated_coordinates.csv",
            mime="text/csv",
        )
    with d2:
        st.download_button(
            "TSV",
            data=display_df.to_csv(index=False, sep="\t"),
            file_name="annotated_coordinates.tsv",
            mime="text/tab-separated-values",
        )
    with d3:
        try:
            from io import BytesIO

            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                display_df.to_excel(writer, index=False, sheet_name="Annotations")
            st.download_button(
                "Excel",
                data=buffer.getvalue(),
                file_name="annotated_coordinates.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except ImportError:
            st.caption("Excel export requires openpyxl")

    if coord_format == "vcf":
        st.info(
            "Reconstructed VCF: original record fields (ID/REF/ALT/QUAL/FILTER, "
            "INFO, FORMAT and samples) and the original VCF header "
            "definitions are preserved, and annotations are appended to "
            "INFO as declared ANNOT_* entries. One record per "
            "query-annotation pair. Shown only when the coordinate input is VCF."
        )
        try:
            vcf_data = convert_df_to_vcf(
                display_df,
                original_header_lines=vcf_header_lines,
                contig_renames=vcf_contig_renames,
            )
        except ChromosomeContigCollisionError as exc:
            fields = ", ".join(sorted(exc.conflicts))
            st.error(
                "Annotated VCF export is unavailable. The input chromosome "
                f"names {', '.join(exc.sources)} were normalized to the same "
                f"name ({exc.target}), but their VCF contig metadata "
                f"disagree ({fields}). AnnotateR cannot safely choose "
                "which metadata to keep."
            )
            return
        st.download_button(
            "Annotated VCF",
            data=vcf_data,
            file_name="annotated_variants.vcf",
            mime="application/octet-stream",
            key="download_vcf",
        )


def _find_gene_column(df: pd.DataFrame):
    """Best-effort gene/feature name column in canonical results."""
    possible_gene_cols = [
        "annot_Name", "annot_gene_name", "annot_name",
        "gene_name", "Name",
        "annot_gene_id", "annot_ID", "gene_id", "ID",
        "gene", "Gene", "GENE", "symbol", "Symbol",
    ]
    for col in possible_gene_cols:
        if col in df.columns:
            if col.startswith("annot_"):
                valid = df[col].dropna()
                valid = valid[~valid.astype(str).isin(["-1", ".", "nan", ""])]
                if len(valid) > 0:
                    return col
            else:
                return col
    return None


def _render_charts_and_gene_list(df):
    if df.empty:
        # Plotly cannot build the per-chromosome / per-gene bars from an
        # empty frame; there is nothing to chart or list.
        st.info("No rows to chart for the current filter.")
        return

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        feature_col = next(
            (
                c
                for c in ("annot_feature", "feature", "coord_feature")
                if c in df.columns
            ),
            None,
        )
        if feature_col:
            valid = df[
                ~df[feature_col].astype(str).isin(["-1", ".", "nan"])
            ]
            if len(valid) > 0:
                counts = valid[feature_col].value_counts()
                fig = px.pie(
                    values=counts.values,
                    names=counts.index,
                    title="Feature type distribution",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_traces(textposition="inside", textinfo="percent+label")
                fig.update_layout(showlegend=True, height=350)
                st.plotly_chart(fig)
            else:
                st.info("No feature type data available for the chart.")
        else:
            st.info("No feature type data available for the chart.")

    with chart_col2:
        chr_col = next(
            (
                c
                for c in (
                    "coord_chr", "chr", "chrom",
                    "coord_chrom_1", "coord_chrom_2", "chrom_1", "chrom_2",
                )
                if c in df.columns
            ),
            None,
        )
        if chr_col:
            chr_counts = df[chr_col].value_counts().head(15)
            # Count is encoded by bar length only — a redundant continuous
            # color scale/colorbar would add noise without new information.
            fig = px.bar(
                x=chr_counts.index,
                y=chr_counts.values,
                title="Annotations per chromosome (top 15)",
                labels={"x": "Chromosome", "y": "Count"},
            )
            fig.update_layout(showlegend=False, height=350)
            st.plotly_chart(fig)
        else:
            st.info("No chromosome data available for the chart.")

    # --- Gene list ---
    gene_col = _find_gene_column(df)
    if gene_col is None:
        st.info("No gene/feature name column found in the results.")
        return

    gene_list = [
        g
        for g in df[gene_col].dropna().unique().tolist()
        if str(g) not in ["-1", ".", "nan", ""]
    ]
    if not gene_list:
        st.info("No valid gene names found in the results.")
        return

    gene_col1, gene_col2 = st.columns(2)
    with gene_col1:
        top = df[gene_col].value_counts().head(10)
        # Count is encoded by bar length only (no redundant color scale).
        fig = px.bar(
            x=top.values,
            y=top.index,
            orientation="h",
            title="Top 10 genes (by annotation count)",
            labels={"x": "Count", "y": "Gene/feature"},
        )
        fig.update_layout(
            showlegend=False,
            height=300,
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(fig)

    with gene_col2:
        st.markdown("**Gene list**")
        gene_text = "\n".join(sorted(gene_list))
        gene_csv = ", ".join(sorted(gene_list))
        g1, g2 = st.columns(2)
        with g1:
            st.download_button(
                "Gene list (.txt)",
                data=gene_text,
                file_name="gene_list.txt",
                mime="text/plain",
                key="gene_txt",
            )
        with g2:
            st.download_button(
                "Gene list (comma-separated)",
                data=gene_csv,
                file_name="gene_list.csv",
                mime="text/csv",
                key="gene_csv",
            )
        with st.expander("Copy to clipboard"):
            st.caption("One gene per line:")
            st.code(gene_text, language="text")
            st.caption("Comma-separated:")
            st.code(gene_csv, language="text")
            st.markdown(
                "Paste into [g:Profiler](https://biit.cs.ut.ee/gprofiler), "
                "[Enrichr](https://maayanlab.cloud/Enrichr), "
                "[DAVID](https://davidbioinformatics.nih.gov/tools.jsp), or "
                "[STRING](https://string-db.org)."
            )


# ---------------------------------------------------------------------------
# VCF export (unchanged canonical semantics; kept at module level)
# ---------------------------------------------------------------------------

#: ``coord_*`` metadata columns that map to fixed VCF fields (or the
#: canonical interval keys) rather than to sample columns: every other
#: ``coord_*`` column in a VCF query result is an original sample column.
_VCF_FIXED_COORD_COLUMNS = frozenset({
    "coord_chr", "coord_start", "coord_end", "coord_id", "coord_ref",
    "coord_alt", "coord_qual", "coord_filter", "coord_info",
    "coord_format", "coord_strand",
})

#: ``annot_*`` columns carrying interval/derived values rather than
#: annotation metadata: never serialized into VCF INFO.
_VCF_NONINFO_ANNOT_COLUMNS = frozenset({
    "annot_chr", "annot_start", "annot_end", "has_overlap",
})


def _vcf_field(value) -> str:
    """
    Render a value as a VCF field: canonical missing (``pd.NA``/``NaN``/``None``)
    becomes the VCF MISSING value ``.``; anything else is stringified as-is.
    Prevents ``"<NA>"``/``"nan"`` sentinels from leaking into exports.
    """
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return "."
    return str(value)


def _vcf_qual(value) -> str:
    """
    Render a QUAL value. Missing becomes the VCF MISSING value ``.``.

    The parser stores QUAL as a float (source ``50`` becomes ``50.0``);
    integer-valued numbers are written back without a fractional part so
    an integer source QUAL round-trips verbatim, while genuinely
    fractional values and non-numeric text are written as stored.
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


def _vcf_info_key(annotation_column: str) -> str:
    """
    ANNOT_*-namespaced INFO identifier for an annotation column.

    The namespace is what keeps emitted keys from colliding with original
    VCF INFO IDs; a suffix that is not a valid VCF INFO ID (must match
    ``[A-Za-z_][A-Za-z0-9_]*``) is deterministically prefixed with
    ``x_``.
    """
    suffix = annotation_column[len("annot_"):]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", suffix):
        suffix = f"x_{suffix}"
    return f"ANNOT_{suffix}"


def _escape_vcf_info_value(value: str) -> str:
    """
    Encode an annotation value for VCF INFO. VCF INFO values may not
    contain ``;`` (field separator), ``=`` (key/value separator), or
    whitespace, so the repository's established mapping applies:
    ``;`` -> ``|``, `` `` -> ``_``, ``=`` -> ``:``. Commas are valid in
    String values and pass through. This is a documented lossy encoding:
    re-importing the exported file yields the escaped form, not the
    original value text.
    """
    return value.replace(";", "|").replace(" ", "_").replace("=", ":")


def _info_contains_key(info_text: str, key: str) -> bool:
    """True if an original INFO field already carries ``key`` (as a flag
    or a ``key=value`` token)."""
    for token in info_text.split(";"):
        if token == key or token.startswith(f"{key}="):
            return True
    return False


def _vcf_sample_name(coord_column: str) -> str:
    """
    Original #CHROM header name for a ``coord_*`` sample column.

    Reverses the parser's deterministic collision rename: a sample whose
    name collides with a parser/core column is stored as
    ``sample_<name>`` (e.g. a sample literally named ``start``).
    Pathological sample names that already start with ``sample_`` cannot
    be distinguished from renamed columns; the renamed form wins.
    """
    name = coord_column[len("coord_"):]
    if name.startswith("sample_"):
        name = name[len("sample_"):]
    return name


def _original_header_declarations(original_header_lines) -> dict:
    """
    Original ``##INFO`` declarations from retained header lines,
    mapped by INFO ID (first declaration wins, source order).
    """
    decls = {}
    for line in original_header_lines or []:
        if not isinstance(line, str):
            continue
        m = re.match(r"##INFO=<ID=([A-Za-z0-9_]+)", line)
        if m:
            decls.setdefault(m.group(1), line)
    return decls


# Collision-safe ##contig reconciliation lives in core (SPEC 5.1).
_reconcile_contig_lines = reconcile_contig_lines


def convert_df_to_vcf(
    df: pd.DataFrame, original_header_lines=None, contig_renames=None
) -> str:
    """
    Convert results DataFrame back to VCF format.

    Export fidelity contract (Task C / F8):

    - original record fields the parse/result path retained are exported
      verbatim: ID, REF, ALT, FILTER, the raw INFO field (including
      END), and, when present, the FORMAT column and per-sample columns
      in #CHROM order;
    - annotation metadata is APPENDED to INFO under the ANNOT_*
      namespace; every emitted key is declared by a generated ##INFO
      line (conservative ``Number=.,Type=String``; no unsupported type
      claims) and never overwrites or duplicates an original INFO key;
    - ``original_header_lines`` (the source file's ``##`` metadata,
      retained by the VCF parser and passed once per source file, not
      per result row) is preserved verbatim in stable source order:
      contig/INFO/FORMAT/FILTER definitions and any other original
      metadata. Exactly one ``##fileformat`` line is emitted — the
      source's version when present, never silently upgraded or
      downgraded (``VCFv4.2`` only as the fallback for a source with
      none); duplicate identical lines are emitted once. The exporter
      then adds ``##source=AnnotateR <version>`` and ``##date`` (additions —
      an original ``##source``/``##date`` line is retained, not
      replaced) and the ANNOT_* declarations. Original definitions are
      never re-synthesized: no types or descriptions are invented.
    - ``contig_renames`` (old -> new chromosome identifiers changed by
      chromosome normalization; the result frame and exported CHROM
      values carry the new identifiers): the ID of the matching
      ``##contig`` lines is renamed to the exported identifier, every
      other attribute (length, assembly, md5, ...) is kept. Contigs that
      were not renamed, and files with no renames, keep their lines
      untouched; no ``##contig`` line is ever invented for a source
      that lacked one.
    - ANNOT_* declaration collision policy: if the original header
      already declares an ``ANNOT_*`` INFO ID, the original definition
      stands and no generated duplicate is emitted when it is
      ``Type=String`` (compatible with the exported string values);
      any other declared type (or a missing Type) is a conflict and
      the export fails with an explicit ``ValueError`` naming the ID —
      the original definition is never silently overwritten.
    - one output record per canonical result row: a source variant
      matching N annotations appears N times with different ANNOT_*
      payloads and identical original fields;
    - unmatched rows keep the original record fields and carry no
      ANNOT_* entries (INFO is the original INFO, or ``.`` when that was
      missing too). POS = coord_start + 1 (canonical 0-based start ->
      1-based VCF POS); REF/ALT/END are never rewritten from annotation
      coordinates.
    """
    original = _reconcile_contig_lines(
        [
            line for line in (original_header_lines or [])
            if isinstance(line, str) and line.startswith("##")
        ],
        contig_renames,
    )

    # Exactly one ##fileformat: the source's version when present, so
    # the export is never silently upgraded or downgraded; VCFv4.2 is
    # only the fallback for a source without a fileformat line.
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
            # emitted above; any further (already invalid) declaration
            # is dropped rather than emitted twice.
            continue
        if line in seen:
            # Duplicate identical metadata lines are emitted once.
            continue
        seen.add(line)
        lines.append(line)
    # AnnotateR provenance: additions, never replacements — an original
    # ##source/##date line (if any) was already retained above.
    lines.append(f"##source=AnnotateR {Settings.VERSION}")
    lines.append(f"##date={pd.Timestamp.now().strftime('%Y%m%d')}")

    # Map internal columns to VCF standard columns
    # Canonical start is 0-based and equals POS - 1, so POS = coord_start + 1.
    # (Using coord_end would be wrong for multi-base variants.)

    res = df.copy()

    # Ensure required columns exist, fill with '.' if missing
    required_map = {
        "coord_chr": "CHROM",
        "coord_start": "POS",
        "coord_id": "ID",
        "coord_ref": "REF",
        "coord_alt": "ALT",
        "coord_qual": "QUAL",
        "coord_filter": "FILTER",
    }

    # Check which columns we actually have
    available_map = {}
    for int_col, vcf_col in required_map.items():
        if int_col in df.columns:
            available_map[int_col] = vcf_col
        # Special handling if coord_ prefix is missing
        elif int_col.replace("coord_", "") in df.columns:
            available_map[int_col.replace("coord_", "")] = vcf_col

    if not available_map:
        return "##Error: Could not reconstruct VCF. Missing coordinate columns."

    # Identify annotation columns for INFO field
    annot_cols = [
        c
        for c in df.columns
        if c.startswith("annot_") and c not in _VCF_NONINFO_ANNOT_COLUMNS
    ]

    # Declare every ANNOT_* key the exporter can emit, in frame column
    # order (deterministic; de-duplicated after ID sanitization).
    info_keys: dict = {}
    for col in annot_cols:
        key = _vcf_info_key(col)
        if key not in info_keys:
            info_keys[key] = col
    # ANNOT_* declarations, honoring the collision policy: a pre-existing
    # original declaration of the same ID stands — a String-typed one is
    # kept as-is (no generated duplicate); any other type is refused
    # with an explicit error rather than silently overwritten.
    original_decls = _original_header_declarations(original)
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
        raise ValueError(
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
        if c.startswith("coord_") and c not in _VCF_FIXED_COORD_COLUMNS
    ]
    chrom_header = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if has_format:
        chrom_header.append("FORMAT")
    chrom_header.extend(_vcf_sample_name(c) for c in sample_columns)
    lines.append("\t".join(chrom_header))

    vcf_rows = []

    for _, row in res.iterrows():
        # Build standard fields
        fields = []
        fields.append(_vcf_field(row.get("coord_chr", row.get("chr", "."))))

        # POS: reconstruct the 1-based VCF position from the canonical start
        # (POS = coord_start + 1)
        pos_value = row.get("coord_start", row.get("start", "."))
        try:
            fields.append(str(int(pos_value) + 1))
        except (TypeError, ValueError):
            fields.append(".")

        # ID/REF/ALT: canonical missing must export as '.', never '<NA>'.
        fields.append(_vcf_field(row.get("coord_id", row.get("id", "."))))
        fields.append(_vcf_field(row.get("coord_ref", row.get("ref", "."))))
        fields.append(_vcf_field(row.get("coord_alt", row.get("alt", "."))))
        # QUAL: canonical missing -> '.', integer-valued floats written
        # back as integers (see _vcf_qual); FILTER: canonical missing
        # (e.g. VCF FILTER "." = filters not applied) exports as '.',
        # never as a rendered "<NA>"/"nan" token.
        fields.append(_vcf_qual(row.get("coord_qual", row.get("qual", "."))))
        fields.append(_vcf_field(row.get("coord_filter", row.get("filter", "."))))

        # Build INFO field: the original field is preserved VERBATIM
        # (including END for symbolic variants); ANNOT_* entries are
        # appended, never replacing or duplicating original keys.
        original_info = _vcf_field(row.get("coord_info", pd.NA))
        info_parts = [original_info] if original_info != "." else []
        emitted_keys = set()
        for col in annot_cols:
            key = _vcf_info_key(col)
            if key in emitted_keys:
                # Two columns sanitizing to the same INFO ID: the first
                # in frame order wins, deterministically.
                continue
            if _info_contains_key(original_info, key):
                # The source INFO already carries this key: the original
                # value wins and is never silently overwritten.
                continue
            raw_val = row[col]
            # Canonical missing (unmatched rows after canonicalization)
            # must not leak into INFO as 'Key=<NA>'.
            if pd.api.types.is_scalar(raw_val) and pd.isna(raw_val):
                continue
            val = str(raw_val)
            if val and val not in [".", "nan", "-1", "None", "<NA>"]:
                info_parts.append(f"{key}={_escape_vcf_info_value(val)}")
                emitted_keys.add(key)

        fields.append(";".join(info_parts) if info_parts else ".")

        # Original FORMAT and sample columns, preserved verbatim (VCF '.'
        # is already canonical missing and renders back to '.').
        if has_format:
            fields.append(_vcf_field(row.get("coord_format", pd.NA)))
        for c in sample_columns:
            fields.append(_vcf_field(row[c]))

        vcf_rows.append("\t".join(fields))

    return "\n".join(lines + vcf_rows)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

def main():
    st.markdown(_TYPOGRAPHY_CSS, unsafe_allow_html=True)
    st.title(Settings.APP_NAME)
    st.caption(
        "Annotate genomic coordinates against a feature set. Bedtools and "
        "Polars-Bio are interchangeable execution backends: the same input "
        "and options produce the same canonical result."
    )

    cfg = render_sidebar()

    coord_info, annot_info, coord_df = render_upload_section(cfg)
    # Re-resolve the canonical query frame for the run section: the column
    # mapping click handler in the upload section may have stored a fresh
    # mapped frame during this very run, and the Run button must reflect
    # that without waiting for another rerun.
    coord_df = _resolve_coord_frame(coord_info, cfg)
    coord_format = coord_info["format"] if coord_info else None
    signature = _config_signature(
        cfg,
        coord_info["identity"] if coord_info else None,
        annot_info["identity"] if annot_info else None,
        coord_format,
    )

    st.header("2. Run annotation")
    # The primary action is enabled only when both required inputs are
    # actually usable: both files uploaded, and for custom-format query
    # files, the explicit column mapping applied. Existing validation in
    # run_annotation() is unchanged and still runs afterwards.
    run_ready = coord_df is not None and annot_info is not None
    if st.button(
        "Run annotation",
        type="primary",
        key="run_button",
        disabled=not run_ready,
        help=(
            "Enabled once both files are uploaded and, for custom-format "
            "query files, the column mapping is applied."
        ),
    ):
        run_annotation(cfg, coord_df, annot_info, signature)
    if not run_ready:
        if (
            coord_df is None
            and coord_info is not None
            and coord_info["format"] == "custom"
            and annot_info is not None
        ):
            # Both files are uploaded; the missing piece is the explicit
            # column mapping for the custom-format query file.
            st.caption(
                "Apply the column mapping for the custom coordinate file "
                "to enable the annotation run."
            )
        else:
            st.caption(
                "Upload both a query file and an annotation file to enable "
                "the annotation run."
            )

    render_results_section(cfg, coord_info["identity"] if coord_info else None,
                           annot_info["identity"] if annot_info else None, coord_format)

    st.divider()
    st.markdown(
        "<div style='text-align:center;color:#666;'>"
        "Developed by <strong>Jyotirmoy Das, Ph.D.</strong> & "
        "<strong>Massimiliano Volpe, Ph.D.</strong><br/>"
        "Contact: "
        "<a href='mailto:jyotirmoy.das@liu.se'>jyotirmoy.das@liu.se</a> | "
        "<a href='mailto:massimiliano.volpe@scilifelab.se'>massimiliano.volpe@scilifelab.se</a><br/>"
        f"Version {Settings.VERSION} | License: BSD-3-Clause | "
        "Powered by Streamlit, with Bedtools and Polars-Bio backends"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()