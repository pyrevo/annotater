"""The single "Genome assembly" control at catalog scale.

One searchable selectbox whose options come from the bundled catalog
metadata (no hard-coded list, no species selector). The six deeply validated
assemblies keep their detailed GUI scenarios in test_f10_chromosome_messaging;
here: option integrity, searchability by the terms users type, selection of
newly bundled assemblies, and that building the selector loads no registry.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from streamlit_app.core.chrom_registry import load_catalog, load_registry
from streamlit_app.streamlit_app import (
    _ASSEMBLY_INFO,
    _ASSEMBLY_LABELS,
    _ASSEMBLY_OPTIONS,
    _ASSEMBLY_PLACEHOLDER,
    _CUSTOM_OPTION,
)
from tests.test_f10_chromosome_messaging import (
    ANNOT_UCSC,
    APP_ENTRYPOINT,
    COORD_UCSC,
    _assert_no_exception,
    _go,
    _upload,
    _widget,
)

CATALOG = load_catalog()
MM10 = "Mouse — Dec. 2011 (GRCm38/mm10)"
CE11 = "C. elegans — Feb. 2013 (WBcel235/ce11)"
UCSC = "UCSC names"
GFF = (b"##gff-version 3\n"
       b"%s\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n")


# ---- option integrity ------------------------------------------------------------

def test_options_are_the_placeholder_then_every_catalog_assembly_once():
    at = _upload(COORD_UCSC, ANNOT_UCSC)
    options = list(_widget(at, "selectbox", "chr_assembly").options)
    assert options == [_ASSEMBLY_PLACEHOLDER, _CUSTOM_OPTION,
                       *(i.display_label for i in CATALOG)]
    assert len(options) == len(set(options)) == 66


def test_every_option_maps_back_to_exactly_one_runtime_assembly():
    assert len(_ASSEMBLY_OPTIONS) == len(CATALOG) == 64
    assert _ASSEMBLY_PLACEHOLDER not in _ASSEMBLY_OPTIONS
    assert len(set(_ASSEMBLY_OPTIONS.values())) == 64
    assert {_ASSEMBLY_LABELS[v]: v for v in _ASSEMBLY_OPTIONS.values()} == \
        _ASSEMBLY_OPTIONS
    for info in CATALOG:
        assert _ASSEMBLY_OPTIONS[info.display_label] == info.canonical_id


def test_nothing_is_preselected_and_only_one_assembly_control_exists():
    at = _upload(COORD_UCSC, ANNOT_UCSC)
    assembly = _widget(at, "selectbox", "chr_assembly")
    assert assembly.value == _ASSEMBLY_PLACEHOLDER
    labels = [s.label for s in at.get("selectbox")]
    assert labels.count("Genome assembly") == 1
    assert not [lab for lab in labels
                if lab in ("Species", "Assembly", "Database", "Source")]
    assert "result_df" not in at.session_state


# ---- searchability -----------------------------------------------------------------

def _search(term):
    """Options a user would see after typing ``term`` (case-insensitive)."""
    return [label for label in _ASSEMBLY_OPTIONS if term.lower() in label.lower()]


def test_users_can_find_assemblies_by_the_terms_they_type():
    for term, expected_db in (("human", "hg19"), ("GRCh38", "hg38"),
                              ("hg38", "hg38"), ("mouse", "mm10"),
                              ("dog", "canFam3"), ("canFam", "canFam4"),
                              ("zebrafish", "danRer11"), ("elegans", "ce11")):
        hits = _search(term)
        assert hits, term
        assert expected_db in " ".join(hits), (term, hits)
    assert len(_search("canFam")) == 4 and len(_search("dog")) == 4


def test_every_assembly_is_findable_by_its_ucsc_db_id_and_organism():
    for info in CATALOG:
        assert info.display_label in _search(info.ucsc_db)
        assert info.display_label in _search(info.organism.strip())


def test_scientific_name_is_shown_for_the_selected_assembly():
    at = _upload(COORD_UCSC, ANNOT_UCSC, assembly=MM10)
    captions = [c.value for c in at.get("caption")]
    assert any("Mus musculus" in c and "UCSC mm10" in c for c in captions)
    at = _upload(COORD_UCSC, ANNOT_UCSC)       # nothing selected: no caption
    assert not any("UCSC " in c.value for c in at.get("caption"))


# ---- newly bundled assemblies (one mammal, one non-mammal) -------------------------

def test_newly_bundled_mammal_normalizes_an_accession_and_matches():
    at = _go(b"NC_000067.6\t100\t200\tq1\n", GFF % b"chr1",
             assembly=MM10, naming=UCSC)
    result = at.session_state["result_df"]
    assert result["coord_chr"].tolist() == ["chr1"]
    assert result["has_overlap"].tolist() == [True]
    assert (result["coord_start"].tolist(), result["coord_end"].tolist()) == (
        [100], [200])                                  # coordinates unchanged
    assert not at.error


def test_newly_bundled_non_mammal_uses_its_own_naming():
    at = _go(b"I\t100\t200\tq1\n", GFF % b"chrI", assembly=CE11, naming=UCSC)
    result = at.session_state["result_df"]
    assert result["coord_chr"].tolist() == ["chrI"]
    assert result["has_overlap"].tolist() == [True]


def test_a_name_from_another_assembly_is_reported_unrecognized():
    at = _go(b"2L\t100\t200\tq1\n", GFF % b"chr1", assembly=MM10, naming=UCSC)
    assert at.warning                                   # visible, not silent
    report = at.session_state["result_chr_normalization"]
    assert "2L" in report["coord_report"].unknown


def test_keep_original_still_needs_no_assembly_and_normalization_requires_one():
    at = _go(COORD_UCSC, ANNOT_UCSC)
    assert "result_df" in at.session_state
    at = _upload(COORD_UCSC, ANNOT_UCSC, naming=UCSC)
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    assert "result_df" not in at.session_state
    assert any("Select the genome assembly" in e.value for e in at.error)


# ---- performance: nothing is loaded eagerly -----------------------------------------

def test_building_the_selector_and_choosing_an_assembly_load_no_registry():
    load_registry.cache_clear()
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _assert_no_exception(at)
    assert load_registry.cache_info().currsize == 0       # selector built
    _widget(at, "selectbox", "chr_assembly").set_value(MM10)
    at.run()
    assert load_registry.cache_info().currsize == 0       # keep original


def test_a_normalizing_run_loads_only_the_selected_registry():
    load_registry.cache_clear()
    _go(b"NC_000067.6\t100\t200\tq1\n", GFF % b"chr1",
        assembly=MM10, naming=UCSC)
    assert load_registry.cache_info().currsize == 1
    assert _ASSEMBLY_INFO["GRCm38"].ucsc_db == "mm10"
