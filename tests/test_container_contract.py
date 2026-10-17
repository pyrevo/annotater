"""Static contract tests for the production container artefacts (Task 14.6).

These tests do not need Docker.  They pin the container's security and
deployment contract to the repository files so that a future edit cannot
silently regress it:

* the image installs dependencies from ``uv.lock`` with hash verification
  (never an unverified ``pip install -r requirements.txt``);
* it runs as the non-root ``appuser`` (UID 1000, the SciLifeLab Serve
  standard);
* the healthcheck targets the FastAPI ``/health`` route, on the port the
  entrypoint actually serves (8000);
* ``start-script.sh`` serves ``streamlit_app.api_server:app`` with a single
  Uvicorn worker and forwarded-header support (the in-memory session model
  requires one worker; the TLS proxy requires forwarded headers);
* every ``COPY`` of a local file in the Dockerfile references a file that
  exists, so the image cannot fail to build on a missing smoke script.

The behaviour of the *built* image is covered separately by
``tests/test_container_image.py`` (Docker-gated) and the in-container smoke
scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
START_SCRIPT = REPO_ROOT / "start-script.sh"
COMPOSE = REPO_ROOT / "docker-compose.yml"
OFFLINE_SMOKE = REPO_ROOT / "scripts" / "offline_smoke.py"
API_SMOKE = REPO_ROOT / "scripts" / "docker_smoke_api.sh"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected container artefact at {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return _read(DOCKERFILE)


# --- dependency integrity -------------------------------------------------

def test_dependencies_install_from_the_lockfile_with_hash_verification(dockerfile):
    assert "uv export --frozen" in dockerfile, "image must export the frozen uv.lock"
    assert "--require-hashes" in dockerfile, "install must verify artifact hashes"
    assert "--no-deps" in dockerfile, "frozen requirements must not be re-resolved"


def test_image_does_not_install_unverified_requirements(dockerfile):
    # A plain `pip install -r requirements.txt` would bypass uv.lock hashes.
    assert "pip install -r requirements.txt" not in dockerfile
    assert "-r requirements.txt" not in dockerfile


def test_dev_dependencies_are_excluded_from_the_runtime_image(dockerfile):
    assert "--no-dev" in dockerfile, "runtime image must not install the dev extra"


# --- non-root / platform --------------------------------------------------

def test_image_runs_as_the_non_root_serve_user(dockerfile):
    assert re.search(r"^USER\s+appuser\s*$", dockerfile, re.MULTILINE)
    assert "useradd -u 1000" in dockerfile, "SciLifeLab Serve expects UID 1000"
    assert re.search(r"^USER\s+root", dockerfile, re.MULTILINE) is None


def test_image_pins_the_amd64_runtime_platform(dockerfile):
    assert "ARG PLATFORM=linux/amd64" in dockerfile
    assert "FROM --platform=${PLATFORM} python:3.12-slim" in dockerfile


# --- serving / healthcheck ------------------------------------------------

def test_exposes_the_fastapi_port_and_not_the_legacy_streamlit_port(dockerfile):
    assert re.search(r"^EXPOSE\s+8000\s*$", dockerfile, re.MULTILINE)
    assert re.search(r"^EXPOSE\s+8501", dockerfile, re.MULTILINE) is None


def test_healthcheck_hits_the_fastapi_health_route(dockerfile):
    healthcheck = re.search(r"^HEALTHCHECK.*(?:\n\s+.*)*", dockerfile, re.MULTILINE)
    assert healthcheck, "Dockerfile declares no HEALTHCHECK"
    block = healthcheck.group(0)
    assert "localhost:8000/health" in block
    assert "/api/metadata" not in block, "stale healthcheck path"


def test_entrypoint_is_the_serve_startup_script(dockerfile):
    assert 'ENTRYPOINT ["./start-script.sh"]' in dockerfile


# --- entrypoint contract --------------------------------------------------

def test_start_script_serves_the_api_app_on_the_single_worker_model():
    script = _read(START_SCRIPT)
    assert "uvicorn streamlit_app.api_server:app" in script
    assert "--host 0.0.0.0" in script
    assert 'PORT="${PORT:-8000}"' in script
    # Ignore comments: the script *warns* against --workers in a comment.
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    workers = re.search(r"--workers\s+\S+", code)
    assert workers is None, "in-memory sessions forbid a multi-worker deployment"


def test_start_script_forwards_proxy_headers_for_the_tls_terminator():
    script = _read(START_SCRIPT)
    assert "--proxy-headers" in script
    assert "forwarded-allow-ips" in script


# --- compose parity -------------------------------------------------------

def test_compose_healthcheck_matches_the_image_contract():
    compose = _read(COMPOSE)
    assert "localhost:8000/health" in compose
    assert "/api/metadata" not in compose, "stale compose healthcheck path"


# --- build inputs exist ---------------------------------------------------

def test_dockerfile_only_copies_files_that_exist(dockerfile):
    missing: list[str] = []
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not line.upper().startswith("COPY"):
            continue
        parts = line.split()[1:]
        # Skip --from=... / --chown=... and URL sources.
        sources = [p for p in parts[:-1] if not p.startswith("--")]
        if any("--from=" in p for p in parts):
            continue
        for src in sources:
            if src.startswith(("http://", "https://")):
                continue
            if not (REPO_ROOT / src).exists():
                missing.append(src)
    assert not missing, f"Dockerfile COPY sources missing from the repo: {missing}"


def test_smoke_scripts_are_shipped_in_the_image(dockerfile):
    assert "COPY scripts/docker_smoke_api.sh" in dockerfile
    assert "COPY scripts/offline_smoke.py" in dockerfile


def test_offline_smoke_forces_the_network_off():
    script = _read(OFFLINE_SMOKE)
    assert "socket.socket.connect = _blocked" in script
    assert "socket.create_connection = _blocked" in script


def test_api_smoke_does_not_start_the_legacy_streamlit_server():
    script = _read(API_SMOKE)
    assert "/app/start-script.sh" in script
    assert "8501" not in script
    assert "streamlit run" not in script
