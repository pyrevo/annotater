"""Docker-gated integration tests for the built production image (Task 14.6).

These tests run the *built* image end to end.  They are skipped unless the
``ANNOTATER_TEST_IMAGE`` environment variable names an image tag and a Docker
daemon is available, so the default test run stays hermetic:

    docker build --platform linux/amd64 -t annotater:ci .
    ANNOTATER_TEST_IMAGE=annotater:ci pytest tests/test_container_image.py

The static container contract (Dockerfile/compose/entrypoint invariants) is
covered without Docker by ``tests/test_container_contract.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

IMAGE = os.environ.get("ANNOTATER_TEST_IMAGE")
_HAS_DOCKER = shutil.which("docker") is not None

pytestmark = pytest.mark.skipif(
    not IMAGE or not _HAS_DOCKER,
    reason=(
        "container integration tests require Docker and ANNOTATER_TEST_IMAGE "
        "(e.g. ANNOTATER_TEST_IMAGE=annotater:ci)"
    ),
)


def _docker_run(
    opts: list[str], command: list[str], *, timeout: int = 1200
) -> subprocess.CompletedProcess:
    assert IMAGE is not None
    # Docker requires the image before the command: run [OPTS] IMAGE [CMD].
    return subprocess.run(
        ["docker", "run", "--rm", *opts, IMAGE, *command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _assert_ok(proc: subprocess.CompletedProcess, label: str) -> None:
    assert proc.returncode == 0, (
        f"{label} failed (exit {proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


def test_image_scientific_core_smoke():
    proc = _docker_run(
        ["--entrypoint", "bash"], ["/app/scripts/docker_smoke.sh"]
    )
    _assert_ok(proc, "scientific-core smoke")
    assert "SMOKE PASS" in proc.stdout


def test_image_scientific_runtime_works_fully_offline():
    proc = _docker_run(
        ["--network", "none", "--entrypoint", "python"],
        ["/app/scripts/offline_smoke.py"],
    )
    _assert_ok(proc, "network-disabled scientific smoke")
    assert "OFFLINE SMOKE PASS" in proc.stdout


def test_image_served_application_smoke():
    proc = _docker_run(
        ["--entrypoint", "bash"], ["/app/scripts/docker_smoke_api.sh"]
    )
    _assert_ok(proc, "served-application smoke")
    assert "API SMOKE PASS" in proc.stdout


def test_image_runs_as_non_root_uid_1000():
    proc = _docker_run(["--entrypoint", "id"], ["-u"])
    _assert_ok(proc, "non-root uid check")
    assert proc.stdout.strip() == "1000"


def test_image_ships_the_built_frontend_assets():
    proc = _docker_run(
        ["--entrypoint", "bash"],
        ["-c", "test -f /app/frontend/dist/index.html"],
    )
    _assert_ok(proc, "frontend dist present")


def test_image_declares_the_fastapi_healthcheck():
    assert IMAGE is not None
    proc = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{json .Config.Healthcheck}}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "localhost:8000/health" in proc.stdout
