"""Task 14.7a (review finding F1): match coverage is query-row based.

The FastAPI ``stats.match_rate`` previously divided matched *result rows* by
query rows, so a single query interval overlapping several annotation rows
reported more than 100% (1 query x 2 genes -> 200%). Coverage must instead
count distinct original query rows with at least one match, which is exact
for many-to-many matches, duplicate query coordinates with distinct row
identities, both join directions and a zero-query edge, and can never leave
the 0..100 range.

These tests pin the framework-independent service contract (both engines)
and the HTTP contract; none of them re-implement the metric.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SessionStore
from streamlit_app.core.engine_registry import engine_available
from streamlit_app.core.execution import AnnotationRequest, execute_annotation
from streamlit_app.core.schema import canonical_result_columns
from tests.parity.comparator import interval_table


def _require(engine):
    if not engine_available(engine):
        pytest.skip(f"{engine} engine unavailable")


def _run(query, annot, join="left", mode="overlap", engine="bedtools"):
    return execute_annotation(
        AnnotationRequest(
            query=query, annotation=annot, join=join, mode=mode, engine=engine
        )
    )


@pytest.fixture(params=["bedtools", "polars-bio"])
def engine(request):
    _require(request.param)
    return request.param


def test_many_to_many_counts_query_once(engine):
    """One query overlapping two annotations is one matched query (not 200%)."""
    query = interval_table(["chr1"], [0], [100])
    annot = interval_table(["chr1", "chr1"], [0, 40], [10, 60])

    outcome = _run(query, annot, engine=engine)

    assert len(outcome.coord_df) == 1
    assert len(outcome.result_df) == 2
    assert outcome.matched_query_count == 1


def test_duplicate_query_coordinates_counted_separately(engine):
    """Two identical query rows are two distinct identities, both matched."""
    query = interval_table(["chr1", "chr1"], [0, 0], [100, 100])
    annot = interval_table(["chr1"], [0], [10])

    outcome = _run(query, annot, engine=engine)

    assert outcome.matched_query_count == 2


def test_left_join_unmatched_query_is_not_counted(engine):
    query = interval_table(["chr1", "chr1"], [0, 500], [100, 600])
    annot = interval_table(["chr1"], [0], [10])

    outcome = _run(query, annot, join="left", engine=engine)

    assert outcome.matched_query_count == 1


def test_inner_join_unmatched_query_is_not_counted(engine):
    """Inner join drops the unmatched query but coverage still reports 1/2."""
    query = interval_table(["chr1", "chr1"], [0, 500], [100, 600])
    annot = interval_table(["chr1"], [0], [10])

    outcome = _run(query, annot, join="inner", engine=engine)

    assert len(outcome.result_df) == 1
    assert outcome.matched_query_count == 1


def test_empty_annotation_is_zero_coverage(engine):
    query = interval_table(["chr1"], [0], [100])
    annot = interval_table([], [], []).astype(
        {"chr": "str", "start": "int64", "end": "int64"}
    )

    outcome = _run(query, annot, join="left", engine=engine)

    assert outcome.matched_query_count == 0


def test_result_schema_is_unchanged_by_the_metric(engine):
    """The identity column used to derive coverage never leaks to callers."""
    query = interval_table(["chr1"], [0], [100])
    annot = interval_table(["chr1", "chr1"], [0, 40], [10, 60])

    outcome = _run(query, annot, engine=engine)

    assert list(outcome.result_df.columns) == list(
        canonical_result_columns(outcome.coord_df, outcome.annot_df)
    )
    assert not any("row_uid" in c for c in outcome.result_df.columns)


def test_user_column_that_collides_with_the_identity_name(engine):
    """A user column matching the private name is preserved, not clobbered."""
    query = interval_table(["chr1"], [0], [100], annotater_query_row_uid=[7])
    annot = interval_table(["chr1"], [0], [10])

    outcome = _run(query, annot, engine=engine)

    assert outcome.matched_query_count == 1
    assert "coord_annotater_query_row_uid" in outcome.result_df.columns
    assert outcome.result_df["coord_annotater_query_row_uid"].tolist() == [7]


# ---------------------------------------------------------------------------
# HTTP boundary
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


def test_api_match_rate_is_query_based_and_bounded(client):
    """Regression: 1 query overlapping 2 annotations must report 100%, not 200%."""
    _require("bedtools")
    client.post(
        "/api/upload",
        files={"file": ("q.bed", b"chr1\t0\t200\tq1\n", "text/plain")},
        data={"role": "query"},
    )
    client.post(
        "/api/upload",
        files={"file": ("a.bed", b"chr1\t0\t10\ta1\nchr1\t20\t30\ta2\n", "text/plain")},
        data={"role": "annot"},
    )
    response = client.post(
        "/api/execute",
        json={"engine": "bedtools", "mode": "overlap", "join": "left"},
    )
    assert response.status_code == 200, response.text

    stats = response.json()["stats"]
    assert stats["query_count"] == 1
    assert stats["matched_query_count"] == 1
    assert stats["unmatched_query_count"] == 0
    assert stats["match_rate"] == 100.0
    assert 0.0 <= stats["match_rate"] <= 100.0


def test_api_match_rate_bounds_across_joins(client):
    """Coverage stays within 0..100 for both join directions."""
    _require("bedtools")
    client.post(
        "/api/upload",
        files={"file": ("q.bed", b"chr1\t0\t50\tq1\nchr1\t900\t950\tq2\n", "text/plain")},
        data={"role": "query"},
    )
    client.post(
        "/api/upload",
        files={"file": ("a.bed", b"chr1\t0\t10\ta1\nchr1\t20\t30\ta2\n", "text/plain")},
        data={"role": "annot"},
    )
    for join in ("left", "inner"):
        response = client.post(
            "/api/execute",
            json={"engine": "bedtools", "mode": "overlap", "join": join},
        )
        assert response.status_code == 200, response.text
        stats = response.json()["stats"]
        assert stats["query_count"] == 2
        assert stats["matched_query_count"] == 1
        assert stats["unmatched_query_count"] == 1
        assert stats["match_rate"] == 50.0
