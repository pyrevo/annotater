"""FastAPI backend application for AnnotateR.

Integrates with the verified core engines (Polars-Bio, Bedtools), format parsers,
and coordinate normalizers, serving REST endpoints for the modern React frontend.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from streamlit_app.api_sessions import (
    SECURE_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    Session,
    SessionStore,
    anonymous_session,
    open_private_storage,
)

from streamlit_app.config import Settings
from streamlit_app.core import (
    CanonicalSchemaError,
    CustomParser,
    FormatDetector,
    VCFExportError,
    build_annotated_vcf,
    coordinate_system_for,
    extension_authoritative_for,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.chrom_registry import (
    assembly_options,
    find_assembly,
    load_catalog,
)
from streamlit_app.core.engine_registry import (
    DEFAULT_ENGINE,
    ENGINE_DESCRIPTIONS,
    ENGINE_LABELS,
    ENGINE_OPTIONS,
    engine_available,
    unavailable_message,
)
from streamlit_app.core.execution import (
    AnnotationError,
    AnnotationExecutionError,
    AnnotationRequest,
    execute_annotation as execute_annotation_core,
)
from streamlit_app.core.vcf_contigs import ChromosomeContigCollisionError
from streamlit_app.utils import get_example_data_path

_logger = logging.getLogger(__name__)

app = FastAPI(
    title="AnnotateR API",
    version=Settings.VERSION,
    description="High-performance genomic coordinate annotation and interval overlap analysis API",
)


def _cors_allow_origins() -> List[str]:
    """Cross-origin origins allowed to call this API (comma-separated env).

    The SPA is served from the same origin in production and through the Vite
    proxy in development, so the default is an empty list: no cross-origin
    request is allowed and, in particular, no request Origin is ever
    reflected back (review finding F8). Set ``ANNOTATER_CORS_ORIGINS``
    (comma-separated) only for deployments that genuinely need cross-origin
    access; listed origins are the only ones that receive CORS headers.

    A bare ``*`` entry is rejected (review finding N6): with
    ``allow_credentials=True`` a wildcard allowlist makes the middleware
    reflect the request Origin of every site, which credentialed-CORSes the
    whole internet. List concrete origins instead.
    """
    raw = os.environ.get("ANNOTATER_CORS_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    rejected = [origin for origin in origins if origin == "*"]
    if rejected:
        _logger.warning(
            "ANNOTATER_CORS_ORIGINS contains a bare wildcard '*', which is "
            "rejected: with credentialed CORS it would reflect every "
            "request Origin. List concrete origins instead."
        )
    return [origin for origin in origins if origin != "*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Per-session request state (replaces the previous process-global cache)
# ---------------------------------------------------------------------------
#: Server-side, bounded, thread-safe store of per-session state. Each browser
#: receives its own opaque token (HttpOnly cookie); no request can reach
#: another session's state. See streamlit_app/api_sessions for the model and
#: the single-worker deployment constraint.
store = SessionStore()
_SESSION_TTL_SECONDS = int(store.ttl_seconds)


def _cookie_is_secure(request: Request) -> bool:
    """True when the request reached us over HTTPS (directly or via proxy)."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded.split(",")[0].strip().lower() == "https":
        return True
    return request.url.scheme == "https"


def _session_cookie_name(request: Request) -> str:
    """The session cookie name honoured on this request's transport.

    Over HTTPS only the ``__Host-`` prefixed cookie is read (and issued):
    browsers scope it to the exact host, require Secure + Path=/ and no
    Domain attribute, so a token planted under a sibling subdomain cannot be
    presented to this host (review finding N1). Over plain HTTP — local
    development only — the unprefixed name is used, because browsers reject
    Secure cookies on cleartext connections.
    """
    if _cookie_is_secure(request):
        return SECURE_SESSION_COOKIE_NAME
    return SESSION_COOKIE_NAME


def get_session(request: Request) -> Session:
    """Resolve the session owned by this request's cookie.

    The session is keyed only by the server-issued token in the transport's
    cookie name; no endpoint accepts a session identifier as input, so a
    request can never address another user's state, and a cookie planted
    under the other transport's name (e.g. an unprefixed cookie presented
    over HTTPS) is ignored rather than honoured (review finding N1).

    This never allocates a stored session. A request with no valid cookie is
    served by a throwaway, never-stored session; capacity is consumed only
    when an endpoint actually stores state via :func:`_materialize_session`
    (review findings F7, N4).
    """
    existing = getattr(request.state, "session", None)
    if existing is not None:
        return existing
    session = store.get(request.cookies.get(_session_cookie_name(request)))
    if session is None:
        session = anonymous_session()
    request.state.session = session
    return session


