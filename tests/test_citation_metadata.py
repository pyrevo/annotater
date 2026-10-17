"""Citation metadata contract tests (Task 14.5).

These tests pin the citation facts that are published in several places
(the frontend citation source, README, the release plan, and
``CITATION.cff``) so they cannot silently drift apart. They are
dependency-free: the frontend citation source is checked with regexes
and ``CITATION.cff`` with simple string checks (PyYAML is not a runtime
dependency). Full schema validation of ``CITATION.cff`` is performed by
``cffconvert`` when that tool is available.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CONCEPT_DOI = "10.5281/zenodo.23415801"
VERSION_DOI = "10.5281/zenodo.23415802"
RC3_COMMIT = "7592b9de803ea19cc10042c2a10515c350d4fbfc"
RC3_DIGEST = "sha256:d4ea46ae879c60c34f98fcabd3545e04281dea40ab56f432c0aa2a10a021f661"
RC3_RUN = "37112430397"


def _read(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --- frontend citation source -------------------------------------------


def _js_value(source: str, name: str) -> str:
    match = re.search(rf"{name}:\s*'([^']+)'", source)
    assert match, f"{name!r} not found in frontend/src/citation.js"
    return match.group(1)


def test_frontend_citation_source_has_the_verified_identifiers():
    source = _read("frontend/src/citation.js")
    assert _js_value(source, "conceptDoi") == CONCEPT_DOI
    assert _js_value(source, "versionDoi") == VERSION_DOI
    assert _js_value(source, "version") == "v0.1.0-rc3"
    assert _js_value(source, "title") == "AnnotateR"


def test_frontend_citation_source_preserves_author_order():
    source = _read("frontend/src/citation.js")
    das = source.index("family: 'Das'")
    volpe = source.index("family: 'Volpe'")
    assert das < volpe


# --- README -------------------------------------------------------------


def test_readme_documents_both_dois_and_the_zenodo_badge():
    readme = _read("README.md")
    assert CONCEPT_DOI in readme
    assert VERSION_DOI in readme
    assert f"zenodo.org/badge/DOI/{CONCEPT_DOI}.svg" in readme
    assert "v0.1.0-rc3" in readme


def test_readme_no_longer_claims_rc2_is_latest_published():
    normalized = _normalized(_read("README.md"))
    assert "latest published image is `0.1.0-rc2`" not in normalized
    assert "latest *published* pre-release image (source commit `4edb362" not in normalized
    assert "latest published image is `0.1.0-rc3`" in normalized
    assert "`0.1.0-rc3` is the latest *published* pre-release image" in normalized


# --- docs that describe the latest published image ----------------------


@pytest.mark.parametrize(
    "relpath",
    [
        "docs/index.md",
        "docs/limitations.md",
        "docs/technical/scientific-contract.md",
    ],
)
def test_docs_do_not_reference_rc2(relpath: str):
    assert "0.1.0-rc2" not in _read(relpath)


def test_docs_name_rc3_as_the_latest_published_image():
    assert "`0.1.0-rc3`" in _read("docs/index.md")
    assert "`0.1.0-rc3`" in _read("docs/limitations.md")
    assert "`0.1.0-rc3`" in _read("docs/technical/scientific-contract.md")
    deployment = _normalized(_read("docs/deployment.md"))
    assert "0.1.0-rc3 # release-candidate tag (pre-publication testing; latest published RC)" in deployment


def test_mkdocs_home_page_carries_the_citation():
    index = _read("docs/index.md")
    assert CONCEPT_DOI in index
    assert VERSION_DOI in index


# --- release plan -------------------------------------------------------


def test_release_plan_records_rc3_publication():
    normalized = _normalized(_read("docs/release-plan-0.1.0.md"))
    assert RC3_COMMIT in normalized
    assert RC3_DIGEST in normalized
    assert RC3_RUN in normalized
    assert "0.1.0-rc3" in normalized


def test_release_plan_records_release_and_zenodo_dois():
    normalized = _normalized(_read("docs/release-plan-0.1.0.md"))
    assert CONCEPT_DOI in normalized
    assert VERSION_DOI in normalized
    assert "releases/tag/v0.1.0-rc3" in normalized
    assert "zenodo.org/records/23415802" in normalized


def test_release_plan_does_not_present_rc3_as_the_final_release():
    normalized = _normalized(_read("docs/release-plan-0.1.0.md"))
    assert "RC3 is the latest published pre-release" in normalized
    assert "not the final `v0.1.0`" in normalized
    assert "has not been released" in normalized


def test_release_plan_keeps_serve_on_rc2():
    normalized = _normalized(_read("docs/release-plan-0.1.0.md"))
    assert "SciLifeLab Serve is running RC2" in normalized
    assert "RC3 has **not** been deployed to Serve" in normalized


# --- CITATION.cff -------------------------------------------------------


def test_citation_cff_authors_and_type():
    cff = _read("CITATION.cff")
    assert "title: \"AnnotateR\"" in cff
    assert "type: software" in cff
    assert "license: BSD-3-Clause" in cff
    assert cff.index("family-names: Das") < cff.index("family-names: Volpe")


def test_citation_cff_is_version_independent():
    cff = _read("CITATION.cff")
    assert not re.search(r"(?m)^version:", cff)
    assert not re.search(r"(?m)^date-released:", cff)
    assert not re.search(r"(?m)^doi:", cff)


def test_citation_cff_comment_no_longer_claims_no_release_exists():
    cff = _read("CITATION.cff")
    assert "No git tag" not in cff
    assert "No DOI or publication is claimed" not in cff


def test_citation_cff_validates_if_validator_available():
    validator = shutil.which("cffconvert")
    if validator is None:
        fallback = Path.home() / ".local" / "bin" / "cffconvert"
        validator = str(fallback) if fallback.exists() else None
    if validator is None:
        pytest.skip("cffconvert not installed; schema validation skipped")

    result = subprocess.run(
        [validator, "--validate", "-i", str(ROOT / "CITATION.cff")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
