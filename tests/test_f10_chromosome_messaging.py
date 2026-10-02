"""
Chromosome naming in the application (F10 intent, assembly-aware model).

The original F10 regression: the app displayed a "standardized" success
message for a pair of naming styles it could not actually convert, while
the result silently contained no matches. The same principle holds for the
assembly-aware workflow:

1. "Keep original names" is a true no-op and needs no genome assembly.
2. Any normalization requires an explicitly selected genome assembly; the
   run is blocked with a clear message otherwise. Nothing is inferred.
3. Normalization is reported honestly: unrecognized chromosome names and
   names unavailable in the chosen naming are left as provided, are listed
   separately, and are never presented as normalized.
4. Chromosome names that merge into one output name are reported, not hidden.
5. When no shared chromosome identifiers remain, a clear warning is shown.
6. A valid overlap produces no false warning.
7. Behavior is identical for both backends.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

GRCH38 = "Human — Dec. 2013 (GRCh38/hg38)"
HG19 = "Human — Feb. 2009 (GRCh37/hg19)"
DM6 = "D. melanogaster — Aug. 2014 (BDGP Release 6 + ISO1 MT/dm6)"
UCSC = "UCSC names"
ENSEMBL = "Ensembl names"

COORD_UCSC = b"chr1\t100\t200\tq1\n"
COORD_NCBI = b"NC_000001.11\t100\t200\tq1\n"
ANNOT_ENSEMBL = (
    b"##gff-version 3\n"
    b"1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)
ANNOT_UCSC = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)


def _widget(at: AppTest, etype: str, key: str):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _assert_no_exception(at: AppTest):
    if at.exception:
        raise at.exception[0].value


def _texts(at: AppTest, kind: str):
    return [e.value for e in at.get(kind)]


def _upload(coord_bytes, annot_bytes, assembly=None, naming=None, engine=None):
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    if engine is not None:
        _widget(at, "radio", "engine").set_value(engine)
    if assembly is not None:
        _widget(at, "selectbox", "chr_assembly").set_value(assembly)
    if naming is not None:
        _widget(at, "selectbox", "chr_naming").set_value(naming)
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", coord_bytes, "application/octet-stream"))
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", annot_bytes, "application/octet-stream"))
    at.run()
    _assert_no_exception(at)
    return at


def _run(at: AppTest) -> AppTest:
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    _assert_no_exception(at)
    return at


def _go(coord, annot, **kw):
    return _run(_upload(coord, annot, **kw))


# --- controls -------------------------------------------------------------------

def test_controls_are_plain_language_with_no_preselected_assembly():
    at = _upload(COORD_UCSC, ANNOT_UCSC)
    assembly = _widget(at, "selectbox", "chr_assembly")
    naming = _widget(at, "selectbox", "chr_naming")
    assert assembly.label == "Genome assembly"
    assert naming.label == "Chromosome naming"
    options = list(assembly.options)
    assert options[0] == "Select genome assembly"
    # the catalog-driven list (details: tests/test_assembly_selector.py);
    # the six deeply validated assemblies are all offered and understandable
    assert options[1] == "Custom chromosome mapping\u2026"
    assert len(options) == 1 + 1 + 64
    for label in (GRCH38, HG19, "Mouse \u2014 Jun. 2020 (GRCm39/mm39)",
                  DM6, "Zebrafish \u2014 May 2017 (GRCz11/danRer11)",
                  "Rat \u2014 Nov. 2020 (mRatBN7.2/rn7)"):
        assert label in options
    assert assembly.value == "Select genome assembly"  # nothing implied
    assert list(naming.options) == [
        "Keep original names", "UCSC names", "Ensembl names",
        "NCBI RefSeq accessions", "GenBank accessions", "Assembly names"]
    assert naming.value == "Keep original names"
    # Obsolete controls and wording are gone.
    assert not at.get("radio") or all(
        getattr(r, "key", None) != "chr_handling" for r in at.get("radio"))
    sidebar_text = " ".join(
        e.label for e in at.get("selectbox") + at.get("radio"))
    for old in ("Auto-convert", "Target style", "Chromosome ID handling"):
        assert old not in sidebar_text


def test_every_supported_assembly_is_offered_and_nothing_else():
    from streamlit_app.core.chrom_registry import load_catalog
    from streamlit_app.streamlit_app import _ASSEMBLY_OPTIONS
    configured = [i.canonical_id for i in load_catalog()]
    assert sorted(_ASSEMBLY_OPTIONS.values()) == sorted(configured)


# --- keep original / assembly requirement -------------------------------------------

def test_keep_original_runs_without_an_assembly_and_changes_nothing():
    at = _go(COORD_UCSC, ANNOT_ENSEMBL)
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "chr1"
    assert bool(result["has_overlap"].iloc[0]) is False  # chr1 vs 1: kept
    assert at.session_state["result_vcf_contig_renames"] == {}
    assert at.session_state["result_chr_normalization"] is None
    assert any("kept as provided" in c for c in _texts(at, "caption"))
    assert any("no shared chromosome identifiers" in w.lower()
               for w in _texts(at, "warning"))


def test_normalizing_without_an_assembly_is_blocked_with_a_clear_message():
    message = "Select the genome assembly before normalizing chromosome names."
    at = _upload(COORD_UCSC, ANNOT_UCSC, naming=ENSEMBL)
    assert message in _texts(at, "warning")  # shown next to the controls
    at = _run(at)
    assert message in _texts(at, "error")
    assert "result_df" not in at.session_state  # the run did not execute


def test_assembly_is_required_even_when_both_files_already_agree():
    at = _go(COORD_UCSC, ANNOT_UCSC, naming=ENSEMBL)
    assert "result_df" not in at.session_state


# --- normalization -----------------------------------------------------------------

def test_grch38_normalization_matches_files_and_keeps_coordinates():
    at = _go(COORD_UCSC, ANNOT_ENSEMBL, assembly=GRCH38, naming=UCSC)
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "chr1"
    assert bool(result["has_overlap"].iloc[0]) is True
    assert (result["coord_start"].iloc[0], result["coord_end"].iloc[0]) == (
        100, 200)
    assert at.session_state["result_vcf_contig_renames"] == {}
    captions = " ".join(_texts(at, "caption"))
    assert "Chromosome naming: UCSC names" in captions
    assert "Coordinates and genome assembly are unchanged" in captions
    assert "Annotation: 1 names normalized" in captions
    assert not _texts(at, "warning")


def test_ensembl_names_for_both_files():
    at = _go(COORD_UCSC, ANNOT_UCSC, assembly=GRCH38, naming=ENSEMBL)
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "1"
    assert at.session_state["result_vcf_contig_renames"] == {"chr1": "1"}


def test_accessions_are_normalized_when_the_assembly_is_known():
    # Previously unsupported: NCBI accessions now resolve within GRCh38.
    at = _go(COORD_NCBI, ANNOT_UCSC, assembly=GRCH38, naming=UCSC)
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "chr1"
    assert bool(result["has_overlap"].iloc[0]) is True


def test_unrecognized_names_are_reported_not_presented_as_normalized():
    at = _go(b"chr1\t100\t200\tq1\nmystery\t100\t200\tq2\n", ANNOT_UCSC,
             assembly=GRCH38, naming=ENSEMBL)
    result = at.session_state["result_df"]
    assert result["coord_chr"].tolist() == ["1", "mystery"]  # left as given
    warnings = " ".join(_texts(at, "warning"))
    assert "could not be normalized" in warnings
    assert "Query: 1 names normalized, 0 already in this naming, 1 not normalized." \
        in " ".join(_texts(at, "caption"))
    details = [e for e in at.get("expander")
               if e.label == "Chromosome normalization details"]
    assert details
    text = " ".join(m.value for m in details[0].markdown)
    assert "Not recognized in Human — Dec. 2013 (GRCh38/hg38): mystery (1 rows)" in text
    assert "no verified name is available" not in text


def test_hg19_mitochondrial_names_are_not_rewritten_by_string_rules():
    coord = b"chrM\t100\t200\tq1\nchrMT\t100\t200\tq2\n"
    annot = (b"##gff-version 3\n"
             b"MT\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n")
    at = _go(coord, annot, assembly=HG19, naming=ENSEMBL)
    result = at.session_state["result_df"].sort_values("coord_start")
    assert result["coord_chr"].tolist() == ["chrM", "MT"]
    report = at.session_state["result_chr_normalization"]["coord_report"]
    assert dict(report.no_alias_for_target) == {"chrM": 1}
    assert not report.unknown
    details = next(e for e in at.get("expander")
                   if e.label == "Chromosome normalization details")
    text = " ".join(m.value for m in details.markdown)
    assert "Recognized, but no verified name is available in Ensembl names: " \
        "chrM (1 rows)" in text
    assert "Not recognized" not in text


def test_dm6_uses_registry_names_not_human_rules():
    coord = b"chr2L\t100\t200\tq1\nchrM\t100\t200\tq2\n"
    annot = (b"##gff-version 3\n"
             b"2L\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n")
    at = _go(coord, annot, assembly=DM6, naming=ENSEMBL)
    result = at.session_state["result_df"].sort_values("coord_start")
    assert result["coord_chr"].tolist() == ["2L", "chrM"]
    assert bool(result["has_overlap"].iloc[0]) is True
    report = at.session_state["result_chr_normalization"]["coord_report"]
    assert dict(report.no_alias_for_target) == {"chrM": 1}


def test_merged_names_are_reported_without_an_error():
    coord = b"1\t100\t200\tq1\nchr1\t100\t200\tq2\n"
    at = _go(coord, ANNOT_UCSC, assembly=GRCH38, naming=UCSC)
    assert not _texts(at, "error")
    assert any("normalized to the same output name" in i
               for i in _texts(at, "info"))
    details = next(e for e in at.get("expander")
                   if e.label == "Chromosome normalization details")
    text = " ".join(m.value for m in details.markdown)
    assert "1, chr1 → chr1" in text
    assert at.session_state["result_vcf_contig_renames"] == {"1": "chr1"}


def test_no_shared_identifiers_warning_is_shown():
    at = _go(COORD_NCBI, ANNOT_UCSC)
    assert any("no shared chromosome identifiers" in w.lower()
               for w in _texts(at, "warning"))
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "NC_000001.11"  # nothing pretended
    assert bool(result["has_overlap"].iloc[0]) is False


def test_no_false_warning_when_valid_overlap_exists():
    at = _go(COORD_UCSC, ANNOT_UCSC)
    assert not any("no shared chromosome identifiers" in w.lower()
                   for w in _texts(at, "warning"))
    assert bool(at.session_state["result_df"]["has_overlap"].iloc[0]) is True


def test_behavior_is_identical_on_the_polars_bio_engine():
    at = _go(COORD_UCSC, ANNOT_ENSEMBL, assembly=GRCH38, naming=UCSC,
             engine="Polars-Bio")
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "chr1"
    assert bool(result["has_overlap"].iloc[0]) is True


# --- state safety ----------------------------------------------------------------------

def test_changing_assembly_or_naming_invalidates_results_and_reports():
    at = _go(COORD_UCSC, ANNOT_ENSEMBL, assembly=GRCH38, naming=UCSC)
    assert "result_df" in at.session_state
    _widget(at, "selectbox", "chr_naming").set_value(ENSEMBL)
    at.run()
    assert "result_df" not in at.session_state
    assert "result_chr_normalization" not in at.session_state
    at = _run(at)
    assert at.session_state["result_df"]["coord_chr"].iloc[0] == "1"
    _widget(at, "selectbox", "chr_assembly").set_value(HG19)
    at.run()
    assert "result_df" not in at.session_state  # assembly change: stale


def test_assembly_change_is_irrelevant_while_names_are_kept():
    at = _go(COORD_UCSC, ANNOT_UCSC)
    assert "result_df" in at.session_state
    _widget(at, "selectbox", "chr_assembly").set_value(HG19)
    at.run()
    assert "result_df" in at.session_state  # kept names: assembly unused
    assert at.session_state["result_chr_normalization"] is None
