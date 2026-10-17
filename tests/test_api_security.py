"""Endpoint-boundary security tests for the FastAPI backend.

These tests exercise the two Task 14.1 objectives at the HTTP boundary:

* uploaded files are stored under server-generated names (no path traversal);
* request state is isolated per session (no cross-user read or overwrite).
"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import (
    SECURE_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SessionStore,
    safe_extension,
)
from streamlit_app.utils import get_example_data_path


def _example_bytes(name: str) -> bytes:
    return Path(get_example_data_path(name)).read_bytes()


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Give every test its own session store (no state bleed between tests)."""
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def https_client():
    """A client speaking TLS end-to-end (cookie jar honours Secure)."""
    return TestClient(app, base_url="https://testserver")


# ---------------------------------------------------------------------------
# Session cookie generation / transmission
# ---------------------------------------------------------------------------


def test_session_cookie_is_httponly_samesite_lax_over_http(client):
    # A state-changing request creates the session (stateless reads do not,
    # review finding F7).
    response = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200

    raw = response.headers.get("set-cookie")
    assert raw is not None
    assert f"{SESSION_COOKIE_NAME}=" in raw
    lowered = raw.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "secure" not in lowered


def test_session_cookie_is_secure_behind_tls_proxy(client):
    response = client.post(
        "/api/load-sample",
        data={"sample_id": "gene_overlap"},
        headers={"x-forwarded-proto": "https"},
    )
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_session_token_is_unpredictable_and_not_reused(client):
    client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    first = client.cookies.get(SESSION_COOKIE_NAME)
    other = TestClient(app)
    other.cookies.pop(SESSION_COOKIE_NAME, None)
    other.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    second = other.cookies.get(SESSION_COOKIE_NAME)
    assert first and second
    assert first != second
    assert len(first) >= 32


# ---------------------------------------------------------------------------
# __Host- session cookie over HTTPS (review finding N1)
# ---------------------------------------------------------------------------


def test_https_issues_host_prefixed_secure_cookie(https_client):
    response = https_client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200

    raw = response.headers["set-cookie"]
    # Exactly one cookie is issued, under the __Host- name (the unprefixed
    # name must not ride along on the TLS path).
    assert raw.split("=", 1)[0] == SECURE_SESSION_COOKIE_NAME
    lowered = raw.lower()
    assert "secure" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    # __Host- cookies must carry no Domain attribute.
    assert "domain=" not in lowered


def test_https_ignores_unprefixed_cookie_even_with_live_token(https_client):
    # A page served from a sibling subdomain over HTTPS (or any off-origin
    # content that somehow learned the token) can present the token under
    # the unprefixed cookie name. Over TLS the server must not read it, so
    # the request cannot be fixated on the victim's session.
    owner = TestClient(app, base_url="https://testserver")
    created = owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert created.status_code == 200
    assert owner.post("/api/execute", json={}).status_code == 200
    live_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert live_token

    intruder = TestClient(app, base_url="https://testserver")
    intruder.cookies.set(SESSION_COOKIE_NAME, live_token)
    response = intruder.get("/api/results/data")
    assert response.status_code == 404
    assert response.headers.get("set-cookie") is None

    # The planted cookie touched neither the store nor the victim's state.
    assert len(api_server.store) == 1
    assert owner.get("/api/results/data").status_code == 200


def test_https_write_with_only_unprefixed_cookie_gets_fresh_session(https_client):
    # The review's required regression: under HTTPS a request whose only
    # cookie is the unprefixed name receives a fresh __Host- session, never
    # the session that name identifies.
    owner = TestClient(app, base_url="https://testserver")
    owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    owner_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert owner_token

    https_client.cookies.set(SESSION_COOKIE_NAME, owner_token)
    created = https_client.post("/api/load-sample", data={"sample_id": "stranded_features"})
    assert created.status_code == 200

    issued = https_client.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert issued and issued != owner_token
    assert https_client.cookies.get(SESSION_COOKIE_NAME) == owner_token  # still the planted one
    assert len(api_server.store) == 2
    # Both sessions remain independent: the fresh session can execute on its
    # own data, and the owner's is untouched.
    assert https_client.post("/api/execute", json={}).status_code == 200
    assert owner.post("/api/execute", json={}).status_code == 200


