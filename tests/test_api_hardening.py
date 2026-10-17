"""Task 14.7a (review findings F6, F7, F8) — API availability hardening.

* F6: ``/api/results/data`` page size is bounded at the HTTP boundary.
* F7: stateless GET reads never allocate stored sessions, so anonymous
  traffic cannot evict a real user's state from the bounded store.
* F8: CORS no longer reflects arbitrary origins; only origins listed in the
  ``ANNOTATER_CORS_ORIGINS`` environment variable are approved.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import (
    MAX_PAGE_SIZE,
    _cors_allow_origins,
    app,
)
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


def _seed_result(client, rows) -> str:
    session = api_server.store.create()
    session.data["result"] = {"df": pd.DataFrame(rows)}
    client.cookies.set(SESSION_COOKIE_NAME, session.token)
    return session.token


# ---------------------------------------------------------------------------
# F6 — bounded page size
# ---------------------------------------------------------------------------


class TestPageSizeBound:
    ROWS = [{"coord_chr": f"c{i}", "coord_start": i, "annot_gene": f"g{i}"} for i in range(5)]

    def test_over_cap_page_size_is_rejected(self, client):
        _seed_result(client, self.ROWS)
        response = client.get("/api/results/data", params={"page_size": MAX_PAGE_SIZE + 1})
        assert response.status_code == 422

    def test_at_cap_page_size_is_accepted(self, client):
        _seed_result(client, self.ROWS)
        response = client.get("/api/results/data", params={"page_size": MAX_PAGE_SIZE})
        assert response.status_code == 200, response.text
        assert response.json()["page_size"] == MAX_PAGE_SIZE

    def test_zero_page_size_is_rejected(self, client):
        _seed_result(client, self.ROWS)
        assert client.get("/api/results/data", params={"page_size": 0}).status_code == 422

    def test_negative_page_is_rejected(self, client):
        _seed_result(client, self.ROWS)
        assert client.get("/api/results/data", params={"page": 0}).status_code == 422


# ---------------------------------------------------------------------------
# F7 — stateless reads cannot grow or evict the session store
# ---------------------------------------------------------------------------


class TestStatelessReads:
    def test_stateless_get_creates_no_session_or_cookie(self, client):
        response = client.get("/api/results/data")
        assert response.status_code == 404
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_stateless_export_get_creates_no_session(self, client):
        response = client.get("/api/export/csv")
        assert response.status_code == 404
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_stateless_gene_list_get_creates_no_session(self, client):
        response = client.get("/api/results/gene-list")
        assert response.status_code == 404
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_anonymous_read_flood_cannot_evict_user_sessions(self, client):
        token = _seed_result(client, [{"coord_chr": "c", "coord_start": 1}])

        # Far more anonymous reads than the store can hold.
        flood = TestClient(app)
        for _ in range(3 * 256):
            assert flood.get("/api/results/data").status_code == 404

        assert len(api_server.store) == 1
        assert api_server.store.get(token) is not None
        assert client.get("/api/results/data").status_code == 200

    def test_write_request_still_creates_a_session(self, client):
        response = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
        assert response.status_code == 200
        assert response.headers.get("set-cookie") is not None
        assert len(api_server.store) == 1

    # Review finding N4: session capacity is consumed on the first state
    # write, so anonymous requests that fail validation (or only read) can
    # never evict a real user's session from the bounded store.

    def test_anonymous_failed_writes_cannot_exhaust_the_store(self, monkeypatch, client):
        monkeypatch.setattr(api_server, "store", SessionStore(max_sessions=8))
        token = _seed_result(client, [{"coord_chr": "c", "coord_start": 1}])

        flood = TestClient(app)
        for _ in range(20):
            assert flood.post("/api/execute", json={}).status_code == 400
            assert flood.cookies.get(SESSION_COOKIE_NAME) is None

        assert len(api_server.store) == 1
        assert api_server.store.get(token) is not None
        assert client.get("/api/results/data").status_code == 200

    def test_failed_upload_does_not_allocate_a_session(self, client, monkeypatch):
        monkeypatch.setattr(
            api_server.Settings, "get_max_file_size_bytes", classmethod(lambda cls: 8)
        )
        response = client.post(
            "/api/upload",
            files={"file": ("q.bed", b"0123456789")},
            data={"role": "query"},
        )
        assert response.status_code == 413
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_invalid_role_upload_does_not_allocate_a_session(self, client):
        response = client.post(
            "/api/upload",
            files={"file": ("q.bed", b"chr1\t10\t20\n")},
            data={"role": "admin"},
        )
        assert response.status_code == 400
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_get_with_valid_cookie_still_reads_state(self, client):
        _seed_result(client, [{"coord_chr": "c", "coord_start": 1}])
        response = client.get("/api/results/data")
        assert response.status_code == 200
        assert response.json()["total_rows"] == 1


# ---------------------------------------------------------------------------
# F8 — CORS allowlist, no wildcard reflection
# ---------------------------------------------------------------------------


def _cors_middleware() -> CORSMiddleware:
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, CORSMiddleware):
            return stack
        stack = getattr(stack, "app", None)
    raise AssertionError("CORSMiddleware not found in the app middleware stack")


class TestCorsAllowlist:
    def test_unlisted_origin_is_never_reflected(self, client):
        response = client.get("/health", headers={"Origin": "https://evil.example"})
        assert response.status_code == 200
        # The security property: the Origin is never echoed back as an
        # allowed origin. (ACAC alone, without ACAO, is inert: browsers only
        # honour the credential pair when an allowed origin is present.)
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_for_unlisted_origin_is_not_approved(self, client):
        response = client.options(
            "/api/upload",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in response.headers

    def test_allowlist_env_var_is_parsed(self, monkeypatch):
        monkeypatch.setenv(
            "ANNOTATER_CORS_ORIGINS", "https://a.example, https://b.example ,"
        )
        assert _cors_allow_origins() == ["https://a.example", "https://b.example"]
        monkeypatch.setenv("ANNOTATER_CORS_ORIGINS", "")
        assert _cors_allow_origins() == []
        monkeypatch.delenv("ANNOTATER_CORS_ORIGINS", raising=False)
        assert _cors_allow_origins() == []

    def test_bare_wildcard_is_rejected(self, monkeypatch):
        # With allow_credentials=True a bare "*" would make the middleware
        # reflect every request Origin (review finding N6), so it must be
        # dropped rather than honoured.
        monkeypatch.setenv("ANNOTATER_CORS_ORIGINS", "*")
        assert _cors_allow_origins() == []
        monkeypatch.setenv("ANNOTATER_CORS_ORIGINS", "*, https://a.example")
        assert _cors_allow_origins() == ["https://a.example"]

    def test_listed_origin_is_approved_and_others_are_not(self, client):
        cors = _cors_middleware()
        original = cors.allow_origins
        try:
            cors.allow_origins = ["https://allowed.example"]

            ok = client.get("/health", headers={"Origin": "https://allowed.example"})
            assert ok.headers["access-control-allow-origin"] == "https://allowed.example"
            assert ok.headers["access-control-allow-credentials"] == "true"

            denied = client.get("/health", headers={"Origin": "https://evil.example"})
            assert "access-control-allow-origin" not in denied.headers
        finally:
            cors.allow_origins = original