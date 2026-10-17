"""Task 14.7a (review finding F4) — gene-list frequency panel.

The React port dropped the "Charts and gene list" panel of the original
Streamlit app. The regression contract here:

* ``/api/execute`` returns a ``gene_list`` payload (frequency table over the
  existing result; no enrichment is computed).
* ``GET /api/results/gene-list`` serves the same payload for a stored result.
* Placeholder name tokens (``-1``, ``.``, ``nan``, ``""``) are never reported
  as genes, mirroring ``_find_gene_column`` in the original app.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import (
    _find_gene_column,
    _gene_list_payload,
    app,
)
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core.engine_registry import engine_available
from tests.test_shared_vcf_export import ANNOT_GFF, QUERY_VCF, _REQUEST, _upload


def _require_bedtools():
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")


# ---------------------------------------------------------------------------
# Gene-column detection (ported from the original Streamlit app)
# ---------------------------------------------------------------------------


class TestFindGeneColumn:
    def test_prefers_annot_name_over_id(self):
        df = pd.DataFrame({"annot_ID": ["x1"], "annot_Name": ["X1"]})
        assert _find_gene_column(df) == "annot_Name"

    def test_plain_candidate_column_accepted_as_is(self):
        df = pd.DataFrame({"gene": ["g1"]})
        assert _find_gene_column(df) == "gene"

    def test_annot_column_full_of_placeholders_is_rejected(self):
        df = pd.DataFrame({"annot_Name": ["-1", ".", "nan"], "annot_ID": ["-1"] * 3})
        assert _find_gene_column(df) is None

    def test_annot_column_with_one_real_value_is_accepted(self):
        df = pd.DataFrame({"annot_Name": ["-1", "g1"]})
        assert _find_gene_column(df) == "annot_Name"

    def test_no_candidate_columns_returns_none(self):
        df = pd.DataFrame({"annot_chr": ["1"], "annot_start": [1]})
        assert _find_gene_column(df) is None


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


class TestGeneListPayload:
    def test_genes_are_sorted_placeholder_free(self):
        df = pd.DataFrame({"annot_Name": ["g2", "g1", "g2", None, "-1"]})
        payload = _gene_list_payload(df)
        assert payload["gene_column"] == "annot_Name"
        assert payload["genes"] == ["g1", "g2"]
        # top10 keeps the raw row counts (chart data), not the filtered list.
        by_gene = {row["gene"]: row["count"] for row in payload["top10"]}
        assert by_gene["g1"] == 1
        assert by_gene["g2"] == 2

    def test_no_gene_column_yields_empty_payload(self):
        df = pd.DataFrame({"annot_chr": ["1"], "annot_start": [1], "annot_end": [2]})
        assert _gene_list_payload(df) == {"gene_column": None, "genes": [], "top10": []}

    def test_top10_is_capped_at_ten(self):
        df = pd.DataFrame({"annot_Name": [f"g{i}" for i in range(15)]})
        payload = _gene_list_payload(df)
        assert len(payload["top10"]) == 10


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())
    return TestClient(app)


def _seed_result(client, df: pd.DataFrame):
    session = api_server.store.create()
    session.data["result"] = {"df": df}
    client.cookies.set(SESSION_COOKIE_NAME, session.token)


class TestGeneListEndpoint:
    def test_no_result_is_404(self, client):
        response = client.get("/api/results/gene-list")
        assert response.status_code == 404

    def test_frequency_table_for_stored_result(self, client):
        _seed_result(client, pd.DataFrame({"annot_Name": ["g1", "g1", "g2"]}))
        body = client.get("/api/results/gene-list").json()
        assert body["gene_column"] == "annot_Name"
        assert body["genes"] == ["g1", "g2"]
        assert body["top10"][0] == {"gene": "g1", "count": 2}

    def test_result_without_gene_column_returns_empty(self, client):
        _seed_result(client, pd.DataFrame({"annot_chr": ["1"]}))
        body = client.get("/api/results/gene-list").json()
        assert body == {"gene_column": None, "genes": [], "top10": []}


# ---------------------------------------------------------------------------
# Execute response contract (end-to-end)
# ---------------------------------------------------------------------------


class TestExecuteGeneList:
    def test_execute_response_includes_gene_list(self, monkeypatch):
        _require_bedtools()
        monkeypatch.setattr(api_server, "store", SessionStore())
        client = TestClient(app)
        _upload(client, "query.vcf", QUERY_VCF, "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        response = client.post("/api/execute", json=_REQUEST)
        assert response.status_code == 200, response.text

        gene_list = response.json()["gene_list"]
        assert gene_list["gene_column"] is not None
        assert gene_list["genes"], "sample fixture has at least one named gene"
        assert all(g not in {"-1", ".", "nan", ""} for g in gene_list["genes"])
        assert len(gene_list["top10"]) <= 10

    def test_gene_list_derives_from_result_frame_not_query(self, monkeypatch):
        _require_bedtools()
        monkeypatch.setattr(api_server, "store", SessionStore())
        client = TestClient(app)
        _upload(client, "q.bed", b"chr1\t0\t200\t\n", "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        response = client.post("/api/execute", json=_REQUEST)
        assert response.status_code == 200, response.text

        gene_list = response.json()["gene_list"]
        # The query has no names; the list still comes from the matched
        # annotation side of the result frame.
        assert gene_list["gene_column"] is not None
        assert gene_list["genes"]