def test_host_cookie_presented_over_http_is_not_honoured(client):
    # Symmetry: the server must not honour the __Host- cookie over cleartext
    # either, so a stolen token value cannot be replayed on an HTTP origin.
    owner = TestClient(app, base_url="https://testserver")
    owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    owner.post("/api/execute", json={})
    live_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert live_token

    client.cookies.set(SECURE_SESSION_COOKIE_NAME, live_token)
    assert client.get("/api/results/data").status_code == 404
    assert len(api_server.store) == 1
    assert owner.get("/api/results/data").status_code == 200


# ---------------------------------------------------------------------------
# Session state isolation
# ---------------------------------------------------------------------------


def test_state_persists_across_requests_for_one_client(client):
    assert (
        client.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code
        == 200
    )
    execute = client.post("/api/execute", json={})
    assert execute.status_code == 200
    assert execute.json()["stats"]["query_count"] > 0
    assert client.get("/api/results/data").status_code == 200


def test_two_clients_do_not_share_state():
    a = TestClient(app)
    b = TestClient(app)

    assert a.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200

    # b never loaded anything and must not see a's datasets.
    assert b.post("/api/execute", json={}).status_code == 400
    assert b.get("/api/results/data").status_code == 404
    assert b.get("/api/export/csv").status_code == 404

    # Anonymous (cookie-less) requests never allocate a stored session or
    # receive a cookie: capacity is consumed only on the first state write
    # (review finding N4).
    assert b.cookies.get(SESSION_COOKIE_NAME) is None
    assert len(api_server.store) == 1

    token_a = a.cookies.get(SESSION_COOKIE_NAME)
    assert token_a

    assert a.post("/api/execute", json={}).status_code == 200
    rows_before = a.get("/api/results/data").json()["total_rows"]

    # b's own work must not affect a's stored results.
    assert (
        b.post("/api/load-sample", data={"sample_id": "closest_variants"}).status_code
        == 200
    )
    token_b = b.cookies.get(SESSION_COOKIE_NAME)
    assert token_b and token_b != token_a
    assert b.post("/api/execute", json={"mode": "closest"}).status_code == 200

    assert a.get("/api/results/data").json()["total_rows"] == rows_before


def test_unknown_cookie_token_is_ignored_and_replaced(client):
    from streamlit_app import api_server

    client.cookies.set(SESSION_COOKIE_NAME, "forged-token-value")
    # A stateless read with an unknown token reads nothing and, under the
    # stateless-read contract (review finding F7), must not allocate a
    # stored session or issue a replacement cookie.
    response = client.get("/api/results/data")
    assert response.status_code == 404
    assert response.headers.get("set-cookie") is None
    assert len(api_server.store) == 0

    # A state-changing request with the forged token gets a fresh session
    # that replaces the forged cookie.
    created = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert created.status_code == 200
    issued = created.headers.get("set-cookie")
    assert issued is not None
    assert "forged-token-value" not in issued


def test_sessions_loaded_for_different_samples_stay_distinct():
    a = TestClient(app)
    b = TestClient(app)
    a.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    b.post("/api/load-sample", data={"sample_id": "stranded_features"})

    stats_a = a.post("/api/execute", json={}).json()["stats"]
    stats_b = b.post("/api/execute", json={}).json()["stats"]

    assert stats_a["query_count"] > 0
    assert stats_b["query_count"] > 0
    assert stats_a["result_count"] == stats_a["result_count"]
    assert stats_a != stats_b


# ---------------------------------------------------------------------------
# Upload path safety
# ---------------------------------------------------------------------------


