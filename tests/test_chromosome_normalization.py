"""Dataframe-level chromosome normalization (SPEC 5.1).

Expected values come from the pinned registries, never from the code under
test. The API is a parallel core API; the application still uses
``ChromosomeMapper``.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from streamlit_app.core import (
    ChromosomeNormalizationReport,
    NormalizationResult,
    normalize_chromosomes,
)
from streamlit_app.core.chrom_registry import (
    ChromosomeRegistry,
    UnsupportedAssemblyError,
    UnsupportedAuthorityError,
)
from streamlit_app.core.chromosome_normalization import (
    ChromosomeNormalizationError,
    StrictChromosomeNormalizationError,
)


def frame(chroms, **extra):
    n = len(chroms)
    data = {"chr": chroms, "start": list(range(100, 100 + n)),
            "end": [s + 50 for s in range(100, 100 + n)],
            "strand": ["+", "-", ".", "+", "-", "."][:n] + ["+"] * max(0, n - 6),
            "name": [f"r{i}" for i in range(n)]}
    data.update(extra)
    return pd.DataFrame(data)


def norm(chroms, assembly, target, **kw):
    return normalize_chromosomes(frame(chroms), assembly=assembly,
                                 target=target, **kw)


def chrs(result):
    return result.dataframe["chr"].tolist()


# --- API contract ----------------------------------------------------------------

def test_returns_structured_result_and_a_new_frame():
    df = frame(["chr1", "chr2"])
    before = df.copy(deep=True)
    result = normalize_chromosomes(df, assembly="GRCh38", target="ensembl")
    assert isinstance(result, NormalizationResult)
    assert isinstance(result.report, ChromosomeNormalizationReport)
    assert result.dataframe is not df
    pd.testing.assert_frame_equal(df, before)  # input untouched
    result.dataframe.loc[0, "name"] = "mutated"
    pd.testing.assert_frame_equal(df, before)  # output is independent


def test_result_and_report_are_immutable():
    result = norm(["chr1", "x"], "GRCh38", "ensembl")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.report.assembly = "hg19"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.dataframe = None
    with pytest.raises(TypeError):
        result.report.unknown["y"] = 1
    with pytest.raises(TypeError):
        result.report.collapses["y"] = ("a", "b")


def test_arguments_are_keyword_only():
    with pytest.raises(TypeError):
        normalize_chromosomes(frame(["chr1"]), "GRCh38", "ensembl")


# --- argument and data validation -----------------------------------------------

@pytest.mark.parametrize("assembly", [None, "", 38, ["GRCh38"]])
def test_assembly_is_mandatory_and_never_defaulted(assembly):
    with pytest.raises(ChromosomeNormalizationError, match="assembly"):
        normalize_chromosomes(frame(["chr1"]), assembly=assembly,
                              target="ensembl")


@pytest.mark.parametrize("assembly", ["hg38", "grch38", "GRCh38 ", "mm39"])
def test_unsupported_assembly_uses_registry_error(assembly):
    with pytest.raises(UnsupportedAssemblyError):
        normalize_chromosomes(frame(["chr1"]), assembly=assembly,
                              target="ensembl")


@pytest.mark.parametrize("target", ["UCSC", "ncbi", "", None, "chr"])
def test_unknown_target_authority_is_a_configuration_error(target):
    with pytest.raises(UnsupportedAuthorityError):
        normalize_chromosomes(frame(["chr1"]), assembly="GRCh38",
                              target=target)
    empty = pd.DataFrame({"chr": [], "start": [], "end": []})
    with pytest.raises(UnsupportedAuthorityError):  # even without rows
        normalize_chromosomes(empty, assembly="GRCh38", target=target)


def test_missing_chr_column_and_non_dataframe_fail_clearly():
    with pytest.raises(ChromosomeNormalizationError, match="'chr'"):
        normalize_chromosomes(pd.DataFrame({"chrom": ["chr1"]}),
                              assembly="GRCh38", target="ensembl")
    with pytest.raises(ChromosomeNormalizationError, match="DataFrame"):
        normalize_chromosomes([("chr1", 1, 2)], assembly="GRCh38",
                              target="ensembl")


@pytest.mark.parametrize("values", [
    ["chr1", None], ["chr1", float("nan")], ["chr1", pd.NA],
])
def test_null_chromosomes_are_invalid_data_not_unknown(values):
    with pytest.raises(ChromosomeNormalizationError, match="null"):
        norm(values, "GRCh38", "ensembl")


@pytest.mark.parametrize("values", [[1, 2], ["chr1", 2], [1.0], [True]])
def test_non_string_chromosomes_are_not_coerced(values):
    with pytest.raises(ChromosomeNormalizationError, match="not coerced"):
        norm(values, "GRCh38", "ensembl")


def test_empty_dataframe_normalizes_with_an_explicit_assembly():
    empty = pd.DataFrame({"chr": pd.Series([], dtype="object"),
                          "start": pd.Series([], dtype="int64"),
                          "end": pd.Series([], dtype="int64")})
    result = normalize_chromosomes(empty, assembly="dm6", target="ensembl")
    pd.testing.assert_frame_equal(result.dataframe, empty)
    report = result.report
    assert (report.total_rows, report.unique_identifiers,
            report.resolved_identifiers, report.unresolved_identifiers,
            report.changed_rows) == (0, 0, 0, 0, 0)
    assert dict(report.collapses) == {} and report.complete
    with pytest.raises(ChromosomeNormalizationError):
        normalize_chromosomes(empty, assembly="", target="ensembl")


# --- resolved: changed vs unchanged ---------------------------------------------

def test_changed_and_unchanged_resolved_identifiers_are_distinguished():
    result = norm(["chr1", "1", "chr1", "chr2"], "GRCh38", "ensembl")
    assert chrs(result) == ["1", "1", "1", "2"]
    r = result.report
    assert (r.resolved_changed_identifiers, r.resolved_unchanged_identifiers,
            r.changed_rows) == (2, 1, 3)
    assert r.unique_identifiers == 3 and r.total_rows == 4
    assert r.resolved_identifiers == 3 and r.complete


def test_already_in_target_form_is_resolved_not_unresolved():
    result = norm(["chr1", "chr2"], "GRCh38", "ucsc")
    assert chrs(result) == ["chr1", "chr2"]
    r = result.report
    assert r.resolved_unchanged_identifiers == 2
    assert r.resolved_changed_identifiers == 0 and r.changed_rows == 0
    assert r.unresolved_identifiers == 0 and r.complete


def test_successful_unchanged_differs_from_failed_unchanged():
    result = norm(["chr1", "unknown_contig"], "GRCh38", "ucsc")
    assert chrs(result) == ["chr1", "unknown_contig"]
    r = result.report
    assert r.resolved_unchanged_identifiers == 1  # chr1: validated
    assert dict(r.unknown) == {"unknown_contig": 1}  # not validated
    assert not r.complete


def test_every_authority_can_be_a_target():
    expected = {"ucsc": "chr1", "assembly": "1", "ensembl": "1",
                "genbank": "CM000663.2", "refseq": "NC_000001.11"}
    for target, alias in expected.items():
        assert chrs(norm(["NC_000001.11"], "GRCh38", target)) == [alias]


# --- unresolved: unknown, no_alias_for_target, partial ---------------------------

@pytest.mark.parametrize("identifier", [
    "unknown_contig", "Chr1", "CHR1", "chr1 ", " chr1", "NC_000001", "chrMT",
    "M", "chr23", "01", "",
])
def test_exact_matching_only_unknown_identifiers_stay_verbatim(identifier):
    result = norm(["chr1", identifier], "GRCh38", "ensembl")
    assert chrs(result) == ["1", identifier]
    assert dict(result.report.unknown) == {identifier: 1}
    assert not result.report.no_alias_for_target


def test_no_alias_for_target_is_distinct_from_unknown():
    result = norm(["chr10_GL383545v1_alt", "nope"], "GRCh38", "ensembl")
    r = result.report
    assert chrs(result) == ["chr10_GL383545v1_alt", "nope"]
    assert dict(r.no_alias_for_target) == {"chr10_GL383545v1_alt": 1}
    assert dict(r.unknown) == {"nope": 1}
    assert r.unresolved_identifiers == 2 and r.unresolved_rows == 2


def test_partial_resolution_is_reported_explicitly():
    result = norm(["chr1", "chr2", "custom_contig", "custom_contig", "chr2"],
                  "GRCh38", "ensembl")
    assert chrs(result) == ["1", "2", "custom_contig", "custom_contig", "2"]
    r = result.report
    assert r.resolved_identifiers == 2 and r.unresolved_identifiers == 1
    assert dict(r.unknown) == {"custom_contig": 2}
    assert r.unresolved_rows == 2 and not r.complete


def test_no_marker_values_replace_unresolved_strings():
    out = chrs(norm(["x_y", " Z ", "NA", "."], "GRCh38", "ucsc"))
    assert out == ["x_y", " Z ", "NA", "."]


# --- strict mode --------------------------------------------------------------------

def test_strict_raises_with_the_full_report_and_returns_nothing_partial():
    df = frame(["chr1", "custom", "chr10_GL383545v1_alt"])
    with pytest.raises(StrictChromosomeNormalizationError) as caught:
        normalize_chromosomes(df, assembly="GRCh38", target="ensembl",
                              strict=True)
    report = caught.value.report
    assert dict(report.unknown) == {"custom": 1}
    assert dict(report.no_alias_for_target) == {"chr10_GL383545v1_alt": 1}
    lenient = normalize_chromosomes(df, assembly="GRCh38", target="ensembl")
    assert lenient.report == report  # same science; only raise vs. return
    assert isinstance(caught.value, ChromosomeNormalizationError)


def test_strict_succeeds_when_everything_resolves_even_with_collapse():
    result = norm(["chr1", "1"], "GRCh38", "ucsc", strict=True)
    assert chrs(result) == ["chr1", "chr1"]
    assert result.report.collapses["chr1"] == ("chr1", "1")


# --- many-to-one collapse -------------------------------------------------------------

def test_two_source_identifiers_collapsing_to_one_target_are_reported():
    result = norm(["1", "chr1", "NC_000001.11", "chr2"], "GRCh38", "ucsc")
    assert chrs(result) == ["chr1", "chr1", "chr1", "chr2"]
    assert dict(result.report.collapses) == {
        "chr1": ("1", "chr1", "NC_000001.11")}


def test_repeated_rows_of_one_identifier_are_not_a_collapse():
    result = norm(["chr1"] * 5 + ["chr2"] * 3, "GRCh38", "ensembl")
    assert dict(result.report.collapses) == {}


def test_unresolved_identifiers_never_count_as_collapse():
    result = norm(["chrM", "chrM", "x"], "dm6", "ensembl")
    assert dict(result.report.collapses) == {}


# --- invariants -------------------------------------------------------------------------

def test_only_the_chr_column_changes_and_everything_else_is_identical():
    index = [30, 10, 20, 40, 50]
    df = frame(["chr2", "chr1", "unknown", "chr1", "chrX"],
               extra_col=[1.5, None, 3.0, 4.0, 5.0])
    df.index = index
    result = normalize_chromosomes(df, assembly="GRCh38", target="ensembl")
    out = result.dataframe
    assert out["chr"].tolist() == ["2", "1", "unknown", "1", "X"]
    pd.testing.assert_frame_equal(out.drop(columns="chr"),
                                  df.drop(columns="chr"))
    assert list(out.columns) == list(df.columns)
    assert out.index.tolist() == index
    assert out["chr"].dtype == df["chr"].dtype
    assert out.shape == df.shape


def test_frame_is_unchanged_when_nothing_needs_normalizing():
    df = frame(["chr1", "chr2", "chrX"])
    out = normalize_chromosomes(df, assembly="GRCh38", target="ucsc").dataframe
    pd.testing.assert_frame_equal(out, df)


@pytest.mark.parametrize("dtype", ["object", "category", "string"])
def test_chromosome_column_dtype_variants(dtype):
    df = frame(["chr1", "chr1", "x"])
    df["chr"] = df["chr"].astype(dtype)
    result = normalize_chromosomes(df, assembly="GRCh38", target="ensembl")
    assert result.dataframe["chr"].astype(object).tolist() == ["1", "1", "x"]
    assert not result.dataframe["chr"].isna().any()  # no silent NaN
    assert dict(result.report.unknown) == {"x": 1}


# --- unique-identifier strategy -----------------------------------------------------------

def test_resolution_runs_once_per_unique_identifier(monkeypatch):
    calls = {"resolve": 0, "render": 0}
    resolve, render = ChromosomeRegistry.resolve, ChromosomeRegistry.render

    def counting_resolve(self, identifier):
        calls["resolve"] += 1
        return resolve(self, identifier)

    def counting_render(self, seq_id, authority):
        calls["render"] += 1
        return render(self, seq_id, authority)

    monkeypatch.setattr(ChromosomeRegistry, "resolve", counting_resolve)
    monkeypatch.setattr(ChromosomeRegistry, "render", counting_render)
    n = 60_000
    chroms = (["chr1", "1", "custom"] * (n // 3))
    df = pd.DataFrame({"chr": chroms, "start": range(n),
                       "end": [i + 1 for i in range(n)]})
    result = normalize_chromosomes(df, assembly="GRCh38", target="ucsc")
    assert calls == {"resolve": 3, "render": 2}
    assert result.report.total_rows == n and result.report.changed_rows == n // 3
    assert result.dataframe["chr"].value_counts().to_dict() == {
        "chr1": 2 * (n // 3), "custom": n // 3}


# --- representative real cases across all six assemblies -----------------------------------

def test_grch38_matrix():
    result = norm(["chr1", "1", "unknown"], "GRCh38", "ensembl")
    assert chrs(result) == ["1", "1", "unknown"]
    r = result.report
    assert (r.resolved_changed_identifiers, r.resolved_unchanged_identifiers,
            dict(r.unknown)) == (1, 1, {"unknown": 1})
    assert dict(r.collapses) == {"1": ("chr1", "1")}


def test_hg19_mitochondrial_records_stay_separate():
    result = norm(["chrM", "chrMT", "MT", "NC_001807.4"], "hg19", "ensembl")
    # chrM (NC_001807.4) has no Ensembl alias; chrMT / MT is Ensembl "MT".
    assert chrs(result) == ["chrM", "MT", "MT", "NC_001807.4"]
    r = result.report
    assert dict(r.no_alias_for_target) == {"chrM": 1, "NC_001807.4": 1}
    assert not r.unknown
    assert dict(r.collapses) == {"MT": ("chrMT", "MT")}
    # The legacy rewrite chrM -> MT must not reappear.
    assert chrs(norm(["chrM"], "hg19", "ensembl")) == ["chrM"]
    assert chrs(norm(["chrM", "chrMT"], "hg19", "refseq")) == [
        "NC_001807.4", "NC_012920.1"]


def test_hg19_primary_and_ensembl_evidence_alias():
    result = norm(["chr1", "chrUn_gl000211", "chr17_ctg5_hap1"], "hg19",
                  "ensembl")
    assert chrs(result) == ["1", "GL000211.1", "chr17_ctg5_hap1"]
    assert dict(result.report.no_alias_for_target) == {"chr17_ctg5_hap1": 1}


def test_grcm39_refseq_target():
    result = norm(["chr19", "19", "chrM"], "GRCm39", "refseq")
    assert chrs(result) == ["NC_000085.7", "NC_000085.7", "NC_005089.1"]
    assert dict(result.report.collapses) == {
        "NC_000085.7": ("chr19", "19")}


def test_dm6_non_human_names_and_missing_mitochondrial_ensembl_alias():
    result = norm(["chr2L", "chr2R", "chr3L", "chrX", "chrM", "chr2L"],
                  "dm6", "ensembl")
    assert chrs(result) == ["2L", "2R", "3L", "X", "chrM", "2L"]
    r = result.report
    assert dict(r.no_alias_for_target) == {"chrM": 1} and not r.unknown
    assert r.changed_rows == 5
    # Human conventions neither resolve nor leak in.
    out = norm(["chr1", "MT", "22"], "dm6", "ucsc")
    assert chrs(out) == ["chr1", "MT", "22"]
    assert set(out.report.unknown) == {"chr1", "MT", "22"}


def test_valid_authority_absent_for_the_whole_assembly():
    result = norm(["chr2L", "2L", "chrM"], "dm6", "assembly")
    assert chrs(result) == ["chr2L", "2L", "chrM"]  # unchanged
    r = result.report
    assert dict(r.no_alias_for_target) == {"chr2L": 1, "2L": 1, "chrM": 1}
    assert not r.unknown and r.resolved_identifiers == 0
    assert not r.complete
    # GRCz11 also has no assembly aliases.
    fish = norm(["chr25"], "GRCz11", "assembly")
    assert dict(fish.report.no_alias_for_target) == {"chr25": 1}


def test_grcz11_chromosomes_above_22_and_alt_without_ensembl_alias():
    result = norm(["chr25", "chr10_KZ114911v1_alt", "chrM"], "GRCz11",
                  "ensembl")
    assert chrs(result) == ["25", "chr10_KZ114911v1_alt", "MT"]
    assert dict(result.report.no_alias_for_target) == {
        "chr10_KZ114911v1_alt": 1}


def test_rn7_evidence_enriched_alias():
    result = norm(["chrUn_NW_023637723v1", "scaffold_23", "chrM"], "rn7",
                  "ensembl")
    assert chrs(result) == ["MU150194.1", "MU150194.1", "MT"]
    assert dict(result.report.collapses) == {
        "MU150194.1": ("chrUn_NW_023637723v1", "scaffold_23")}
    assert result.report.complete


def test_same_string_normalizes_differently_per_assembly():
    for assembly, expected in (("GRCh38", "NC_000001.11"),
                               ("hg19", "NC_000001.10"),
                               ("GRCm39", "NC_000067.7"),
                               ("rn7", "NC_051336.1"),
                               ("GRCz11", "NC_007112.7")):
        assert chrs(norm(["chr1"], assembly, "refseq")) == [expected]
    assert chrs(norm(["chr1"], "dm6", "refseq")) == ["chr1"]  # unknown in dm6


# --- rename map (single source of truth for downstream metadata) ----------------------------

def test_renames_contain_only_actual_string_changes():
    result = norm(["1", "chr1", "chr1", "custom", "chr10_GL383545v1_alt"],
                  "GRCh38", "ucsc")
    # chr1 and chr10_GL383545v1_alt are resolved but already UCSC; custom
    # is unknown: none of them is a rename.
    assert dict(result.report.renames) == {"1": "chr1"}
    assert list(result.report.renames) == ["1"]


def test_renames_exclude_unresolved_and_missing_target_aliases():
    result = norm(["chrM", "x", "chr1"], "hg19", "ensembl")
    assert dict(result.report.renames) == {"chr1": "1"}  # chrM: no alias
    assert dict(norm(["chr1"], "GRCh38", "ucsc").report.renames) == {}


def test_renames_are_deterministic_and_read_only():
    a = norm(["2", "1", "chr3"], "GRCh38", "ucsc").report.renames
    b = norm(["2", "1", "chr3"], "GRCh38", "ucsc").report.renames
    assert list(a) == list(b) == ["2", "1"]  # first appearance
    with pytest.raises(TypeError):
        a["9"] = "chr9"
