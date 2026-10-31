"""Contract for the Zensical documentation build: pins, config, inventory, checker.

Static checks pin the dependency and configuration guarantees; the workflow
guards live in test_docs_production_contract.py. The checker's own behaviour is
exercised on tiny synthetic sites. Real-build tests run when both builders are
installed and are skipped, with the reason, if not (DOCS_SEARCH_REQUIRE_BROWSER=1
turns that skip into a failure).
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_docs_site.py"
INVENTORY = ROOT / "tests" / "fixtures" / "docs_site_pages.txt"

_spec = importlib.util.spec_from_file_location("check_docs_site", CHECKER)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


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
    return (
        '<html><head><link rel="canonical" href="https://e.org/">'
        '<link rel="stylesheet" href="assets/stylesheets/classic/main.css"></head>'
        f"<body><article>{body}</article></body></html>"
    )


def _site(root: Path, pages: dict[str, str], search: object = None) -> Path:
    for name, body in pages.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_page(body), "utf-8")
    (root / "sitemap.xml").write_text("<urlset><url><loc>https://e.org/</loc></url></urlset>", "utf-8")
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


def test_navigation_parser_keeps_order_targets_and_labels():
    page = (
        '<nav class="md-nav md-nav--primary"><ul>'
        '<li><a href="../a/" class="md-nav__link"><span> Alpha </span></a></li>'
        '<li><nav class="md-nav"><a href="#frag" class="md-nav__link">Frag</a></nav></li>'
        '<li><a href="../b/" class="md-nav__link">Beta</a></li></ul></nav>'
        '<nav class="md-nav md-nav--secondary"><a href="x/" class="md-nav__link">Other</a></nav>'
    )
    assert checker.navigation(page, "docs/page/index.html") == [
        ("/docs/a", "Alpha"),
        ("/docs/page#frag", "Frag"),
        ("/docs/b", "Beta"),
    ]


def test_canonical_and_sitemap_helpers(tmp_path):
    assert checker.canonical('<link rel="canonical" href="https://e.org/a/">') == ["https://e.org/a/"]
    assert checker.canonical("<p>none</p>") == []
    (tmp_path / "sitemap.xml").write_text("<urlset><url><loc>b</loc></url><url><loc>a</loc></url></urlset>")
    assert checker.sitemap_urls(tmp_path) == ["a", "b"]
    assert checker.sitemap_urls(tmp_path / "missing") == []


def test_every_structural_mutation_names_a_distinct_expected_failure():
    assert len(checker.MUTATIONS) == 9
    assert len({expected for _, expected in checker.MUTATIONS.values()}) == len(checker.MUTATIONS)


# --- F3: a site is never compared with itself ---------------------------------


@pytest.fixture
def one_page_inventory(tmp_path, monkeypatch):
    inventory = tmp_path / "inventory.txt"
    inventory.write_text("index.html\n")
    monkeypatch.setattr(checker, "INVENTORY", inventory)


def _run_main(monkeypatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["check_docs_site.py", *args])
    return checker.main()


def test_identical_site_and_reference_paths_are_refused(tmp_path, monkeypatch, capsys, one_page_inventory):
    site = _site(tmp_path / "site", {"index.html": "<h2 id='a'>x</h2>"}, {"items": [1]})
    assert _run_main(monkeypatch, "--site", str(site), "--reference", str(site)) == 2
    err = capsys.readouterr().err
    assert "resolve to the same directory" in err and "proves nothing" in err
    with pytest.raises(checker.SelfComparisonError):
        checker.check(site, site)
    with pytest.raises(checker.SelfComparisonError):
        checker.self_test(site, site)


def test_equivalent_relative_and_absolute_spellings_are_refused(tmp_path, monkeypatch, capsys, one_page_inventory):
    _site(tmp_path / "site", {"index.html": "<h2 id='a'>x</h2>"}, {"items": [1]})
    monkeypatch.chdir(tmp_path)
    absolute = str((tmp_path / "site").resolve())
    for site, reference in (
        ("site", absolute),
        (absolute, "site"),
        ("site", "./site"),
        ("site", "site/"),
        ("site", "site/../site"),
        ("./site/../site", absolute + "/."),
    ):
        assert _run_main(monkeypatch, "--site", site, "--reference", reference) == 2, (site, reference)
        assert "resolve to the same directory" in capsys.readouterr().err


def test_symlink_alias_of_the_site_is_refused(tmp_path, monkeypatch, capsys, one_page_inventory):
    site = _site(tmp_path / "site", {"index.html": "<h2 id='a'>x</h2>"}, {"items": [1]})
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(site, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are not supported here: {exc}")
    assert _run_main(monkeypatch, "--site", str(alias), "--reference", str(site)) == 2
    assert _run_main(monkeypatch, "--site", str(site), "--reference", str(alias)) == 2
    chained = tmp_path / "chained"
    chained.symlink_to(alias, target_is_directory=True)
    assert _run_main(monkeypatch, "--site", str(chained), "--reference", str(site)) == 2
    assert capsys.readouterr().err.count("resolve to the same directory") == 3


def test_distinct_site_and_reference_directories_are_compared(tmp_path, monkeypatch, capsys, one_page_inventory):
    site = _site(tmp_path / "site", {"index.html": "<h2 id='a'>Hello</h2>"}, {"items": [1]})
    reference = _site(tmp_path / "reference", {"index.html": "<h2 id='a'>Hello</h2>"})
    assert _run_main(monkeypatch, "--site", str(site), "--reference", str(reference)) == 0
    assert "1 pages checked, 0 problem(s)" in capsys.readouterr().out
    # distinct directories with a real difference are compared (and fail), not refused
    different = _site(tmp_path / "different", {"index.html": "<h2 id='a'>Changed</h2>"})
    assert _run_main(monkeypatch, "--site", str(site), "--reference", str(different)) == 1
    assert "article text differs" in capsys.readouterr().err
    assert checker.refuse_self_comparison(site, reference) is None


def test_missing_reference_directory_is_not_mistaken_for_the_site(tmp_path, one_page_inventory):
    site = _site(tmp_path / "site", {"index.html": "<h2 id='a'>x</h2>"}, {"items": [1]})
    assert checker.refuse_self_comparison(site, tmp_path / "does-not-exist") is None


# --- real builds (skipped with a reason when the builders are absent) -------


def _unavailable(reason: str):
    if os.environ.get("DOCS_SEARCH_REQUIRE_BROWSER") == "1":
        pytest.fail(f"DOCS_SEARCH_REQUIRE_BROWSER=1 but: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def built_sites(tmp_path_factory):
    if shutil.which("zensical") is None or shutil.which("mkdocs") is None:
        _unavailable("zensical and mkdocs (docs/requirements-*.txt) are not installed")
    base = tmp_path_factory.mktemp("docs-sites")
    env = {**os.environ, "NO_MKDOCS_2_WARNING": "1"}
    material_site = base / "material-site"
    subprocess.run(["mkdocs", "build", "--strict", "-d", str(material_site)], cwd=ROOT, env=env, check=True)
    # Zensical writes to site_dir (site/); build from a copy so the repo stays clean.
    work = base / "src"
    shutil.copytree(ROOT / "docs", work / "docs")
    shutil.copy(ROOT / "mkdocs.yml", work / "mkdocs.yml")
    subprocess.run(["zensical", "build", "--clean", "--strict"], cwd=work, env=env, check=True)
    return work / "site", material_site


def test_real_zensical_build_matches_material_reference(built_sites):
    site, material_site = built_sites
    assert checker.check(site, material_site) == []


@pytest.mark.parametrize("name", list(checker.MUTATIONS))
def test_structural_gate_fails_on_broken_copies_of_the_real_site(built_sites, tmp_path, name):
    site, material_site = built_sites
    mutate, expected = checker.MUTATIONS[name]
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    mutate(copy)
    problems = checker.check(copy, material_site)
    assert any(expected in p for p in problems), problems


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def test_structural_self_test_never_modifies_the_checked_site(built_sites, capsys):
    site, material_site = built_sites
    before = _tree_digest(site)
    assert checker.self_test(site, material_site) == []
    assert _tree_digest(site) == before
    assert checker.check(site, material_site) == []
    assert _tree_digest(site) == before