def _materialize_session(request: Request, session: Session) -> Session:
    """Upgrade a throwaway session into a stored one, on first state write.

    Session capacity is consumed only by requests that actually store state
    (review finding N4): an anonymous request that fails validation — or
    that only reads — never allocates a slot in the bounded store, so
    anonymous traffic cannot evict a real user's state. Call this
    immediately before the first ``session.data[...]`` write and use the
    returned session for the write; the response middleware attaches the
    cookie.
    """
    if session.token:
        return session
    stored = store.create()
    request.state.session = stored
    # The middleware below attaches the cookie once the response exists.
    request.state.new_session_token = stored.token
    return stored


@app.middleware("http")
async def _issue_session_cookie(request: Request, call_next):
    """Attach the session cookie to responses that created a new session."""
    response = await call_next(request)
    token = getattr(request.state, "new_session_token", None)
    if token:
        response.set_cookie(
            key=_session_cookie_name(request),
            value=token,
            max_age=_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=_cookie_is_secure(request),
            path="/",
        )
    return response


def _clean_df_for_json(df: pd.DataFrame, max_rows: int = 500) -> List[Dict[str, Any]]:
    """Convert dataframe to JSON-safe dictionary, sanitizing NaNs and infinities."""
    subset = df.head(max_rows).copy()
    subset = subset.replace({float("nan"): None, float("inf"): None, float("-inf"): None})
    return subset.to_dict(orient="records")


#: Hard ceiling for ``/api/results/data`` page size (review finding F6): a
#: client can no longer request the entire result frame in one JSON response.
MAX_PAGE_SIZE = 10_000


#: Placeholder tokens some writers emit where no name exists (for example the
#: ``-1`` a BED interval without a name receives). They are never reported as
#: genes by the gene-list endpoint.
_GENE_PLACEHOLDERS = {"-1", ".", "nan", ""}


def _find_gene_column(df: pd.DataFrame) -> Optional[str]:
    """Best-effort gene/feature name column in a canonical result frame.

    Ported from the original Streamlit app: annotation-derived columns are
    only returned when they actually contain non-placeholder values, so a
    BED result without names does not surface a column full of ``-1``.
    """
    possible_gene_cols = [
        "annot_Name", "annot_gene_name", "annot_name",
        "gene_name", "Name",
        "annot_gene_id", "annot_ID", "gene_id", "ID",
        "gene", "Gene", "GENE", "symbol", "Symbol",
    ]
    for col in possible_gene_cols:
        if col not in df.columns:
            continue
        if col.startswith("annot_"):
            valid = df[col].dropna()
            valid = valid[~valid.astype(str).isin(_GENE_PLACEHOLDERS)]
            if len(valid) > 0:
                return col
        else:
            return col
    return None


# ---------------------------------------------------------------------------
# API Routes
#
# VCF export is the shared, framework-independent writer in
# streamlit_app.core.vcf_export (``build_annotated_vcf``); this module keeps
# no second implementation.
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, str]:
    """Lightweight liveness probe for the container and any orchestrator.

    Deliberately does no filesystem or engine work (unlike ``/api/meta``,
    which loads the assembly catalog and probes the engines): it reports only
    that the process is up and serving. The image HEALTHCHECK, the compose
    healthcheck and the deployment readiness probe use this endpoint.
    """
    return {"status": "ok", "version": Settings.VERSION}


