"""Task 14.3: React/FastAPI functional parity at the HTTP boundary.

Covers the regressions found in the independent PR review (excluding VCF
export, which is Task 14.4):

* the frontend's default configuration completes a valid run;
* custom query column mapping uses the real core parser API;
* feature filtering is the shared ``core/execution`` expansion, not a
  second implementation in the backend;
* the normalization report and non-fatal warnings reach the client intact
  (so the GUI can distinguish unknown / no-alias / renamed / collapsed /
  no-shared identifiers);
* request-shape and input errors are clear HTTP errors without tracebacks
  or private paths;
* Task 14.1 session isolation still holds after a full run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SessionStore
from streamlit_app.core.engine_registry import engine_available

ROOT = Path(__file__).resolve().parents[1]

GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t1\t100\t.\t+\t.\tID=g1\n"
    b"chr1\tsrc\tmRNA\t1\t100\t.\t+\t.\tID=t1\n"
    b"chr1\tsrc\tfive_prime_UTR\t1\t20\t.\t+\t.\tID=u1\n"
    b"chr1\tsrc\texon\t1\t30\t.\t+\t.\tID=e1\n"
)


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


def _upload(client, name, content, role, coord_system=None, media="text/plain"):
    data = {"role": role}
    if coord_system is not None:
        data["coord_system"] = coord_system
    return client.post("/api/upload", files={"file": (name, content, media)}, data=data)


def _load_sample(client):
    response = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200, response.text


def _require_bedtools():
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")


# ---------------------------------------------------------------------------
# Default configuration (frontend defaults)
# ---------------------------------------------------------------------------

#: Exact defaults the React app sends for a fresh session after the fix.
FRONTEND_DEFAULT = {
    "engine": "bedtools",
    "mode": "overlap",
    "join": "left",
    "feature_types": ["gene"],
    "use_strand": False,
    "min_overlap": 0.0,
    "assembly": None,
    "chr_naming": None,
}


def test_frontend_default_request_succeeds(client):
    _require_bedtools()
    _load_sample(client)
    response = client.post("/api/execute", json=FRONTEND_DEFAULT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stats"]["result_count"] >= 1
    assert body["stats"]["engine"] == "bedtools"
    assert body["warnings"] == []
    assert body["chromosome_normalization"] is None
    assert body["feature_filter"]["applied"] is True


def test_legacy_frontend_default_is_rejected(client):
    """Documents the root cause: the label (not the option key) was sent as
    ``chr_naming`` while no assembly was selected."""
    _load_sample(client)
    legacy = dict(FRONTEND_DEFAULT, chr_naming="Ensembl names", assembly=None)
    response = client.post("/api/execute", json=legacy)
    assert response.status_code == 400
    assert "genome assembly" in response.json()["detail"].lower()


def test_frontend_source_defaults_match_the_backend_contract():
    source = (ROOT / "frontend" / "src" / "App.jsx").read_text("utf-8")
    assert "useState('Keep original names')" in source
    assert "useState('Ensembl names')" not in source
    for token in (
        "execResult.warnings",
        "execResult.chromosome_normalization",
        "execResult.feature_filter",
        "ChromosomeNormalizationReport",
    ):
        assert token in source, token


# ---------------------------------------------------------------------------
# Custom query column mapping
# ---------------------------------------------------------------------------

CUSTOM_CSV = (
    b"Chromosome\tStart\tEnd\tgene\n"
    b"chr1\t100\t200\tg1\n"
    b"chr1\t500\t600\tg2\n"
)


def _custom_query(client, content=CUSTOM_CSV, name="q.csv"):
    response = _upload(client, name, content, "query", media="text/csv")
    assert response.status_code == 200, response.text
    assert response.json()["format"] == "custom"
    assert response.json()["needs_mapping"] is True
    return response


def test_custom_query_mapping_end_to_end(client):
    _require_bedtools()
    _custom_query(client)

    mapped = client.post("/api/apply-mapping", json={
        "chr_col": "Chromosome", "start_col": "Start", "end_col": "End",
        "strand_col": None, "coord_system": "Auto-detect",
    })
    assert mapped.status_code == 200, mapped.text
    body = mapped.json()
    assert body["columns"] == ["chr", "start", "end", "gene"]
    assert body["preview"][0] == {"chr": "chr1", "start": 100, "end": 200, "gene": "g1"}

    # A custom query always requires mapping (parity with the Streamlit app).
    missing = client.post("/api/apply-mapping", json={
        "chr_col": "nope", "start_col": "Start", "end_col": "End",
    })
    assert missing.status_code == 400
    assert "not a column" in missing.json()["detail"]

    ok = _upload(client, "a.gff3", GFF, "annot")
    assert ok.status_code == 200
    result = client.post("/api/execute", json=FRONTEND_DEFAULT)
    assert result.status_code == 200, result.text
    assert result.json()["stats"]["result_count"] >= 1


def test_custom_mapping_single_position_both_systems(client):
    one_based = b"chrom\tpos\tname\nchr2\t50\ts1\n"
    _custom_query(client, one_based, "s.tsv")
    response = client.post("/api/apply-mapping", json={
        "chr_col": "chrom", "start_col": "pos", "end_col": None,
        "coord_system": "1-based (GFF/GTF/VCF)",
    })
    assert response.status_code == 200, response.text
    row = response.json()["preview"][0]
    assert (row["chr"], row["start"], row["end"], row["name"]) == ("chr2", 49, 50, "s1")

    api_server.store = SessionStore()
    other = TestClient(app)
    _custom_query(other, one_based, "s.tsv")
    response = other.post("/api/apply-mapping", json={
        "chr_col": "chrom", "start_col": "pos", "end_col": None,
        "coord_system": "Auto-detect",
    })
    assert response.status_code == 200, response.text
    row = response.json()["preview"][0]
    assert (row["start"], row["end"]) == (50, 51)


def test_custom_mapping_preserves_metadata_and_strand(client):
    content = b"chrom\tbegin\tfinish\tstrand\tlabel\nchr1\t10\t20\t+\tA\n"
    _custom_query(client, content, "withstrand.tsv")
    response = client.post("/api/apply-mapping", json={
        "chr_col": "chrom", "start_col": "begin", "end_col": "finish",
        "strand_col": "strand", "coord_system": "0-based (BED)",
    })
    assert response.status_code == 200, response.text
    assert response.json()["columns"] == ["chr", "start", "end", "strand", "label"]
    assert response.json()["preview"][0]["strand"] == "+"
    assert response.json()["preview"][0]["label"] == "A"


def test_custom_mapping_rejects_duplicate_roles(client):
    _custom_query(client)
    response = client.post("/api/apply-mapping", json={
        "chr_col": "Chromosome", "start_col": "Chromosome", "end_col": "End",
    })
    assert response.status_code == 400


def test_custom_mapping_rejects_non_numeric_start_without_path_leak(client):
    content = b"chrom\tpos\nchr1\tnotanumber\n"
    _custom_query(client, content, "bad.tsv")
    response = client.post("/api/apply-mapping", json={
        "chr_col": "chrom", "start_col": "pos", "end_col": None,
    })
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Column mapping failed" in detail
    assert "annotater-upload" not in detail


# ---------------------------------------------------------------------------
# Feature filtering uses the shared expansion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "feature_types, expected_used",
    [
        (["gene"], 1),
        (["transcript"], 1),          # expands to mRNA (shared mapping)
        (["exon"], 1),
        (["5' UTR"], 1),              # expands to five_prime_UTR
        (["mRNA"], 1),                # arbitrary literal source value
    ],
)
def test_feature_filter_uses_shared_expansion(client, feature_types, expected_used):
    _require_bedtools()
    _upload(client, "q.bed", b"chr1\t0\t200\tq1\n", "query")
    _upload(client, "a.gff3", GFF, "annot")
    response = client.post("/api/execute", json=dict(
        FRONTEND_DEFAULT, feature_types=feature_types,
    ))
    assert response.status_code == 200, response.text
    report = response.json()["feature_filter"]
    assert report["applied"] is True
    assert report["used_rows"] == expected_used
    assert report["total_rows"] == 4


def test_feature_filter_no_filter_uses_all_features(client):
    _require_bedtools()
    _upload(client, "q.bed", b"chr1\t0\t200\tq1\n", "query")
    _upload(client, "a.gff3", GFF, "annot")
    response = client.post("/api/execute", json=dict(
        FRONTEND_DEFAULT, feature_types=[],
    ))
    assert response.status_code == 200, response.text
    assert response.json()["feature_filter"] is None


def test_feature_filter_empty_result_is_a_clear_error(client):
    _require_bedtools()
    _upload(client, "q.bed", b"chr1\t0\t200\tq1\n", "query")
    _upload(client, "a.gff3", GFF, "annot")
    response = client.post("/api/execute", json=dict(
        FRONTEND_DEFAULT, feature_types=["CDS"],
    ))
    assert response.status_code == 400
    assert "No annotations match" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Normalization reports and warnings
# ---------------------------------------------------------------------------

_NORMALIZE_QUERY = b"chrM\t0\t100\tq0\nMT\t0\t100\tq1\nscaffold_XYZ\t0\t100\tq2\nchr1\t0\t100\tq3\n"
_NORMALIZE_ANNOT = b"##gff-version 3\nchrM\tsrc\tgene\t1\t50\t.\t+\t.\tID=g1\nchr1\tsrc\tgene\t1\t50\t.\t+\t.\tID=g2\n"


def test_normalization_report_exposes_rename_unknown_and_collapse(client):
    _require_bedtools()
    _upload(client, "q.bed", _NORMALIZE_QUERY, "query")
    _upload(client, "a.gff3", _NORMALIZE_ANNOT, "annot")
    response = client.post("/api/execute", json=dict(
        FRONTEND_DEFAULT, chr_naming="ensembl", assembly="GRCh38",
    ))
    assert response.status_code == 200, response.text
    report = response.json()["chromosome_normalization"]
    assert report is not None
    assert report["target"] == "ensembl"
    coord = report["coord_report"]
    assert coord["renames"].get("chrM") == "MT"
    assert coord["renames"].get("chr1") == "1"
    assert "scaffold_XYZ" in coord["unknown"]
    assert coord["collapses"].get("MT") == ["chrM", "MT"]
    # The keys the GUI relies on to distinguish categories are always present.
    for key in ("unknown", "no_alias_for_target", "collapses", "renames"):
        assert key in coord and key in report["annot_report"]


def test_normalization_report_exposes_recognized_without_alias(client):
    _require_bedtools()
    _upload(client, "q.bed", b"chrM\t0\t100\tq0\nchr1\t0\t100\tq1\n", "query")
    _upload(client, "a.gff3",
            b"##gff-version 3\nchrM\tsrc\tgene\t1\t50\t.\t+\t.\tID=g1\n"
            b"chr1\tsrc\tgene\t1\t50\t.\t+\t.\tID=g2\n", "annot")
    response = client.post("/api/execute", json=dict(
        FRONTEND_DEFAULT, chr_naming="ensembl", assembly="hg19",
    ))
    assert response.status_code == 200, response.text
    coord = response.json()["chromosome_normalization"]["coord_report"]
    assert coord["no_alias_for_target"].get("chrM") == 1


def test_no_shared_identifier_warning_is_propagated(client):
    _require_bedtools()
    _upload(client, "q.bed", b"chrZ\t0\t100\tq0\n", "query")
    _upload(client, "a.gff3",
            b"##gff-version 3\nchrA\tsrc\tgene\t1\t50\t.\t+\t.\tID=g1\n", "annot")
    response = client.post("/api/execute", json=FRONTEND_DEFAULT)
    assert response.status_code == 200, response.text
    body = response.json()
    warnings = {w["code"]: w["message"] for w in body["warnings"]}
    assert "no_shared_identifiers" in warnings
    assert "No shared chromosome identifiers remain" in warnings["no_shared_identifiers"]
    # Left join keeps the query row even with no match.
    assert body["stats"]["result_count"] == 1


# ---------------------------------------------------------------------------
# Error behavior
# ---------------------------------------------------------------------------

def test_execute_requires_both_datasets(client):
    response = client.post("/api/execute", json=FRONTEND_DEFAULT)
    assert response.status_code == 400
    assert "must be loaded" in response.json()["detail"]


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"engine": "nope"}, "Invalid option"),
        ({"mode": "sideways"}, "Invalid operation"),
        ({"join": "outer"}, "Invalid join"),
    ],
)
def test_execute_rejects_invalid_options(client, override, fragment):
    _load_sample(client)
    response = client.post("/api/execute", json=dict(FRONTEND_DEFAULT, **override))
    assert response.status_code == 400
    assert fragment in response.json()["detail"]


def test_upload_error_does_not_leak_private_paths(client):
    # A BED whose end is not greater than its start is invalid input.
    response = _upload(client, "bad.bed", b"chr1\t100\t50\n", "query")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "annotater-upload" not in detail
    assert "/tmp/" not in detail


# ---------------------------------------------------------------------------
# Session isolation after a full run (Task 14.1 regression)
# ---------------------------------------------------------------------------

def test_session_isolation_holds_after_a_full_run():
    _require_bedtools()
    first = TestClient(app)
    second = TestClient(app)

    _load_sample(first)
    assert first.post("/api/execute", json=FRONTEND_DEFAULT).status_code == 200
    assert first.get("/api/results/data").status_code == 200

    # The second client never loaded data or ran: nothing is shared.
    assert second.post("/api/execute", json=FRONTEND_DEFAULT).status_code == 400
    assert second.get("/api/results/data").status_code == 404
