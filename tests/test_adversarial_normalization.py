"""Adversarial review (Task 10): partial resolution, collapse, dtypes,
strict mode and bundled/custom equivalence.

The central check is a brute-force model written independently of the
production normalizer: random registries and tables are normalized by both
and every output value and report field must agree.
"""

from __future__ import annotations

import ast
import csv
import io
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from streamlit_app.core.chrom_registry import (
    AUTHORITIES,
    CUSTOM_HEADER,
    ChromosomeRegistry,
    SequenceRecord,
    builder,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.chromosome_inputs import (
    StrictInputNormalizationError,
    normalize_input_chromosomes,
)
from streamlit_app.core.chromosome_normalization import (
    ChromosomeNormalizationError,
    StrictChromosomeNormalizationError,
    normalize_chromosomes_with_registry,
)

CORE = Path(__file__).resolve().parent.parent / "streamlit_app" / "core"


def frame(names, dtype=None):
    chr_col = pd.Series(list(names), dtype=dtype) if dtype else list(names)
    n = len(names)
    return pd.DataFrame({"chr": chr_col, "start": range(n),
                         "end": range(1, n + 1), "name": [f"r{i}" for i in range(n)]})


# ---- brute-force model ------------------------------------------------------------

def random_registry(rng: random.Random):
    pool = [f"{p}{i}" for p in ("a", "B", "c_", "1", "NC_0", "chr", "x y")
            for i in range(12)]
    rng.shuffle(pool)
    records, owner = {}, {}
    for n in range(rng.randint(1, 8)):
        aliases = {}
        for authority in AUTHORITIES:
            if pool and rng.random() < 0.6:
                aliases[authority] = pool.pop()
        if not aliases:
            aliases["ucsc"] = pool.pop()
        records[f"r{n}"] = SequenceRecord(f"r{n}", aliases)
        for alias in aliases.values():
            owner[alias] = f"r{n}"
    return ChromosomeRegistry("R", records), records, owner, pool


def model(identifiers, records, owner, target):
    """Expected output values and report fields, computed by hand."""
    out, unknown, no_alias, renames, targets = [], {}, {}, {}, {}
    changed_rows = 0
    for ident in identifiers:
        rec = owner.get(ident)
        if rec is None:
            unknown[ident] = unknown.get(ident, 0) + 1
            out.append(ident)
            continue
        alias = records[rec].aliases.get(target)
        if alias is None:
            no_alias[ident] = no_alias.get(ident, 0) + 1
            out.append(ident)
            continue
        out.append(alias)
        targets.setdefault(alias, [])
        if ident not in targets[alias]:
            targets[alias].append(ident)
        if alias != ident:
            renames[ident] = alias
            changed_rows += 1
    collapses = {a: tuple(s) for a, s in targets.items() if len(s) > 1}
    return out, unknown, no_alias, renames, collapses, changed_rows


@pytest.mark.parametrize("seed", range(250))
def test_normalizer_equals_the_brute_force_model(seed):
    rng = random.Random(seed)
    registry, records, owner, _ = random_registry(rng)
    names = list(owner) + [f"nope{i}" for i in range(3)] + ["", " a0", "A0"]
    identifiers = [rng.choice(names) for _ in range(rng.randint(0, 40))]
    target = rng.choice(AUTHORITIES)
    result = normalize_chromosomes_with_registry(
        frame(identifiers), registry=registry, target=target)
    out, unknown, no_alias, renames, collapses, changed_rows = model(
        identifiers, records, owner, target)
    report = result.report
    assert result.dataframe["chr"].tolist() == out
    assert dict(report.unknown) == unknown
    assert dict(report.no_alias_for_target) == no_alias
    assert dict(report.renames) == renames
    assert dict(report.collapses) == collapses
    assert report.changed_rows == changed_rows
    # report totals reconcile with the dataframe
    assert report.total_rows == len(identifiers)
    assert report.unique_identifiers == len(set(identifiers))
    resolved_rows = sum(1 for i in identifiers if i in owner
                        and target in records[owner[i]].aliases)
    assert resolved_rows + report.unresolved_rows == len(identifiers)
    assert (report.resolved_identifiers + report.unresolved_identifiers
            == report.unique_identifiers)
    unchanged_rows = sum(1 for before, after in zip(identifiers, out)
                         if before == after)
    assert unchanged_rows == len(identifiers) - changed_rows
    # nothing but the chr column changed
    original = frame(identifiers)
    for column in ("start", "end", "name"):
        assert result.dataframe[column].tolist() == original[column].tolist()
    # a kept-verbatim identifier is never also the target of a rendering
    kept = set(report.unknown) | set(report.no_alias_for_target)
    rendered = {a for ident in identifiers if ident in owner
                for a in [records[owner[ident]].aliases.get(target)] if a}
    assert kept.isdisjoint(rendered)
    # reproducible
    again = normalize_chromosomes_with_registry(
        frame(identifiers), registry=registry, target=target)
    assert again.report == report
    assert again.dataframe.equals(result.dataframe)


# ---- 10/11. mixed tables: every category at once ---------------------------------------

def mixed_registry():
    rec = {
        # resolvable + target (ensembl) available
        "s1": SequenceRecord("s1", {"ucsc": "chrA", "ensembl": "A",
                                    "genbank": "GA.1"}),
        # resolvable, no ensembl alias
        "s2": SequenceRecord("s2", {"ucsc": "chrB", "genbank": "GB.1"}),
        # target alias equals one of its own spellings (already in target)
        "s3": SequenceRecord("s3", {"ucsc": "chrC", "ensembl": "C"}),
        # many sources to one target
        "s4": SequenceRecord("s4", {"ucsc": "chrD", "ensembl": "D",
                                    "genbank": "GD.1", "refseq": "RD.1",
                                    "assembly": "d-asm"}),
    }
    return ChromosomeRegistry("MIX", rec)


MIXED = ["chrA", "A", "chrB", "GB.1", "C", "chrC", "mystery", "mystery",
         "chrD", "GD.1", "RD.1", "d-asm", "D", "other", "chrB"]


def test_mixed_table_every_category_is_accounted_for_once():
    result = normalize_chromosomes_with_registry(
        frame(MIXED), registry=mixed_registry(), target="ensembl")
    report = result.report
    assert result.dataframe["chr"].tolist() == [
        "A", "A", "chrB", "GB.1", "C", "C", "mystery", "mystery",
        "D", "D", "D", "D", "D", "other", "chrB"]
    assert dict(report.unknown) == {"mystery": 2, "other": 1}
    assert dict(report.no_alias_for_target) == {"chrB": 2, "GB.1": 1}
    assert dict(report.renames) == {"chrA": "A", "chrC": "C", "chrD": "D",
                                    "GD.1": "D", "RD.1": "D", "d-asm": "D"}
    assert dict(report.collapses) == {
        "A": ("chrA", "A"), "C": ("C", "chrC"),
        "D": ("chrD", "GD.1", "RD.1", "d-asm", "D")}
    assert report.total_rows == 15
    assert report.changed_rows == 1 + 1 + 4         # chrA, chrC, chrD+3 aliases
    assert report.unresolved_rows == 3 + 3          # 2+1 unknown, 2+1 no-alias
    assert (report.resolved_changed_identifiers,
            report.resolved_unchanged_identifiers) == (6, 3)
    assert not report.complete


def test_unknown_and_no_alias_never_absorb_each_other():
    only_unknown = normalize_chromosomes_with_registry(
        frame(["zzz"]), registry=mixed_registry(), target="ensembl").report
    only_no_alias = normalize_chromosomes_with_registry(
        frame(["chrB"]), registry=mixed_registry(), target="ensembl").report
    assert (dict(only_unknown.unknown), dict(only_unknown.no_alias_for_target)
            ) == ({"zzz": 1}, {})
    assert (dict(only_no_alias.unknown),
            dict(only_no_alias.no_alias_for_target)) == ({}, {"chrB": 1})


@pytest.mark.parametrize("names,kind", [(["zzz"], "unknown"),
                                        (["chrB"], "no_alias")])
def test_strict_mode_raises_for_each_kind_with_the_full_report(names, kind):
    with pytest.raises(StrictChromosomeNormalizationError) as caught:
        normalize_chromosomes_with_registry(
            frame(names), registry=mixed_registry(), target="ensembl",
            strict=True)
    report = caught.value.report
    if kind == "unknown":
        assert dict(report.unknown) == {"zzz": 1} and not report.no_alias_for_target
        assert "1 unknown and 0 identifiers" in str(caught.value)
    else:
        assert dict(report.no_alias_for_target) == {"chrB": 1} and not report.unknown
        assert "0 unknown and 1 identifiers" in str(caught.value)


def test_strict_dual_input_raises_when_either_table_is_incomplete():
    reg = mixed_registry()
    good, bad = frame(["chrA", "C"]), frame(["chrA", "zzz"])
    for coord, annot in ((good, bad), (bad, good)):
        with pytest.raises(StrictInputNormalizationError) as caught:
            normalize_input_chromosomes(coord, annot, registry=reg,
                                        target="ensembl", strict=True)
        error = caught.value
        assert (error.coord_report.complete) != (error.annot_report.complete)
    ok = normalize_input_chromosomes(good, good, registry=reg,
                                     target="ensembl", strict=True)
    assert ok.complete


# ---- 12. collapse: many-to-one in every combination -------------------------------------

@pytest.mark.parametrize("sources,expected", [
    (["chrA", "A"], ("chrA", "A")),
    (["chrD", "GD.1", "RD.1"], ("chrD", "GD.1", "RD.1")),
    (["d-asm", "RD.1", "GD.1", "chrD", "D"],
     ("d-asm", "RD.1", "GD.1", "chrD", "D")),
])
@pytest.mark.parametrize("where", ["query", "annotation", "both"])
def test_collapses_are_reported_per_table_and_lose_no_source(
        sources, expected, where):
    reg = mixed_registry()
    noise = ["zzz", "chrB", "zzz"]       # unknown and no-target in the frame
    rows = [s for s in sources for _ in range(2)] + noise      # repeated rows
    empty = ["chrC"]
    coord, annot = ((rows, empty) if where == "query" else
                    (empty, rows) if where == "annotation" else (rows, rows))
    out = normalize_input_chromosomes(frame(coord), frame(annot), registry=reg,
                                      target="ensembl")
    target = {"chrA": "A", "A": "A"}.get(sources[0], "D")
    for table, report, names in (("q", out.coord_report, coord),
                                 ("a", out.annot_report, annot)):
        if names is rows:
            assert dict(report.collapses) == {target: expected}, table
            # every source identifier is still individually accounted for
            seen = set(report.renames) | {
                s for s in names if s == target and s in expected}
            assert set(expected) <= seen | set(report.collapses[target])
            assert dict(report.unknown) == {"zzz": 2}
            assert dict(report.no_alias_for_target) == {"chrB": 1}
        else:
            assert not report.collapses
    assert out.coord_collapses == dict(out.coord_report.collapses)


def test_collapse_is_informational_never_an_error_at_normalization_level():
    out = normalize_chromosomes_with_registry(
        frame(["chrD", "GD.1", "RD.1"]), registry=mixed_registry(),
        target="ensembl", strict=True)             # strict only gates unresolved
    assert out.dataframe["chr"].tolist() == ["D", "D", "D"]
    assert out.report.collapses == {"D": ("chrD", "GD.1", "RD.1")}


# ---- 23. nulls and dtypes ------------------------------------------------------------------

def _chr_frame(values, dtype=None):
    series = pd.Series(values, dtype=dtype)
    return pd.DataFrame({"chr": series, "start": range(len(series)),
                         "end": range(1, len(series) + 1)})


@pytest.mark.parametrize("values,dtype", [
    ([None, "chrA"], object), ([np.nan, "chrA"], object),
    (["chrA", pd.NA], "string"), (["chrA", None], "category"),
])
def test_null_identifiers_are_rejected_not_treated_as_unknown(values, dtype):
    with pytest.raises(ChromosomeNormalizationError, match="null"):
        normalize_chromosomes_with_registry(
            _chr_frame(values, dtype), registry=mixed_registry(), target="ucsc")


@pytest.mark.parametrize("values,dtype", [
    ([1, 2], "int64"), ([1.0, 2.5], "float64"), (["chrA", 3], object),
    ([b"chrA"], object), ([("chrA",)], object), ([True, False], "bool"),
])
def test_non_string_identifiers_are_rejected_and_never_coerced(values, dtype):
    with pytest.raises(ChromosomeNormalizationError, match="must be str"):
        normalize_chromosomes_with_registry(
            _chr_frame(values, dtype), registry=mixed_registry(), target="ucsc")


def test_string_extension_and_categorical_dtypes_are_supported_and_kept():
    reg = mixed_registry()
    pd_string = normalize_chromosomes_with_registry(
        _chr_frame(["chrA", "zzz"], "string"), registry=reg, target="ensembl")
    assert pd_string.dataframe["chr"].dtype == "string"
    assert pd_string.dataframe["chr"].tolist() == ["A", "zzz"]
    cat = normalize_chromosomes_with_registry(
        _chr_frame(["chrA", "zzz", "chrA"], "category"), registry=reg,
        target="ensembl")
    assert isinstance(cat.dataframe["chr"].dtype, pd.CategoricalDtype)
    assert cat.dataframe["chr"].astype(str).tolist() == ["A", "zzz", "A"]
    assert dict(cat.report.unknown) == {"zzz": 1}


def test_unused_categories_do_not_become_unknown_identifiers():
    series = pd.Categorical(["chrA"], categories=["chrA", "never-used"])
    df = pd.DataFrame({"chr": series, "start": [0], "end": [1]})
    out = normalize_chromosomes_with_registry(
        df, registry=mixed_registry(), target="ensembl")
    assert not out.report.unknown and out.report.total_rows == 1


def test_empty_and_zero_row_frames():
    reg = mixed_registry()
    for df in (pd.DataFrame({"chr": pd.Series([], dtype=object),
                             "start": [], "end": []}),
               pd.DataFrame({"chr": pd.Series([], dtype="string"),
                             "start": [], "end": []})):
        out = normalize_chromosomes_with_registry(df, registry=reg,
                                                  target="ensembl")
        assert out.report.total_rows == 0 and out.report.complete
        assert len(out.dataframe) == 0 and out.dataframe.columns.tolist() == [
            "chr", "start", "end"]


def test_all_unknown_frame_is_returned_verbatim_and_reported():
    names = ["u1", "u2", "u1"]
    out = normalize_chromosomes_with_registry(
        frame(names), registry=mixed_registry(), target="ensembl")
    assert out.dataframe["chr"].tolist() == names
    assert dict(out.report.unknown) == {"u1": 2, "u2": 1}
    assert out.report.changed_rows == 0 and not out.report.renames


def test_the_input_dataframe_is_never_modified():
    df = frame(["chrA", "zzz"])
    before = df.copy(deep=True)
    normalize_chromosomes_with_registry(df, registry=mixed_registry(),
                                        target="ensembl")
    assert df.equals(before)


def test_a_missing_chr_column_and_a_non_registry_are_clear_errors():
    with pytest.raises(ChromosomeNormalizationError, match="no 'chr' column"):
        normalize_chromosomes_with_registry(
            pd.DataFrame({"x": [1]}), registry=mixed_registry(), target="ucsc")
    with pytest.raises(ChromosomeNormalizationError, match="ChromosomeRegistry"):
        normalize_chromosomes_with_registry(
            frame(["a"]), registry="GRCh38", target="ucsc")


# ---- 18. bundled/custom equivalence over whole registries ---------------------------------

def _custom_from_bundled(assembly: str) -> ChromosomeRegistry:
    """The *entire* bundled registry re-expressed as a custom mapping."""
    text = (builder.PACKAGE_DIR / "data" / f"{assembly}.tsv").read_text()
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(CUSTOM_HEADER)
    for row in csv.DictReader(text.splitlines(), delimiter="\t"):
        writer.writerow([row[c] for c in CUSTOM_HEADER])
    return load_custom_registry(out.getvalue().encode("utf-8"))


@pytest.mark.parametrize("assembly", ["GRCh38", "hg19", "dm6", "GRCz11"])
def test_full_registry_as_custom_mapping_behaves_identically(assembly):
    bundled = load_registry(assembly)
    custom = _custom_from_bundled(assembly)
    assert len(custom) == len(bundled)
    assert custom.assembly_id is None and bundled.assembly_id == assembly
    names = sorted({a for s in bundled for a in bundled.record(s).aliases.values()})
    names += ["nope", "", "chr1 ", "MT", "chrMT", "chrM", "1", "X"]
    rng = random.Random(assembly)
    rows = [rng.choice(names) for _ in range(2000)]
    other = [rng.choice(names) for _ in range(500)]
    for target in AUTHORITIES:
        a = normalize_chromosomes_with_registry(
            frame(rows), registry=bundled, target=target)
        b = normalize_chromosomes_with_registry(
            frame(rows), registry=custom, target=target)
        assert a.dataframe.equals(b.dataframe)
        for field in ("target", "total_rows", "unique_identifiers",
                      "resolved_changed_identifiers",
                      "resolved_unchanged_identifiers", "changed_rows",
                      "renames", "unknown", "no_alias_for_target", "collapses"):
            assert getattr(a.report, field) == getattr(b.report, field), field
        da = normalize_input_chromosomes(frame(rows), frame(other),
                                         registry=bundled, target=target)
        db = normalize_input_chromosomes(frame(rows), frame(other),
                                         registry=custom, target=target)
        assert da.coord_df.equals(db.coord_df) and da.annot_df.equals(db.annot_df)
        assert da.coord_renames == db.coord_renames
        assert da.annot_collapses == db.annot_collapses
        strict = []
        for reg in (bundled, custom):
            try:
                normalize_chromosomes_with_registry(
                    frame(rows), registry=reg, target=target, strict=True)
                strict.append(None)
            except StrictChromosomeNormalizationError as exc:
                strict.append((dict(exc.report.unknown),
                               dict(exc.report.no_alias_for_target)))
        assert strict[0] == strict[1]
    # resolve and render agree on every alias
    for name in names:
        rb, rc = bundled.resolve(name), custom.resolve(name)
        assert rb.resolved == rc.resolved
        if rb.resolved:
            for authority in AUTHORITIES:
                assert (bundled.render(rb.seq_id, authority).alias
                        == custom.render(rc.seq_id, authority).alias)


def test_hg19_mitochondria_stay_distinct_through_a_custom_copy():
    custom = _custom_from_bundled("hg19")
    out = normalize_chromosomes_with_registry(
        frame(["chrM", "chrMT", "MT", "NC_001807.4", "NC_012920.1"]),
        registry=custom, target="ensembl")
    assert out.dataframe["chr"].tolist() == ["chrM", "MT", "MT", "NC_001807.4", "MT"]
    assert dict(out.report.no_alias_for_target) == {"chrM": 1,
                                                    "NC_001807.4": 1}
    assert out.report.collapses == {"MT": ("chrMT", "MT", "NC_012920.1")}


def test_no_custom_specific_branch_exists_after_registry_selection():
    """Static: the shared normalization modules never mention the custom
    loader or branch on the registry's assembly identity."""
    for name in ("chromosome_normalization.py", "chromosome_inputs.py"):
        tree = ast.parse((CORE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            ident = getattr(node, "id", None) or getattr(node, "attr", None)
            if isinstance(ident, str):
                assert "custom" not in ident.lower(), (name, ident)
            if isinstance(node, ast.Compare):
                text = ast.unparse(node)
                assert "assembly_id" not in text, (name, text)