@app.get("/api/meta")
def get_metadata():
    """Returns application metadata, available engines, and operation presets."""
    engines = []
    active_default = None
    for key, label in ENGINE_OPTIONS:
        avail = engine_available(key)
        if avail and active_default is None:
            active_default = key
        engines.append({
            "key": key,
            "label": label,
            "available": avail,
            "description": ENGINE_DESCRIPTIONS.get(key, ""),
            "unavailable_message": unavailable_message(key) if not avail else None,
        })

    catalog = load_catalog()
    assemblies = []
    for info in catalog:
        assemblies.append({
            "id": info.canonical_id,
            "display_label": info.display_label,
            "ucsc_db": info.ucsc_db,
            "organism": info.organism,
            "scientific_name": info.scientific_name,
        })

    return {
        "app_name": Settings.APP_NAME,
        "version": Settings.VERSION,
        "default_engine": active_default or DEFAULT_ENGINE,
        "engines": engines,
        "modes": [
            {"key": k, "label": k.title(), "description": v["description"]}
            for k, v in Settings.ANNOTATION_MODES.items()
        ],
        "feature_types": ["gene", "transcript", "exon", "CDS", "5' UTR", "3' UTR", "start_codon", "stop_codon"],
        "coord_systems": ["Auto-detect", "0-based (BED)", "1-based (GFF/GTF/VCF)"],
        "naming_options": [
            {"key": None, "label": "Keep original names"},
            {"key": "ensembl", "label": "Ensembl names"},
            {"key": "ucsc", "label": "UCSC names"},
            {"key": "refseq", "label": "NCBI RefSeq accessions"},
            {"key": "genbank", "label": "GenBank accessions"},
            {"key": "assembly", "label": "Assembly names"},
        ],
        "assemblies": assemblies,
    }


@app.get("/api/sample-datasets")
def list_sample_datasets():
    """Lists available pre-bundled sample datasets."""
    return [
        {
            "id": "gene_overlap",
            "name": "Gene Overlap Analysis",
            "query_file": "example_coordinates.bed",
            "annot_file": "example_annotations.gff3",
            "description": "Exemplary BED query intervals matched against Ensembl GFF3 gene models.",
            "mode": "overlap",
        },
        {
            "id": "closest_variants",
            "name": "Closest Variants Proximity",
            "query_file": "example_closest_variants.vcf",
            "annot_file": "example_closest_annotations.gff3",
            "description": "High-throughput VCF variation dataset paired with nearest gene proximity search.",
            "mode": "closest",
        },
        {
            "id": "stranded_features",
            "name": "Strand-Specific Features",
            "query_file": "example_strand_coordinates.bed",
            "annot_file": "example_strand_annotations.gff3",
            "description": "Strand-aware genomic intervals filtering for antisense/sense overlaps.",
            "mode": "overlap",
        },
    ]


@app.post("/api/load-sample")
def load_sample(
    request: Request,
    sample_id: str = Form(...),
    session: Session = Depends(get_session),
):
    """Loads a pre-bundled sample dataset into the active working state."""
    samples = {
        "gene_overlap": ("example_coordinates.bed", "example_annotations.gff3"),
        "closest_variants": ("example_closest_variants.vcf", "example_closest_annotations.gff3"),
        "stranded_features": ("example_strand_coordinates.bed", "example_strand_annotations.gff3"),
    }
    if sample_id not in samples:
        raise HTTPException(status_code=404, detail="Sample dataset not found")

    q_name, a_name = samples[sample_id]
    q_path = get_example_data_path(q_name)
    a_path = get_example_data_path(a_name)

    # Parse query
    q_fmt = FormatDetector.detect(str(q_path))
    q_df = parse_and_normalize(str(q_path), fmt=q_fmt)

    # Parse annotation
    a_fmt = FormatDetector.detect(str(a_path))
    a_df = parse_and_normalize(str(a_path), fmt=a_fmt)

    # First state write: consume a session slot (anonymous requests that
    # never stored state did not, review finding N4).
    session = _materialize_session(request, session)
    # Store in this session only
    session.data["query"] = {
        "filename": q_name,
        "format": q_fmt,
        "df": q_df,
        "rows": len(q_df),
        "columns": list(q_df.columns),
        "vcf_header_lines": q_df.attrs.get("vcf_header_lines"),
    }
    session.data["annot"] = {
        "filename": a_name,
        "format": a_fmt,
        "df": a_df,
        "rows": len(a_df),
        "columns": list(a_df.columns),
    }

    return {
        "status": "success",
        "query": {
            "filename": q_name,
            "format": q_fmt,
            "total_rows": len(q_df),
            "columns": list(q_df.columns),
            "preview": _clean_df_for_json(q_df, 50),
        },
        "annot": {
            "filename": a_name,
            "format": a_fmt,
            "total_rows": len(a_df),
            "columns": list(a_df.columns),
            "preview": _clean_df_for_json(a_df, 50),
        },
    }


