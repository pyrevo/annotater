"""Regression tests for final-gate finding N2.

The declared coordinate system is baked into the parsed table at upload
time (known formats) or at mapping time (custom tables). Before the fix,
changing the coordinate-system declaration after a file was loaded was
silently ignored: the server kept re-running the stale, already-
normalized table. The fix invalidates the stored dataset when the
declaration changes, forcing a re-upload under the new declaration.
"""

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SessionStore

# Extension-neutral, BED-like content: for a .tsv the declared coordinate
# system takes precedence over content sniffing (coordinate_system_for), so
# the same bytes normalize differently under each declaration.
_TSV = b"chr1\t10\t20\nchr1\t30\t40\n"


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


def _upload_query(client, coord_system):
    return client.post(
        "/api/upload",
        files={"file": ("q.tsv", _TSV, "text/tab-separated-values")},
        data={"role": "query", "coord_system": coord_system},
    )


def test_clear_rejects_invalid_roles(client):
    assert client.post("/api/dataset/clear", json={"role": "admin"}).status_code == 400
    assert client.post("/api/dataset/clear", json={}).status_code == 422


def test_clear_with_nothing_stored_allocates_no_session(client):
    response = client.post("/api/dataset/clear", json={"role": "query"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "cleared": "query",
        "was_loaded": False,
    }
    # A state removal is not a state write (finding N4).
    assert len(api_server.store) == 0
    assert response.headers.get("set-cookie") is None


def test_clear_removes_the_dataset_and_any_derived_result(client):
    assert client.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200
    assert client.post("/api/execute", json={}).status_code == 200
    assert client.get("/api/results/data").status_code == 200

    cleared = client.post("/api/dataset/clear", json={"role": "query"})
    assert cleared.status_code == 200
    assert cleared.json()["was_loaded"] is True

    # The pipeline cannot run without the query, and the result derived
    # from it is gone (a stale result must not be servable, finding F5).
    assert client.post("/api/execute", json={}).status_code == 400
    assert client.get("/api/results/data").status_code == 404
    assert client.get("/api/export/csv").status_code == 404

    # The other role is untouched: re-uploading a query makes the
    # pipeline runnable again.
    assert _upload_query(client, "0-based").status_code == 200
    assert client.post("/api/execute", json={}).status_code == 200


def test_reupload_after_clear_uses_the_new_declaration(client):
    """The reviewer's N2 reproduction, at the API boundary.

    An extension-neutral BED-like .tsv is uploaded as 0-based; the user
    then changes the declaration to 1-based. Before the fix, the stored
    table kept the stale 0-based normalization; after the fix the
    declaration change clears it and the re-upload re-normalizes.
    """
    assert client.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200

    first = _upload_query(client, "0-based")
    assert first.status_code == 200
    rows = [(r["start"], r["end"]) for r in first.json()["preview"]]
    assert rows == [(10, 20), (30, 40)]

    # The declaration changes: the stored copy is invalidated.
    cleared = client.post("/api/dataset/clear", json={"role": "query"})
    assert cleared.json()["was_loaded"] is True
    assert client.post("/api/execute", json={}).status_code == 400

    # Re-upload of the same bytes under the new declaration: 1-based
    # inclusive [S, E] becomes 0-based half-open [S-1, E).
    second = _upload_query(client, "1-based")
    assert second.status_code == 200
    rows = [(r["start"], r["end"]) for r in second.json()["preview"]]
    assert rows == [(9, 20), (29, 40)]

    # And execution now runs on the re-normalized table.
    assert client.post("/api/execute", json={}).status_code == 200