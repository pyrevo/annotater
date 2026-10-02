"""Backend orchestration: both input tables under one assembly/target."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from streamlit_app.core.chrom_registry import (
    ChromosomeRegistry,
    UnsupportedAssemblyError,
    UnsupportedAuthorityError,
)
from streamlit_app.core.chromosome_inputs import (
    InputChromosomeNormalization,
    StrictInputNormalizationError,
    normalize_input_chromosomes,
)
from streamlit_app.core.chromosome_normalization import (
    ChromosomeNormalizationError,
)


def table(chroms, **extra):
    n = len(chroms)
    data = {"chr": chroms, "start": list(range(10, 10 + n)),
            "end": [i + 5 for i in range(10, 10 + n)],
            "strand": ["+"] * n, "name": [f"n{i}" for i in range(n)]}
    data.update(extra)
    return pd.DataFrame(data)


def run(coord, annot, assembly="GRCh38", target="ensembl", **kw):
    return normalize_input_chromosomes(
        table(coord), table(annot), assembly=assembly, target=target, **kw)


def test_both_tables_are_normalized_under_one_assembly_and_target():
    out = run(["chr1", "chr2"], ["1", "2"])
    assert isinstance(out, InputChromosomeNormalization)
    assert out.coord_df["chr"].tolist() == ["1", "2"]
    assert out.annot_df["chr"].tolist() == ["1", "2"]
    # The two tables now share identifiers although they started apart.
    assert set(out.coord_df["chr"]) == set(out.annot_df["chr"])
    assert (out.assembly, out.target) == ("GRCh38", "ensembl")
    assert (out.coord_report.assembly, out.annot_report.assembly) == (
        "GRCh38", "GRCh38")
    assert (out.coord_report.target, out.annot_report.target) == (
        "ensembl", "ensembl")
    assert out.complete


def test_reports_are_independent_per_table():
    out = run(["chr1", "chr2", "custom"], ["1", "2", "X"])
    assert dict(out.coord_report.unknown) == {"custom": 1}
    assert not out.annot_report.unknown
    assert out.coord_report.resolved_changed_identifiers == 2
    assert out.annot_report.resolved_unchanged_identifiers == 3
    assert out.coord_df["chr"].tolist() == ["1", "2", "custom"]  # verbatim
    assert not out.complete


def test_no_alias_for_target_in_one_table_only():
    out = run(["chr1"], ["chr1", "chr10_GL383545v1_alt"])
    assert not out.coord_report.no_alias_for_target
    assert dict(out.annot_report.no_alias_for_target) == {
        "chr10_GL383545v1_alt": 1}
    assert out.annot_df["chr"].tolist() == ["1", "chr10_GL383545v1_alt"]


def test_collapse_in_the_coordinate_table_only():
    out = run(["1", "chr1", "chr2"], ["chr1", "chr2"], target="ucsc")
    assert dict(out.coord_collapses) == {"chr1": ("1", "chr1")}
    assert dict(out.annot_collapses) == {}
    assert out.coord_df["chr"].tolist() == ["chr1", "chr1", "chr2"]


def test_collapse_in_the_annotation_table_only():
    out = run(["chr1"], ["1", "NC_000001.11", "chr1"], target="ucsc")
    assert dict(out.coord_collapses) == {}
    assert dict(out.annot_collapses) == {
        "chr1": ("1", "NC_000001.11", "chr1")}


def test_rename_maps_come_from_the_reports_and_exclude_non_renames():
    out = run(["1", "chr1", "custom", "chr10_GL383545v1_alt"],
              ["chr2", "x"], target="ucsc")
    # chr1 resolved-unchanged, custom unknown: neither is a rename.
    assert dict(out.coord_renames) == {"1": "chr1"}
    assert out.coord_renames is out.coord_report.renames
    # chr10_GL383545v1_alt is resolved and already UCSC: no rename either.
    assert dict(out.annot_renames) == {}
    unresolved = run(["chr10_GL383545v1_alt", "nope"], ["chr1"])
    assert dict(unresolved.coord_renames) == {}  # no-alias + unknown
    with pytest.raises(TypeError):
        out.coord_renames["x"] = "y"


def test_assembly_and_target_are_explicit_and_never_defaulted():
    with pytest.raises(TypeError):
        normalize_input_chromosomes(table(["chr1"]), table(["chr1"]))
    for bad in (None, ""):
        with pytest.raises(ChromosomeNormalizationError):
            run(["chr1"], ["chr1"], assembly=bad)
    with pytest.raises(UnsupportedAssemblyError):
        run(["chr1"], ["chr1"], assembly="HG38")
    with pytest.raises(UnsupportedAuthorityError):
        run(["chr1"], ["chr1"], target="UCSC")


def test_same_assembly_changes_both_tables_consistently():
    out = run(["chrM", "chrMT"], ["MT", "chrM"], assembly="hg19")
    assert out.coord_df["chr"].tolist() == ["chrM", "MT"]
    assert out.annot_df["chr"].tolist() == ["MT", "chrM"]
    assert dict(out.coord_report.no_alias_for_target) == {"chrM": 1}
    assert dict(out.annot_report.no_alias_for_target) == {"chrM": 1}


def test_non_human_assembly_dual_table():
    out = run(["chr2L", "chrM"], ["2L", "2R"], assembly="dm6")
    assert out.coord_df["chr"].tolist() == ["2L", "chrM"]
    assert out.annot_df["chr"].tolist() == ["2L", "2R"]
    assert dict(out.coord_report.no_alias_for_target) == {"chrM": 1}


def test_inputs_are_not_mutated_and_other_columns_identical():
    coord, annot = table(["chr1", "x"]), table(["1", "y"])
    before = (coord.copy(deep=True), annot.copy(deep=True))
    out = normalize_input_chromosomes(coord, annot, assembly="GRCh38",
                                      target="ucsc")
    pd.testing.assert_frame_equal(coord, before[0])
    pd.testing.assert_frame_equal(annot, before[1])
    pd.testing.assert_frame_equal(out.coord_df.drop(columns="chr"),
                                  coord.drop(columns="chr"))
    pd.testing.assert_frame_equal(out.annot_df.drop(columns="chr"),
                                  annot.drop(columns="chr"))


def test_result_is_immutable():
    out = run(["chr1"], ["1"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.assembly = "hg19"


def test_strict_raises_with_both_reports_and_lenient_does_not():
    with pytest.raises(StrictInputNormalizationError) as caught:
        run(["chr1", "custom"], ["1", "chr10_GL383545v1_alt"], strict=True)
    assert dict(caught.value.coord_report.unknown) == {"custom": 1}
    assert dict(caught.value.annot_report.no_alias_for_target) == {
        "chr10_GL383545v1_alt": 1}
    assert isinstance(caught.value, ChromosomeNormalizationError)
    assert not run(["chr1", "custom"], ["1"]).complete  # lenient returns
    assert run(["chr1"], ["1"], strict=True).complete


def test_each_table_is_normalized_exactly_once(monkeypatch):
    calls = []
    resolve = ChromosomeRegistry.resolve

    def spy(self, identifier):
        calls.append(identifier)
        return resolve(self, identifier)

    monkeypatch.setattr(ChromosomeRegistry, "resolve", spy)
    out = run(["chr1"] * 50 + ["x"], ["1"] * 40 + ["chr2"] * 10)
    assert sorted(calls) == sorted(["chr1", "x", "1", "chr2"])
    assert out.coord_report.total_rows == 51
