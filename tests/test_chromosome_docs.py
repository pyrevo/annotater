"""Documentation contract for assembly-aware chromosome normalization.

Concrete claims in the user documentation are tied to the real registries
and application: examples, counts, limits, messages and links. Generated
blocks must be current, and the removed chromosome-style vocabulary must
not come back.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from streamlit_app.core.chrom_registry import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ROWS,
    builder,
    load_catalog,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.chromosome_normalization import (
    normalize_chromosomes,
    normalize_chromosomes_with_registry,
)
from streamlit_app.core.vcf_contigs import (
    header_contig_renames,
    reconcile_contig_lines,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GUIDE = DOCS / "preparing-your-data" / "chromosome-identifiers.md"
ASSEMBLIES = DOCS / "preparing-your-data" / "bundled-assemblies.md"
METHODS = DOCS / "technical" / "chromosome-registry.md"
APP_SOURCE = (ROOT / "streamlit_app" / "streamlit_app.py").read_text("utf-8")
# adjacent string literals joined, unicode escapes resolved
APP_TEXT = re.sub(r'"\s*\n\s*"', "", APP_SOURCE).replace("\\u2026", "…")

# Pages that are not published on the site (see mkdocs.yml exclude_docs).
EXCLUDED = {"manual-plan.md", "release-plan-0.1.0.md", "FUTURE_FEATURES.md",
            "implementation-notes.md", "legacy.md", "semantic-examples.md"}


def public_pages():
    pages = [p for p in DOCS.rglob("*.md")
             if p.name not in EXCLUDED and "agents" not in p.parts]
    return pages + [ROOT / "README.md", ROOT / "QUICKSTART.md"]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- generated content is current ----------------------------------------------------

def test_generated_assembly_blocks_are_current():
    assert _load("generate_assembly_docs").run(check=True) == 0


def test_generated_chromosome_examples_in_the_guide_are_current():
    assert _load("generate_semantic_examples").run(check=True) == 0
    guide = GUIDE.read_text("utf-8")
    for name in ("chromosome_accession_identity", "chromosome_wrong_assembly",
                 "chromosome_hg19_mitochondria", "chromosome_dm6_non_human",
                 "chromosome_many_to_one", "chromosome_coordinates_preserved"):
        assert f"<!-- BEGIN GENERATED: {name} -->" in guide


def test_the_assembly_reference_lists_every_bundled_assembly_exactly_once():
    text = ASSEMBLIES.read_text("utf-8")
    for info in load_catalog():
        assert f"| {info.display_label} | {info.canonical_id} | {info.ucsc_db} |" \
            in text, info.canonical_id
    rows = [ln for ln in text.splitlines() if ln.startswith("| ")][1:]
    assert len(rows) == len(load_catalog()) == 64
    assert "registry_file" not in text and "data/" not in text   # no internals


# ---- numbers --------------------------------------------------------------------------

def test_bundle_and_audit_numbers_are_stated_exactly():
    catalog = load_catalog()
    species = {i.scientific_name for i in catalog}
    assert (len(catalog), len(species)) == (64, 46)
    for page in (GUIDE, ROOT / "README.md"):
        assert "64 genome assemblies of 46 species" in " ".join(
            page.read_text("utf-8").split()), page.name
    audit = json.loads(
        (ROOT / "audits/chrom_alias_catalog/bundle_facts.json").read_text())
    counts = audit["audit"]["status_counts"]
    assert (audit["audit"]["candidates"], audit["audit"]["with_chrom_alias"],
            counts["PASS"], counts["REVIEW"], counts["FAIL"],
            counts["NO_SOURCE"]) == (238, 132, 122, 5, 5, 106)
    block = METHODS.read_text("utf-8")
    for fragment in ("| UCSC genome databases audited | 238 |",
                     "| …with a database `chromAlias` source | 132 |",
                     "| …representable cleanly by the current architecture | 122 |",
                     "| …requiring review | 5 |",
                     "| …failing the current representation | 5 |",
                     "| …with no database `chromAlias` source | 106 |",
                     "**64 assemblies, 46 species**"):
        assert fragment in block, fragment


def test_the_audit_count_is_never_presented_as_runtime_support():
    for page in (GUIDE, ASSEMBLIES, ROOT / "README.md", ROOT / "QUICKSTART.md",
                 DOCS / "limitations.md", DOCS / "faq.md"):
        assert "122" not in page.read_text("utf-8"), page.name
    methods = METHODS.read_text("utf-8")
    assert "Architecture audit coverage" in methods
    assert "Bundled runtime support" in methods


def test_documented_custom_limits_are_the_loader_defaults():
    assert (DEFAULT_MAX_ROWS, DEFAULT_MAX_BYTES) == (500_000, 64 * 2**20)
    guide = GUIDE.read_text("utf-8")
    assert "**500,000 rows** and **64 MiB**" in guide
    assert "0.6 GB" in guide and "worst case" in guide
    assert "500,000 rows and 64 MiB" in (DOCS / "limitations.md").read_text()


# ---- examples tied to real registry behavior ---------------------------------------------

def frame(names):
    return pd.DataFrame({"chr": names, "start": range(len(names)),
                         "end": range(1, len(names) + 1)})


def test_documented_examples_hold_in_the_bundled_registries():
    out = normalize_chromosomes(frame(["NC_000001.11"]), assembly="GRCh38",
                                target="ucsc")
    assert out.dataframe["chr"].tolist() == ["chr1"]
    # unknown vs recognized-without-target are different outcomes
    grch38 = normalize_chromosomes(frame(["NC_000001.10"]), assembly="GRCh38",
                                   target="ucsc").report
    assert dict(grch38.unknown) == {"NC_000001.10": 1}
    hg19 = normalize_chromosomes(frame(["chrM", "chrMT"]), assembly="hg19",
                                 target="ensembl")
    assert hg19.dataframe["chr"].tolist() == ["chrM", "MT"]
    assert dict(hg19.report.no_alias_for_target) == {"chrM": 1}
    assert not hg19.report.unknown
    dm6 = normalize_chromosomes(frame(["chr2L", "chrM"]), assembly="dm6",
                                target="ensembl")
    assert dm6.dataframe["chr"].tolist() == ["2L", "chrM"]
    assert normalize_chromosomes(frame(["chr1"]), assembly="GRCh38",
                                 target="ucsc").report.complete


def test_documented_aliases_load_the_same_assembly():
    for canonical, alias in (("GRCh38", "hg38"), ("GRCm38", "mm10"),
                             ("GRCm39", "mm39"), ("mRatBN7.2", "rn7")):
        assert load_registry(alias) is load_registry(canonical)
        assert load_registry(alias).assembly_id == canonical
    assert load_registry("hg19").assembly_id == "hg19"


def test_hg19_mitochondrial_facts_in_the_text_are_in_the_pinned_evidence():
    hg19 = load_registry("hg19")
    chrm = hg19.record(hg19.resolve("chrM").seq_id).aliases
    chrmt = hg19.record(hg19.resolve("chrMT").seq_id).aliases
    assert chrm["refseq"] == "NC_001807.4" and "ensembl" not in chrm
    assert chrmt["refseq"] == "NC_012920.1" and chrmt["assembly"] == "MT"
    assert hg19.resolve("chrM").seq_id != hg19.resolve("chrMT").seq_id
    sources = json.loads((builder.PACKAGE_DIR / "sources.json").read_text())
    entry = next(a for a in sources["assemblies"] if a["assembly_id"] == "hg19")
    assert "16571 bp" in entry["label_corrections"][0]["rationale"]
    evidence = (builder.PACKAGE_DIR / entry["ensembl_evidence"]["evidence_file"]
                ).read_text().splitlines()
    header = evidence[0].split("\t")
    mt = [dict(zip(header, ln.split("\t"))) for ln in evidence[1:]
          if ln.split("\t")[0] == "MT"]
    assert mt[0]["length"] == "16569" and mt[0]["refseq"] == "NC_012920.1"
    guide = GUIDE.read_text("utf-8")
    for fact in ("NC_001807.4 (16,571 bp)", "NC_012920.1 (16,569 bp)"):
        assert fact in guide


def test_zebrafish_has_25_chromosomes_and_no_x():
    zebrafish = load_registry("GRCz11")
    assert all(zebrafish.resolve(f"chr{n}").resolved for n in range(1, 26))
    assert not zebrafish.resolve("chr26").resolved
    assert not zebrafish.resolve("chrX").resolved


def _tsv_block():
    guide = GUIDE.read_text("utf-8")
    match = re.search(r"```tsv\n(.*?)```", guide, re.DOTALL)
    return match.group(1)


def test_the_documented_custom_example_is_a_valid_mapping_with_real_tabs():
    text = _tsv_block()
    assert text.splitlines()[0] == "assembly\tucsc\tensembl\tgenbank\trefseq"
    assert "\t" in text and "  " not in text
    registry = load_custom_registry(text.encode())
    assert len(registry) == 4 and registry.assembly_id is None
    out = normalize_chromosomes_with_registry(
        frame(["NC_099999.1", "scaffold_1", "1"]), registry=registry,
        target="ensembl")
    assert out.dataframe["chr"].tolist() == ["MT", "scaffold_1", "1"]
    # the sequence without an Ensembl name is "recognized, no verified name"
    assert dict(out.report.no_alias_for_target) == {"scaffold_1": 1}
    assert not out.report.unknown


def test_documented_custom_rules_match_the_loader():
    from streamlit_app.core.chrom_registry import CustomRegistryError
    header = "assembly\tucsc\tensembl\tgenbank\trefseq\n"
    rejected = {
        "whitespace": header + " a\tb\t\t\t\n",
        "same name on two rows": header + "a\tb\t\t\t\nc\ta\t\t\t\n",
        "empty line": header + "a\tb\t\t\t\n\n",
        "no name": header + "\t\t\t\t\n",
        "duplicate row": header + "a\tb\t\t\t\na\tb\t\t\t\n",
        "comment": header + "# x\na\tb\t\t\t\n",
        "control character": header + "a\tb\x01\t\t\t\n",
    }
    for label, text in rejected.items():
        with pytest.raises(CustomRegistryError):
            load_custom_registry(text.encode())
        assert label
    load_custom_registry(("﻿" + header.replace("\n", "\r\n")
                          + "a\tb\t\t\t").encode())                    # accepted
    load_custom_registry((header + "x\tx\tx\t\t\n").encode())          # same row
    load_custom_registry((header + "Chr1\tchr1\t\t\t\n").encode())     # case


def test_documented_vcf_contig_behavior():
    registry = load_registry("GRCh38")
    header = ["##contig=<ID=1,length=248956422>",
              "##contig=<ID=mystery,length=5>"]
    renames = header_contig_renames(header, registry, "ucsc")
    assert renames == {"1": "chr1"}
    assert reconcile_contig_lines(header, renames) == [
        "##contig=<ID=chr1,length=248956422>", "##contig=<ID=mystery,length=5>"]
    assert reconcile_contig_lines(header, {}) == header          # keep original


# ---- UI names and messages quoted in the docs exist in the app ---------------------------

def test_quoted_ui_texts_exist_in_the_application():
    guide = " ".join(GUIDE.read_text("utf-8").split())
    for label in ("Select genome assembly", "Custom chromosome mapping…",
                  "Chromosome mapping file", "Keep original names",
                  "UCSC names", "Assembly names", "Ensembl names",
                  "NCBI RefSeq accessions", "GenBank accessions",
                  "Genome assembly", "Chromosome naming"):
        assert label in guide, label
        assert label in APP_TEXT, label
    for message in (
            "Select the genome assembly before normalizing chromosome names.",
            "Upload a chromosome mapping file before normalizing chromosome names.",
            "The chromosome mapping file is not valid",
            "Not recognized in",
            "Recognized, but no verified name is available in",
            "Annotated VCF export is unavailable",
            ("No shared chromosome identifiers remain between query and "
             "annotation data.")):
        assert message in guide, message
        assert message in APP_TEXT, message


# ---- trust boundary wording --------------------------------------------------------------

def test_the_custom_trust_boundary_is_explicit_and_not_overstated():
    guide = " ".join(GUIDE.read_text("utf-8").split())
    assert ("AnnotateR checks custom mappings for structural consistency, but "
            "does not independently verify that the supplied biological "
            "mappings are correct.") in guide
    for page in public_pages():
        text = page.read_text("utf-8").lower()
        for claim in ("verified custom", "certified", "validates your mapping",
                      "biologically verified mapping"):
            assert claim not in text, (page.name, claim)


# ---- vocabulary, scope and links -----------------------------------------------------------

STALE = ["Auto-convert", "Chromosome ID handling", "Target style",
         "Manual specification", "chromosome style", "chr style",
         "naming style", "auto-detected style", "ChromosomeMapper",
         "UCSC ⇄ Ensembl", "chr1 vs 1", "style mismatch"]


@pytest.mark.parametrize("page", public_pages(), ids=lambda p: p.name)
def test_removed_chromosome_style_vocabulary_is_gone(page):
    text = page.read_text("utf-8")
    for phrase in STALE:
        assert phrase not in text, (page.name, phrase)


def test_no_hypothetical_cli_is_documented():
    for page in public_pages():
        text = page.read_text("utf-8")
        for phrase in ("--assembly", "--chrom-map", "annotater --"):
            assert phrase not in text, (page.name, phrase)


def slug(heading: str) -> str:
    text = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"[\s]+", "-", text)


def anchors(path: Path) -> set[str]:
    return {slug(m.group(1)) for m in
            re.finditer(r"^#{1,6}\s+(.*?)\s*$", path.read_text("utf-8"),
                        re.MULTILINE)}


@pytest.mark.parametrize("page", public_pages(), ids=lambda p: p.name)
def test_relative_links_and_images_resolve(page):
    text = page.read_text("utf-8")
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path, _, anchor = target.partition("#")
        resolved = (page.parent / path).resolve()
        assert resolved.exists(), (page.name, target)
        if anchor and resolved.suffix == ".md":
            assert anchor in anchors(resolved), (page.name, target)
    for anchor in re.findall(r"\]\(#([^)\s]+)\)", text):
        assert anchor in anchors(page), (page.name, anchor)


def test_new_pages_are_in_the_navigation_and_stale_screenshots_are_gone():
    nav = (ROOT / "mkdocs.yml").read_text("utf-8")
    for page in ("preparing-your-data/chromosome-identifiers.md",
                 "preparing-your-data/bundled-assemblies.md",
                 "technical/chromosome-registry.md"):
        assert page in nav, page
    assert "chr1 vs 1" not in nav
    assert not list((DOCS / "assets").rglob("*.png"))
    for page in public_pages():
        assert "assets/screenshots" not in page.read_text("utf-8"), page.name


def test_the_ci_workflow_checks_the_generated_assembly_docs():
    workflow = (ROOT / ".github/workflows/python-tests.yml").read_text()
    assert "generate_assembly_docs.py --check" in workflow
