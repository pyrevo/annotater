"""Contract for the experimental parallel Zensical documentation build (M3.1b).

Static checks pin the workflow/dependency/config guarantees (the Material build
and Pages deployment are untouched; the Zensical job never publishes). The
checker's own behaviour is exercised on tiny synthetic sites. A real-build test
runs when both builders are installed and is skipped, with the reason, if not.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yaml"
CHECKER = ROOT / "scripts" / "check_docs_site.py"
INVENTORY = ROOT / "tests" / "fixtures" / "docs_site_pages.txt"

_spec = importlib.util.spec_from_file_location("check_docs_site", CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]


# --- static contract -------------------------------------------------------


def test_zensical_requirements_are_pinned_and_material_is_kept():
    zen = (ROOT / "docs" / "requirements-zensical.txt").read_text("utf-8")
    lines = [l for l in zen.splitlines() if l.strip() and not l.startswith("#")]
    assert lines == ["zensical==0.0.73"]
    material = (ROOT / "docs" / "requirements-docs.txt").read_text("utf-8")
    assert "mkdocs-material>=9.5,<10" in material


def test_mkdocs_config_sets_classic_variant_and_nothing_else_in_theme():
    config = (ROOT / "mkdocs.yml").read_text("utf-8")
    assert re.search(r"^theme:\n  name: material\n(?:  #.*\n)*  variant: classic\n", config, re.M)


def test_material_build_and_deploy_jobs_are_unchanged():
    jobs = _jobs()
    assert set(jobs) == {"build", "deploy", "docs-zensical"}
    build_runs = [s.get("run") for s in jobs["build"]["steps"]]
    assert "mkdocs build --strict" in build_runs
    assert jobs["deploy"]["needs"] == "build"
    assert jobs["deploy"]["if"] == "github.event_name == 'push' && vars.DOCS_PUBLISH == 'true'"


def test_zensical_job_is_pr_only_unprivileged_and_never_publishes():
    jobs = _jobs()
    job = jobs["docs-zensical"]
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["permissions"] == {"contents": "read"}
    uses = [s.get("uses", "") for s in job["steps"]]
    assert not any("pages" in u for u in uses)
    assert any(u.startswith("actions/upload-artifact@") for u in uses)
    assert "environment" not in job
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "zensical build --clean --strict" in runs
    assert "requirements-zensical.txt" in runs
    for name, other in jobs.items():
        assert "docs-zensical" not in str(other.get("needs", "")), name


def test_zensical_job_is_not_an_application_ci_gate_dependency():
    gate = yaml.safe_load((ROOT / ".github" / "workflows" / "python-tests.yml").read_text("utf-8"))
    needs = gate["jobs"]["ci-gate"]["needs"]
    assert "docs-zensical" not in needs


def test_pinned_inventory_is_46_unique_sorted_pages():
    pages = INVENTORY.read_text("utf-8").split()
    assert len(pages) == 46 == len(set(pages))
    assert pages == sorted(pages)
    assert "index.html" in pages and "404.html" in pages


def test_inventory_covers_every_nav_page():
    nav = (ROOT / "mkdocs.yml").read_text("utf-8")
    pages = set(INVENTORY.read_text("utf-8").split())
    for md in re.findall(r":\s+([\w/.-]+\.md)\s*$", nav, re.M):
        stem = md[:-3]
        expected = "index.html" if md == "index.md" else f"{stem}/index.html"
        assert expected in pages, md


# --- checker behaviour on synthetic sites ----------------------------------


def _page(body: str) -> str:
    return f"<html><body><article>{body}</article></body></html>"


def _site(root: Path, pages: dict[str, str], search: object = None) -> Path:
    for name, body in pages.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_page(body), "utf-8")
    if search is not None:
        (root / "search.json").write_text(json.dumps(search), "utf-8")
    return root


def test_links_resolve_with_directory_urls_and_anchors(tmp_path):
    site = _site(
        tmp_path,
        {
            "index.html": '<a href="a/">a</a><a href="a/#top-x">x</a><a href="https://e.org/">e</a>',
            "a/index.html": '<h2 id="top-x">x</h2><a href="../">home</a><a href="#top-x">s</a>',
        },
    )
    assert checker.check_links(site) == []


def test_links_report_missing_page_and_missing_anchor(tmp_path):
    site = _site(
        tmp_path,
        {
            "index.html": '<a href="gone/">g</a><a href="a/#nope">n</a>',
            "a/index.html": '<h2 id="ok">x</h2>',
        },
    )
    errors = checker.check_links(site)
    assert len(errors) == 2
    assert any("missing gone/index.html" in e for e in errors)
    assert any("missing anchor" in e for e in errors)


def test_content_anchors_ignore_theme_internal_ids():
    html_ = _page('<h2 id="real">r</h2><span id="__toc"></span>')
    assert checker.content_anchors(html_) == {"real"}


def test_normalized_text_ignores_highlight_markup_and_spacing():
    plain = _page("<pre><code>docker build -p 80:80</code></pre>")
    highlighted = _page(
        '<div class="highlight"><pre><span></span><code>docker<span class="w"> </span>'
        "build -p 80<span class='o'>:</span>80\n</code></pre></div>"
    )
    assert checker.normalized_text(plain) == checker.normalized_text(highlighted)
    assert checker.normalized_text(plain) != checker.normalized_text(_page("<p>other</p>"))


def test_leaked_fence_words_are_the_only_tolerated_difference():
    assert checker.only_leaked_fence_words("exampletextchr1", "examplechr1")
    assert not checker.only_leaked_fence_words("examplechr1", "exampleXchr1")
    assert not checker.only_leaked_fence_words("exampletextchr1", "examplechr2")
    assert not checker.only_leaked_fence_words("exampletextchr1", "exchr1")


def test_check_flags_inventory_text_anchor_and_search_regressions(tmp_path, monkeypatch):
    inventory = tmp_path / "inv.txt"
    inventory.write_text("index.html\n")
    monkeypatch.setattr(checker, "INVENTORY", inventory)
    ref = _site(tmp_path / "ref", {"index.html": '<h2 id="a">Hello</h2>'})
    good = _site(tmp_path / "good", {"index.html": '<h2 id="a">Hello</h2>'}, {"items": [{"t": 1}]})
    assert checker.check(good, ref) == []

    bad_text = _site(tmp_path / "t", {"index.html": '<h2 id="a">Changed</h2>'}, {"items": [1]})
    assert any("article text differs" in e for e in checker.check(bad_text, ref))
    bad_anchor = _site(tmp_path / "an", {"index.html": '<h2 id="b">Hello</h2>'}, {"items": [1]})
    assert any("anchors differ" in e for e in checker.check(bad_anchor, ref))
    extra = _site(tmp_path / "x", {"index.html": "<p>Hello</p>", "new/index.html": ""}, {"items": [1]})
    assert any("inventory differs" in e for e in checker.check(extra, ref))
    no_search = _site(tmp_path / "s", {"index.html": '<h2 id="a">Hello</h2>'}, {"items": []})
    assert any("no entries" in e for e in checker.check(no_search, ref))
    missing = _site(tmp_path / "m", {"index.html": '<h2 id="a">Hello</h2>'})
    assert any("search.json unreadable" in e for e in checker.check(missing, ref))


# --- real builds (skipped with a reason when the builders are absent) -------


@pytest.mark.skipif(
    shutil.which("zensical") is None or shutil.which("mkdocs") is None,
    reason="zensical and mkdocs (docs/requirements-*.txt) are not installed",
)
def test_real_zensical_build_matches_material_reference(tmp_path):
    env_site = tmp_path / "zensical-site"
    material_site = tmp_path / "material-site"
    env = {"NO_MKDOCS_2_WARNING": "1", "PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path)}
    subprocess.run(["mkdocs", "build", "--strict", "-d", str(material_site)], cwd=ROOT, env=env, check=True)
    # Zensical writes to site_dir (site/); build from a copy so the repo stays clean.
    work = tmp_path / "src"
    shutil.copytree(ROOT / "docs", work / "docs")
    shutil.copy(ROOT / "mkdocs.yml", work / "mkdocs.yml")
    subprocess.run(["zensical", "build", "--clean", "--strict"], cwd=work, env=env, check=True)
    shutil.move(str(work / "site"), env_site)
    assert checker.check(env_site, material_site) == []