@app.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    role: str = Form(...),  # 'query' or 'annot'
    coord_system: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """Uploads and parses a genomic interval file."""
    if role not in ("query", "annot"):
        raise HTTPException(status_code=400, detail="Role must be 'query' or 'annot'")

    # The client filename is never used as a path component: the file is
    # stored under a server-generated name inside a private temp directory,
    # preserving only a validated extension (see api_sessions.safe_extension).
    temp_dir = Path(tempfile.mkdtemp(prefix="annotater-upload-"))
    fd, temp_path = open_private_storage(temp_dir, file.filename)
    try:
        max_bytes = Settings.get_max_file_size_bytes()
        total = 0
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds the {Settings.MAX_FILE_SIZE_MB} MB limit",
                    )
                handle.write(chunk)

        fmt = FormatDetector.detect(str(temp_path))
        declared = None
        if coord_system and "0-based" in coord_system:
            declared = "0-based"
        elif coord_system and "1-based" in coord_system:
            declared = "1-based"

        if fmt == "custom":
            df = CustomParser.parse(str(temp_path))
            # A custom coordinate file always requires an explicit column
            # mapping: the declared coordinate system cannot be inferred from
            # the file (Streamlit behaves the same way). A custom annotation
            # is normalized in place when it already exposes the canonical
            # columns.
            needs_mapping = role == "query" or not all(
                c in df.columns for c in ("chr", "start", "end")
            )
            if not needs_mapping and role == "annot":
                df = normalize_intervals(df, coordinate_system=declared or "0-based")
        else:
            df = parse_and_normalize(str(temp_path), fmt=fmt, declared_system=declared)
            needs_mapping = False

        # First state write: consume a session slot (a failed upload did
        # not, review finding N4).
        session = _materialize_session(request, session)
        session.data[role] = {
            "filename": file.filename,
            "format": fmt,
            "df": df,
            "rows": len(df),
            "columns": list(df.columns),
            "needs_mapping": needs_mapping,
            "vcf_header_lines": df.attrs.get("vcf_header_lines"),
        }

        return {
            "status": "success",
            "role": role,
            "filename": file.filename,
            "format": fmt,
            "total_rows": len(df),
            "columns": list(df.columns),
            "needs_mapping": needs_mapping,
            "preview": _clean_df_for_json(df, 50),
        }
    except HTTPException:
        raise
    except Exception as exc:
        # User-input failures produce a clear, bounded error; server-side
        # paths are scrubbed so they are never echoed to the client.
        detail = str(exc).replace(str(temp_path), "the uploaded file")
        detail = detail.replace(str(temp_dir), "the uploaded file")
        raise HTTPException(status_code=400, detail=detail)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class DatasetClearRequest(BaseModel):
    role: str


@app.post("/api/dataset/clear")
def clear_dataset(req: DatasetClearRequest, session: Session = Depends(get_session)):
    """Discards one role's stored dataset and any result derived from it.

    The declared coordinate system is baked into the parsed table at upload
    time (for known formats) or at mapping time (for custom tables); changing
    the declaration afterwards must invalidate the stored table, not be
    silently ignored (review finding N2). The React frontend calls this when
    the user changes the coordinate-system selector of an already-loaded
    side, which forces a re-upload under the new declaration.

    This is a state *removal*: it never allocates a session, so an anonymous
    request that has nothing stored clears nothing (finding N4).
    """
    if req.role not in ("query", "annot"):
        raise HTTPException(status_code=400, detail="Role must be 'query' or 'annot'")
    was_loaded = req.role in session.data
    session.data.pop(req.role, None)
    # A stored result is always derived from the current datasets, so it is
    # stale the moment one of them is discarded (finding F5).
    session.data.pop("result", None)
    return {"status": "success", "cleared": req.role, "was_loaded": was_loaded}


class ColumnMappingRequest(BaseModel):
    chr_col: str
    start_col: str
    # ``None`` marks a single-position file: each row becomes a one-base
    # interval in the declared coordinate system (mirrors the Streamlit
    # "None (single positions)" choice).
    end_col: Optional[str] = None
    strand_col: Optional[str] = None
    coord_system: str = "0-based"


