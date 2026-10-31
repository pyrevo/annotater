"""Contract for the HTTP browser search regression of the Zensical build.

Static and harness tests always run. The real-browser tests need Playwright with
Chromium and the pinned Zensical; when those are absent they are *skipped with a
reason* (never reported as passing), unless DOCS_SEARCH_REQUIRE_BROWSER=1, in
which case missing prerequisites are a failure.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_docs_search.py"

_spec = importlib.util.spec_from_file_location("check_docs_search", SCRIPT)
search = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = search  # dataclasses resolve their module through sys.modules
_spec.loader.exec_module(search)

REQUIRE = os.environ.get("DOCS_SEARCH_REQUIRE_BROWSER") == "1"


# --- static contract --------------------------------------------------------


def test_browser_dependency_is_pinned_and_separate():
    lines = [
        l for l in (ROOT / "docs" / "requirements-docs-browser.txt").read_text("utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    assert len(lines) == 1 and re.fullmatch(r"playwright==\d+\.\d+\.\d+", lines[0])
    zensical = (ROOT / "docs" / "requirements-zensical.txt").read_text("utf-8")
    assert "playwright" not in zensical and "zensical==0.0.73" in zensical


def test_script_uses_roles_not_material_selectors_and_no_fixed_sleeps():
    source = SCRIPT.read_text("utf-8")
    assert "get_by_role(\"combobox\")" in source and "get_by_role(\"option\")" in source
    for forbidden in ("md-search__input", "md-search-result", "wait_for_timeout", "time.sleep"):
        assert forbidden not in source, forbidden


# --- harness behaviour (no browser needed) -----------------------------------


def test_server_uses_an_ephemeral_port_serves_files_and_shuts_down(tmp_path):
    (tmp_path / "index.html").write_text("<p>hi</p>", "utf-8")
    (tmp_path / "empty").mkdir()
    with search.serving(tmp_path) as base:
        assert base.startswith("http://127.0.0.1:") and not base.endswith(":80/")
        assert urllib.request.urlopen(base).status == 200
        with pytest.raises(urllib.error.HTTPError) as listing:  # no directory listing
            urllib.request.urlopen(base + "empty/")
        assert listing.value.code == 404
    with pytest.raises(OSError):
        urllib.request.urlopen(base, timeout=2)


def test_server_is_shut_down_even_when_the_body_raises(tmp_path):
    (tmp_path / "index.html").write_text("x", "utf-8")
    with pytest.raises(RuntimeError, match="boom"):
        with search.serving(tmp_path) as base:
            raise RuntimeError("boom")
    with pytest.raises(OSError):
        urllib.request.urlopen(base, timeout=2)


def _fake_site(root: Path) -> Path:
    (root / "technical" / "registry").mkdir(parents=True)
    (root / "index.html").write_text('<script src="./assets/a.js"></script><p>home</p>', "utf-8")
    (root / "404.html").write_text("x", "utf-8")
    (root / "technical" / "registry" / "index.html").write_text("page", "utf-8")
    (root / "search.json").write_text(json.dumps({"config": {"k": 1}, "items": [{"t": "a"}]}), "utf-8")
    return root


def test_mutations_change_the_site_as_described(tmp_path):
    site = _fake_site(tmp_path / "s")
    search._empty_index(site)
    assert json.loads((site / "search.json").read_text())["items"] == []
    assert json.loads((site / "search.json").read_text())["config"] == {"k": 1}
    search._no_javascript(site)
    assert "<script" not in (site / "index.html").read_text() and "home" in (site / "index.html").read_text()
    search._unreachable_results(site)
    assert (site / "index.html").exists() and (site / "404.html").exists()
    assert not (site / "technical" / "registry" / "index.html").exists()
    search._missing_index(site)
    assert not (site / "search.json").exists()


def test_every_mutation_names_a_distinct_expected_failure():
    assert set(search.MUTATIONS) == {
        "search.json missing",
        "search.json without entries",
        "search interface cannot be activated",
        "result cannot be navigated to",
    }
    assert all(expected for _, expected in search.MUTATIONS.values())


def test_missing_browser_is_exit_status_2_not_success(monkeypatch, tmp_path, capsys):
    (tmp_path / "index.html").write_text("x", "utf-8")

    def unavailable(*args, **kwargs):
        raise search.BrowserUnavailable("no chromium")

    monkeypatch.setattr(search, "check_site", unavailable)
    monkeypatch.setattr("sys.argv", ["check_docs_search.py", "--site", str(tmp_path)])
    assert search.main() == 2
    assert "cannot run the browser check" in capsys.readouterr().err


# --- real browser against a real Zensical build ------------------------------


def _unavailable(reason: str):
    if REQUIRE:
        pytest.fail(f"DOCS_SEARCH_REQUIRE_BROWSER=1 but: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def built_site(tmp_path_factory) -> Path:
    if shutil.which("zensical") is None:
        _unavailable("zensical (docs/requirements-zensical.txt) is not installed")
    try:
        search._import_playwright()
    except search.BrowserUnavailable as exc:
        _unavailable(str(exc))
    work = tmp_path_factory.mktemp("zensical-src")
    shutil.copytree(ROOT / "docs", work / "docs")
    shutil.copy(ROOT / "mkdocs.yml", work / "mkdocs.yml")
    env = {**os.environ, "NO_MKDOCS_2_WARNING": "1"}
    subprocess.run(["zensical", "build", "--clean", "--strict"], cwd=work, env=env, check=True)
    return work / "site"


def _check(site: Path) -> list[str]:
    try:
        return search.check_site(site, timeout_ms=4000)
    except search.BrowserUnavailable as exc:
        _unavailable(str(exc))
        return []


def test_real_site_search_works_over_http_on_desktop_and_mobile(built_site):
    assert _check(built_site) == []


@pytest.mark.parametrize("name", list(search.MUTATIONS))
def test_browser_check_fails_on_broken_copies(built_site, tmp_path, name):
    mutate, expected = search.MUTATIONS[name]
    copy = tmp_path / "site"
    shutil.copytree(built_site, copy)
    mutate(copy)
    problems = _check(copy)
    assert any(expected in p for p in problems), problems


def test_search_self_test_never_modifies_the_checked_site(built_site):
    def digest(root: Path) -> str:
        h = hashlib.sha256()
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            h.update(path.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(path.read_bytes()).digest())
        return h.hexdigest()

    before = digest(built_site)
    try:
        failures = search.self_test(built_site, search.TERM, 3000)
    except search.BrowserUnavailable as exc:
        _unavailable(str(exc))
        return
    assert failures == []
    assert digest(built_site) == before