def test_upload_absolute_filename_cannot_write_outside_storage(tmp_path, client):
    target = tmp_path / "pwned.bed"
    target.write_bytes(b"SENTINEL")

    response = client.post(
        "/api/upload",
        files={"file": (str(target), _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )

    assert response.status_code == 200, response.text
    # The server received the absolute path verbatim, so the old
    # `Path(temp_dir) / filename` join would have written to `target`.
    assert response.json()["filename"] == str(target)
    assert target.read_bytes() == b"SENTINEL"


def test_upload_dotdot_filename_cannot_escape_storage(tmp_path, monkeypatch, client):
    monkeypatch.chdir(tmp_path)
    response = client.post(
        "/api/upload",
        files={"file": ("../../../pwned.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 200, response.text
    assert not (tmp_path / "pwned.bed").exists()
    assert not (tmp_path.parent / "pwned.bed").exists()


def test_upload_preserves_valid_extension_and_parses(client):
    response = client.post(
        "/api/upload",
        files={"file": ("strange name.gff3", _example_bytes("example_annotations.gff3"))},
        data={"role": "annot"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "gff"
    assert body["needs_mapping"] is False
    assert body["filename"] == "strange name.gff3"


def test_upload_without_extension_parses_by_content(client):
    response = client.post(
        "/api/upload",
        files={"file": ("coords", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["format"] == "bed"


def test_upload_rejects_invalid_role(client):
    response = client.post(
        "/api/upload",
        files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "admin"},
    )
    assert response.status_code == 400


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(
        api_server.Settings, "get_max_file_size_bytes", classmethod(lambda cls: 8)
    )
    response = client.post(
        "/api/upload",
        files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 413


def test_upload_error_does_not_leak_server_paths(client):
    response = client.post(
        "/api/upload",
        files={"file": ("broken.bed", b"\x00\x01not a genomic file\x02")},
        data={"role": "query"},
    )
    assert response.status_code in (400, 422)
    detail = response.json().get("detail", "")
    assert "annotater-upload-" not in detail
    assert "/tmp/" not in detail


def test_uploaded_state_is_session_scoped():
    a = TestClient(app)
    b = TestClient(app)
    assert (
        a.post(
            "/api/upload",
            files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
            data={"role": "query"},
        ).status_code
        == 200
    )
    assert (
        a.post(
            "/api/upload",
            files={"file": ("a.gff3", _example_bytes("example_annotations.gff3"))},
            data={"role": "annot"},
        ).status_code
        == 200
    )
    assert a.post("/api/execute", json={}).status_code == 200

    # b uploaded nothing; a's uploaded state must be invisible to b.
    assert b.post("/api/execute", json={}).status_code == 400
    assert b.get("/api/results/data").status_code == 404


# ---------------------------------------------------------------------------
# SessionStore unit behaviour
# ---------------------------------------------------------------------------


def test_safe_extension_accepts_only_safe_suffixes():
    assert safe_extension("regions.bed") == ".bed"
    assert safe_extension("features.gff3") == ".gff3"
    assert safe_extension("path/to/features.vcf") == ".vcf"
    assert safe_extension("windows\\path\\x.bed") == ".bed"
    assert safe_extension("noext") == ""
    assert safe_extension(None) == ""
    assert safe_extension("evil...") == ""
    assert safe_extension("evil.b/e/d") == ""
    assert safe_extension("spaces in name.bed") == ".bed"


def test_safe_extension_rejects_path_components_and_overlong():
    assert safe_extension("x.tar.gz") == ".gz"
    assert safe_extension("x.verylongextension") == ""
    assert safe_extension("x.bed/../etc") == ""


def test_store_expires_idle_sessions():
    store = SessionStore(ttl_seconds=10)
    session = store.create(now=100)
    assert store.get(session.token, now=105) is session
    assert store.get(session.token, now=200) is None
    assert len(store) == 0


def test_store_drop_only_affects_target_session():
    store = SessionStore()
    first = store.create()
    second = store.create()
    store.drop(first.token)
    assert store.get(first.token) is None
    assert store.get(second.token) is second


def test_store_is_bounded_and_evicts_oldest():
    store = SessionStore(max_sessions=3)
    sessions = [store.create(now=float(i)) for i in range(3)]
    store.get(sessions[0].token, now=3.0)
    newest = store.create(now=4.0)

    assert len(store) == 3
    assert store.get(sessions[1].token, now=5.0) is None
    assert store.get(sessions[0].token, now=5.0) is not None
    assert store.get(newest.token, now=5.0) is not None


def test_store_handles_concurrent_access():
    store = SessionStore(max_sessions=10_000)
    created = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            session = store.create()
            session.data["x"] = 1
            with lock:
                created.append(session.token)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == len(set(created)) == 400
    assert len(store) == 400