def _declared_coordinate_system(option: Optional[str]) -> str:
    """UI coordinate-system selector -> explicit system.

    Only an explicit ``1-based`` declaration selects 1-based; everything else
    (including ``Auto-detect``) defaults to ``0-based``, exactly as the
    Streamlit app resolves it for custom files.
    """
    if option and option.startswith("1-based"):
        return "1-based"
    return "0-based"


@app.post("/api/apply-mapping")
def apply_mapping(req: ColumnMappingRequest, session: Session = Depends(get_session)):
    """Applies custom column mappings to a delimited coordinate file.

    Uses the same core building blocks as the Streamlit app
    (``CustomParser.map_columns`` + ``normalize_intervals``): chromosome,
    start, end (or single position) and optional strand are selected from the
    user's columns; every other column is preserved as metadata.
    """
    if "query" not in session.data:
        raise HTTPException(status_code=400, detail="No query dataset loaded")

    raw_df = session.data["query"]["df"]
    columns = list(raw_df.columns)
    end_col = req.end_col or None
    strand_col = req.strand_col or None

    requested = [("chr_col", req.chr_col), ("start_col", req.start_col)]
    if end_col is not None:
        requested.append(("end_col", end_col))
    if strand_col is not None:
        requested.append(("strand_col", strand_col))
    for field_name, column in requested:
        if column not in columns:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} {column!r} is not a column of the query file",
            )

    system = _declared_coordinate_system(req.coord_system)
    unmapped_cols = [
        c for c in columns
        if c not in (req.chr_col, req.start_col, end_col, strand_col)
    ]

    try:
        mapped_df = CustomParser.map_columns(
            raw_df, req.chr_col, req.start_col, end_col, unmapped_cols
        )
        if strand_col is not None:
            mapped_df["strand"] = raw_df[strand_col]
        if end_col is None:
            # A single position is exactly one base in the declared source
            # system (see the Streamlit mapping UI for the rationale).
            start_numeric = pd.to_numeric(mapped_df["start"], errors="coerce")
            mapped_df["end"] = (
                start_numeric if system == "1-based" else start_numeric + 1
            )
        mapped_df = normalize_intervals(mapped_df, coordinate_system=system)
    except (CanonicalSchemaError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Column mapping failed: {exc}")

    session.data["query"]["df"] = mapped_df
    session.data["query"]["needs_mapping"] = False
    session.data["query"]["columns"] = list(mapped_df.columns)
    session.data["query"]["rows"] = len(mapped_df)
    return {
        "status": "success",
        "total_rows": len(mapped_df),
        "columns": list(mapped_df.columns),
        "preview": _clean_df_for_json(mapped_df, 50),
    }


class ExecutionRequest(BaseModel):
    engine: str = "bedtools"
    mode: str = "overlap"
    join: str = "left"
    feature_types: List[str] = ["gene"]
    use_strand: bool = False
    min_overlap: float = 0.0
    assembly: Optional[str] = None
    chr_naming: Optional[str] = None


@app.post("/api/execute")
def execute_annotation(req: ExecutionRequest, session: Session = Depends(get_session)):
    """Executes the genomic interval annotation pipeline.

    HTTP translation only: the single scientific workflow lives in the shared
    ``streamlit_app.core.execution`` service (the same one the Streamlit GUI
    uses). This endpoint maps the request onto that service and serializes the
    outcome; it contains no scientific logic of its own.
    """
    if "query" not in session.data or "annot" not in session.data:
        raise HTTPException(status_code=400, detail="Both query and annotation datasets must be loaded")

    query = session.data["query"]
    annot = session.data["annot"]

    request = AnnotationRequest(
        query=query["df"],
        annotation=annot["df"],
        annotation_format=annot.get("format"),
        engine=req.engine,
        mode=req.mode,
        join=req.join,
        use_strand=req.use_strand,
        min_overlap=req.min_overlap,
        feature_types=tuple(req.feature_types or ()),
        chr_naming=req.chr_naming,
        assembly=req.assembly,
        coord_vcf_header_lines=query.get("vcf_header_lines"),
    )

    try:
        outcome = execute_annotation_core(request)
    except AnnotationExecutionError as exc:
        # Backend/canonicalization failure is propagated explicitly, never
        # reported as an empty result.
        raise HTTPException(status_code=500, detail=exc.message)
    except AnnotationError as exc:
        raise HTTPException(status_code=400, detail=exc.message)

    result_df = outcome.result_df

    query_count = len(outcome.coord_df)
    matched_rows = int(result_df["has_overlap"].sum()) if "has_overlap" in result_df.columns else len(result_df)
    unmatched_rows = len(result_df) - matched_rows
    # Coverage is query-row based (distinct original query rows with at least
    # one match), never a ratio of result rows to query rows: a single query
    # matching many annotations is one matched query, so the invariant 0..100
    # always holds regardless of join direction.
    matched_queries = int(outcome.matched_query_count)
    unmatched_queries = max(0, query_count - matched_queries)
    match_rate = (matched_queries / max(1, query_count)) * 100

    # Store result in this session only. The scientific report fields below
    # are ones the previous response contract could not carry; they are kept
    # for the results/export endpoints and surfaced to the client.
    session.data["result"] = {
        "df": result_df,
        "coord_format": query.get("format"),
        "vcf_header_lines": outcome.vcf_header_lines,
        "vcf_contig_renames": dict(outcome.vcf_contig_renames),
        "chromosome_normalization": (
            outcome.chromosome_normalization.as_dict()
            if outcome.chromosome_normalization is not None
            else None
        ),
        "warnings": [warning.as_dict() for warning in outcome.warnings],
        "feature_filter": (
            outcome.feature_filter.as_dict()
            if outcome.feature_filter is not None
            else None
        ),
        "elapsed": outcome.elapsed_seconds,
        "join": outcome.join,
        "mode": outcome.mode,
    }

    # Generate Chart Data
    chr_dist = []
    if "coord_chr" in result_df.columns:
        counts = result_df["coord_chr"].value_counts().head(25)
        chr_dist = [{"chromosome": str(k), "intervals": int(v)} for k, v in counts.items()]

    feature_dist = []
    if "annot_feature" in result_df.columns and result_df["annot_feature"].notna().any():
        f_counts = result_df["annot_feature"].dropna().value_counts().head(10)
        feature_dist = [{"feature": str(k), "count": int(v)} for k, v in f_counts.items()]

    distance_dist = []
    if req.mode == "closest" and "distance" in result_df.columns:
        valid_d = result_df["distance"].dropna()
        if not valid_d.empty:
            hist, bin_edges = pd.cut(valid_d, bins=15, retbins=True)
            dist_counts = hist.value_counts().sort_index()
            distance_dist = [
                {"range": f"{int(iv.left):,} - {int(iv.right):,}", "count": int(c)}
                for iv, c in dist_counts.items()
            ]

    return {
        "status": "success",
        "stats": {
            "query_count": query_count,
            "result_count": len(result_df),
            "matched_count": matched_rows,
            "unmatched_count": unmatched_rows,
            "matched_query_count": matched_queries,
            "unmatched_query_count": unmatched_queries,
            "match_rate": round(match_rate, 2),
            "elapsed_seconds": round(outcome.elapsed_seconds, 4),
            "engine": outcome.engine,
            "mode": outcome.mode,
            "join": outcome.join,
        },
        "charts": {
            "chromosome_distribution": chr_dist,
            "feature_distribution": feature_dist,
            "distance_distribution": distance_dist,
            "match_ratio": [
                {"name": "Matched", "value": matched_queries},
                {"name": "Unmatched", "value": unmatched_queries},
            ],
        },
        # Scientific report fields the previous response contract could not
        # carry (previously discarded); exposed additively so no run
        # information is lost. ``chromosome_normalization`` is null when
        # names were kept as provided.
        "warnings": [warning.as_dict() for warning in outcome.warnings],
        "chromosome_normalization": (
            outcome.chromosome_normalization.as_dict()
            if outcome.chromosome_normalization is not None
            else None
        ),
        "feature_filter": (
            outcome.feature_filter.as_dict()
            if outcome.feature_filter is not None
            else None
        ),
        # Gene/feature frequency table for the results gene-list panel
        # (restored from the original Streamlit app; review finding F4).
        "gene_list": _gene_list_payload(result_df),
        "columns": list(result_df.columns),
        "total_rows": len(result_df),
        "preview": _clean_df_for_json(result_df, 100),
    }


@app.get("/api/results/data")
def get_results_data(
    filter_type: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
):
    """Fetches paginated results with filter support (all, matched, unmatched)."""
    if "result" not in session.data:
        raise HTTPException(status_code=404, detail="No execution results available")

    df = session.data["result"]["df"]
    if filter_type == "matched" and "has_overlap" in df.columns:
        filtered = df[df["has_overlap"] == True]
    elif filter_type == "unmatched" and "has_overlap" in df.columns:
        filtered = df[df["has_overlap"] == False]
    else:
        filtered = df

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    sliced = filtered.iloc[start_idx:end_idx]

    return {
        "total_rows": len(filtered),
        "page": page,
        "page_size": page_size,
        "total_pages": (len(filtered) + page_size - 1) // page_size,
        "rows": _clean_df_for_json(sliced, page_size),
    }


def _gene_list_payload(df: pd.DataFrame) -> Dict[str, Any]:
    """Gene/feature frequency payload for the results gene-list panel.

    ``genes`` is the sorted, placeholder-free list of distinct names (the
    input for external enrichment tools); ``top10`` feeds the bar chart and
    keeps the original result's row counts.
    """
    gene_col = _find_gene_column(df)
    if gene_col is None:
        return {"gene_column": None, "genes": [], "top10": []}

    values = df[gene_col].dropna().astype(str)
    genes = sorted({value for value in values if value not in _GENE_PLACEHOLDERS})
    counts = df[gene_col].dropna().value_counts().head(10)
    return {
        "gene_column": gene_col,
        "genes": genes,
        "top10": [{"gene": str(name), "count": int(count)} for name, count in counts.items()],
    }


@app.get("/api/results/gene-list")
def get_gene_list(session: Session = Depends(get_session)):
    """Frequency table of the matched annotation gene/feature names.

    Restores the "Charts and gene list" panel of the original Streamlit app
    (top-10 gene chart and gene-list export for external enrichment tools
    such as g:Profiler/Enrichr/DAVID/STRING). This is a frequency table over
    the existing result; no enrichment is computed here.
    """
    if "result" not in session.data:
        raise HTTPException(status_code=404, detail="No execution results available")

    return _gene_list_payload(session.data["result"]["df"])


@app.get("/api/export/{fmt}")
def export_results(fmt: str, filter_type: str = "all", session: Session = Depends(get_session)):
    """Downloads results in CSV, TSV, Excel, or VCF format."""
    if "result" not in session.data:
        raise HTTPException(status_code=404, detail="No results found to export")

    res = session.data["result"]
    df = res["df"]
    if filter_type == "matched" and "has_overlap" in df.columns:
        export_df = df[df["has_overlap"] == True]
    elif filter_type == "unmatched" and "has_overlap" in df.columns:
        export_df = df[df["has_overlap"] == False]
    else:
        export_df = df

    if fmt == "csv":
        csv_data = export_df.to_csv(index=False)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.csv"},
        )
    elif fmt == "tsv":
        tsv_data = export_df.to_csv(index=False, sep="\t")
        return Response(
            content=tsv_data,
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.tsv"},
        )
    elif fmt == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Annotated")
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.xlsx"},
        )
    elif fmt == "vcf":
        # VCF export is only meaningful for VCF query input: the exporter
        # fabricates records from canonical intervals, so REF/ALT would be
        # synthetic placeholders for BED/GFF/CSV input. The released
        # Streamlit app gated this on ``coord_format == "vcf"``; enforce the
        # same rule at the HTTP boundary, independently of the frontend.
        if res.get("coord_format") != "vcf":
            raise HTTPException(
                status_code=400,
                detail=(
                    "VCF export is only available when the query input is a "
                    "VCF file; this result was produced from "
                    f"{res.get('coord_format') or 'an unknown'} input. Export "
                    "as CSV, TSV or Excel instead."
                ),
            )
        try:
            vcf_str = build_annotated_vcf(
                export_df,
                original_header_lines=res.get("vcf_header_lines"),
                contig_renames=res.get("vcf_contig_renames"),
            )
        except ChromosomeContigCollisionError:
            raise HTTPException(
                status_code=409,
                detail=(
                    "VCF export unavailable: some normalized chromosome "
                    "names share contig metadata that conflicts. Choose a "
                    "different source assembly for this input."
                ),
            )
        except VCFExportError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return Response(
            content=vcf_str,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=annotated_variants.vcf"},
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format {fmt}")


# ---------------------------------------------------------------------------
# Mount Built Frontend Static Files (if dist exists)
# ---------------------------------------------------------------------------
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
