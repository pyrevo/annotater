"""Task 14.2: Streamlit and FastAPI share one scientific execution service.

The single scientific workflow lives in ``streamlit_app.core.execution``
(validation -> feature filter -> chromosome normalization -> warning ->
engine dispatch -> canonical result). These tests assert the Task 14.2
objectives at the boundary that matters:

* both frontends call the *same* service object, and the service imports
  neither Streamlit nor FastAPI;
* the FastAPI backend carries no scientific logic of its own;
* the backends agree through that service (identical canonical outcomes);
* the shared service reports feature filtering, chromosome normalization
  and non-fatal warnings uniformly;
* the Task 14.1 session isolation still holds once a run executes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SessionStore
from streamlit_app.core import execution
from streamlit_app.core.engine_registry import engine_available
from streamlit_app.core.execution import (
    AnnotationError,
    AnnotationExecutionError,
    AnnotationRequest,
    execute_annotation,
)
from tests.parity.comparator import assert_canonical_equal, interval_table

ROOT = Path(__file__).resolve().parents[1]
SERVICE = execution.execute_annotation


# ---------------------------------------------------------------------------
# One shared, framework-independent service
# ---------------------------------------------------------------------------


def test_streamlit_and_fastapi_import_the_same_service_object():
    """Both frontends must bind the very same core function (no re-export copy
    that could drift)."""
    import streamlit_app.streamlit_app as gui

    assert gui.execute_annotation is SERVICE
    assert api_server.execute_annotation_core is SERVICE


def test_core_execution_imports_neither_streamlit_nor_fastapi():
    """Import the service in a clean interpreter: no web framework may load."""
    code = (
        "import sys\n"
        "import streamlit_app.core.execution\n"
        "assert 'streamlit' not in sys.modules, 'streamlit was imported'\n"
        "assert 'fastapi' not in sys.modules, 'fastapi was imported'\n"
        "print('clean')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(ROOT),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_fastapi_module_holds_no_scientific_primitives():
    """The backend must not own validation, normalization, canonicalization or
    engine construction: it translates HTTP to the shared service only."""
    for name in (
        "build_engine",
        "normalize_input_chromosomes",
        "canonicalize_annotation_result",
        "header_contig_renames",
        "DataValidator",
    ):
        assert not hasattr(api_server, name), f"{name} leaked into api_server"


# ---------------------------------------------------------------------------
# The service itself: engine agreement and uniform reporting
# ---------------------------------------------------------------------------


def test_both_engines_produce_identical_canonical_outcomes():
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")
    if not engine_available("polars-bio"):
        pytest.skip("polars-bio unavailable")

    coord = interval_table(
        ["chrA", "chrA", "chrB"], [10, 100, 0], [20, 200, 5],
        gene=["g1", "g2", "g3"],
    )
    annot = interval_table(
        ["chrA", "chrA"], [5, 25], [15, 35], feature=["gene", "exon"],
    )

    bed = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="gff",
                          engine="bedtools")
    )
    pol = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="gff",
                          engine="polars-bio")
    )

    assert_canonical_equal(bed.result_df, pol.result_df)
    assert bed.warnings == pol.warnings
    assert bed.engine == "bedtools" and pol.engine == "polars-bio"
    assert bed.engine_label == "Bedtools"
    assert pol.engine_label == "Polars-Bio"


def test_feature_filter_is_reported_and_empty_match_is_a_warning():
    coord = interval_table(["chrA"], [10], [20], gene=["g1"])
    annot = interval_table(
        ["chrA", "chrA"], [5, 25], [15, 35], feature=["CDS", "exon"],
    )

    applied = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="gff",
                          feature_types=("exon",))
    )
    assert applied.feature_filter is not None
    assert applied.feature_filter.applied is True
    assert applied.feature_filter.used_rows == 1
    assert applied.feature_filter.total_rows == 2
    assert applied.feature_filter.selected == ("exon",)

    with pytest.raises(AnnotationError) as excinfo:
        execute_annotation(
            AnnotationRequest(query=coord, annotation=annot,
                              annotation_format="gff", feature_types=("gene",))
        )
    assert excinfo.value.code == "no_feature_match"
    assert excinfo.value.severity == "warning"


def test_feature_filter_is_ignored_for_non_gff_formats():
    """A BED annotation has no ``feature`` column semantics: the filter is a
    no-op (never silently drops rows or reports a filter)."""
    coord = interval_table(["chrA"], [10], [20], gene=["g1"])
    annot = interval_table(["chrA"], [5], [15], feature=["gene"])
    outcome = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="bed",
                          feature_types=("gene",))
    )
    assert outcome.feature_filter is None
    assert len(outcome.annot_df) == 1


def test_chromosome_normalization_is_reported_for_both_tables():
    coord = interval_table(["1", "chr2"], [100, 10], [200, 20], gene=["g1", "g2"])
    annot = interval_table(["2", "chr1"], [5, 25], [15, 35], feature=["gene", "gene"])

    outcome = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="gff",
                          chr_naming="ucsc", assembly="GRCh38")
    )
    norm = outcome.chromosome_normalization
    assert norm is not None
    assert norm.assembly_id == "GRCh38"
    assert norm.target == "ucsc"
    assert outcome.coord_df["chr"].tolist() == ["chr1", "chr2"]
    assert outcome.annot_df["chr"].tolist() == ["chr2", "chr1"]
    assert norm.coord_report.changed_rows >= 1
    assert norm.annot_report.changed_rows >= 1


def test_no_shared_identifiers_is_a_non_fatal_warning():
    coord = interval_table(["chrZ"], [10], [20], gene=["g1"])
    annot = interval_table(["chrA"], [5], [15], feature=["gene"])
    outcome = execute_annotation(
        AnnotationRequest(query=coord, annotation=annot, annotation_format="gff")
    )
    codes = [warning.code for warning in outcome.warnings]
    assert codes == ["no_shared_identifiers"]
    assert len(outcome.result_df) == 1  # left join keeps the query row


# ---------------------------------------------------------------------------
# FastAPI delegates to the shared service
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


def _load_gene_sample(client: TestClient) -> None:
    response = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200, response.text


def test_fastapi_execute_delegates_to_the_shared_service(client, monkeypatch):
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")

    calls = []
    real = api_server.execute_annotation_core

    def spy(request):
        calls.append(request)
        return real(request)

    monkeypatch.setattr(api_server, "execute_annotation_core", spy)

    _load_gene_sample(client)
    response = client.post(
        "/api/execute",
        json={"engine": "bedtools", "mode": "overlap", "join": "left"},
    )
    assert response.status_code == 200, response.text

    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request, AnnotationRequest)
    assert request.engine == "bedtools"
    assert request.annotation_format == "gff"

    body = response.json()
    assert body["status"] == "success"
    assert body["stats"]["result_count"] >= 1
    assert body["stats"]["engine"] == "bedtools"
    # Outcome-derived report fields are surfaced, not discarded.
    assert body["warnings"] == []
    assert body["chromosome_normalization"] is None
    assert body["feature_filter"]["applied"] is True


def test_fastapi_maps_invalid_request_to_400_and_backend_failure_to_500(
        client, monkeypatch):
    _load_gene_sample(client)

    def invalid(request):
        raise AnnotationError("invalid_option", "bad option")

    monkeypatch.setattr(api_server, "execute_annotation_core", invalid)
    response = client.post("/api/execute", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "bad option"

    def crash(request):
        raise AnnotationExecutionError(
            "bedtools exploded", engine_label="Bedtools", mode="overlap",
            join="left",
        )

    monkeypatch.setattr(api_server, "execute_annotation_core", crash)
    response = client.post("/api/execute", json={})
    assert response.status_code == 500
    assert "bedtools exploded" in response.json()["detail"]


def test_fastapi_execute_requires_both_datasets(client):
    response = client.post("/api/execute", json={})
    assert response.status_code == 400
    assert "must be loaded" in response.json()["detail"]


def test_execute_results_stay_in_their_own_session():
    """Task 14.1 isolation holds through an actual run: one client's result is
    never visible to another."""
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")

    first = TestClient(app)
    second = TestClient(app)

    _load_gene_sample(first)
    # ``second`` has loaded nothing yet.
    assert second.post("/api/execute", json={}).status_code == 400

    _load_gene_sample(second)
    assert first.post("/api/execute", json={}).status_code == 200
    assert first.get("/api/results/data").status_code == 200
    assert second.get("/api/results/data").status_code == 404


# ---------------------------------------------------------------------------
# Streamlit delegates to the shared service
# ---------------------------------------------------------------------------


def test_streamlit_app_delegates_to_the_shared_service(monkeypatch):
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")

    from streamlit.testing.v1 import AppTest

    # The GUI script re-imports the service on every run, so patching the
    # source module is what a fresh script execution observes.
    calls = []
    real = execution.execute_annotation

    def spy(request):
        calls.append(request)
        return real(request)

    monkeypatch.setattr(execution, "execute_annotation", spy)

    entry = ROOT / "streamlit_app" / "streamlit_app.py"
    at = AppTest.from_file(str(entry), default_timeout=120)
    at.run()

    def widget(kind, key):
        return next(e for e in at.get(kind) if getattr(e, "key", None) == key)

    widget("file_uploader", "coord_file").set_value(
        ("q.bed", b"chr1\t0\t100\tq0\n", "text/plain"))
    widget("file_uploader", "annot_file").set_value(
        ("a.gff3", b"##gff-version 3\n"
                    b"chr1\tsrc\tgene\t11\t20\t.\t+\t.\tID=g1\n", "text/plain"))
    at.run()
    widget("button", "run_button").set_value(True)
    at.run()

    assert not at.exception
    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request, AnnotationRequest)
    assert request.annotation_format == "gff"
    assert request.mode == "overlap"
    # The GUI stored the shared outcome (not a locally-computed result).
    assert at.session_state["result_df"] is not None

    captions = " ".join(c.value for c in at.caption)
    assert "annotation features (feature filter)." in captions
