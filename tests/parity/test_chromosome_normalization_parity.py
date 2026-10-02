"""Chromosome normalization versus the two annotation engines.

Normalization happens once, before engine dispatch. For the same normalized
inputs, Bedtools and Polars-Bio must return identical canonical results, and
those results must equal hand-computed expectations. The registry itself is
not tested here (see tests/oracle/ and tests/test_chrom_registry_*.py); this
module checks scientific output after normalization.

Expected pairs are derived by hand from the canonical interval semantics
(0-based half-open overlap) and the documented assembly facts, never from a
backend.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
from tests.parity.comparator import (
    assert_canonical_equal,
    check_expected,
    interval_table,
    run_and_canonicalize,
)

ENGINES = [BedtoolsEngine, PolarsBioEngine]
ROOT = Path(__file__).resolve().parents[2]

# name -> (assembly, target, query rows, annotation rows, expected pairs
# after normalization for how="inner" / how="left"). Rows are
# (chr, start, end, label).
CASES = {
    # Different valid aliases of the same sequences meet after normalization.
    "grch38_aliases": {
        "assembly": "GRCh38", "target": "ucsc",
        "query": [("1", 100, 200, "q0"), ("chr2", 10, 20, "q1")],
        "annot": [("NC_000001.11", 150, 300, "a0"),
                  ("NC_000002.12", 0, 50, "a1"), ("chr1", 500, 600, "a2")],
        "inner": [(0, 0), (1, 1)], "left": [(0, 0), (1, 1)],
        "normalized_query": ["chr1", "chr2"],
        "normalized_annot": ["chr1", "chr2", "chr1"],
    },
    # hg19 chrM and chrMT are different sequences: chrM has no Ensembl name
    # and stays chrM; chrMT becomes MT. They must never meet each other.
    "hg19_mitochondria": {
        "assembly": "hg19", "target": "ensembl",
        "query": [("chrM", 0, 100, "q0"), ("chrMT", 0, 100, "q1")],
        "annot": [("chrMT", 50, 150, "a0"), ("MT", 10, 20, "a1"),
                  ("chrM", 0, 10, "a2")],
        "inner": [(0, 2), (1, 0), (1, 1)], "left": [(0, 2), (1, 0), (1, 1)],
        "normalized_query": ["chrM", "MT"],
        "normalized_annot": ["MT", "MT", "chrM"],
    },
    # Non-human naming: dm6 chr2L -> 2L, chrM has no Ensembl name.
    "dm6_non_human": {
        "assembly": "dm6", "target": "ensembl",
        "query": [("chr2L", 100, 200, "q0"), ("chrM", 0, 50, "q1"),
                  ("chrX", 50, 60, "q2")],
        "annot": [("2L", 150, 250, "a0"), ("chrM", 10, 20, "a1"),
                  ("X", 0, 100, "a2")],
        "inner": [(0, 0), (1, 1), (2, 2)], "left": [(0, 0), (1, 1), (2, 2)],
        "normalized_query": ["2L", "chrM", "X"],
        "normalized_annot": ["2L", "chrM", "X"],
    },
    # Partial normalization: unresolved identifiers stay verbatim and match
    # nothing they should not; the left join keeps the unmatched query.
    "partial_unresolved": {
        "assembly": "GRCh38", "target": "ucsc",
        "query": [("1", 0, 100, "q0"), ("mystery", 0, 100, "q1"),
                  ("NC_000001.10", 0, 100, "q2")],
        "annot": [("chr1", 50, 60, "a0"), ("unseen", 0, 10, "a1")],
        "inner": [(0, 0)], "left": [(0, 0), (1, None), (2, None)],
        "normalized_query": ["chr1", "mystery", "NC_000001.10"],
        "normalized_annot": ["chr1", "unseen"],
    },
}


def _tables(case):
    query = interval_table([r[0] for r in case["query"]],
                           [r[1] for r in case["query"]],
                           [r[2] for r in case["query"]],
                           name=[r[3] for r in case["query"]])
    annot = interval_table([r[0] for r in case["annot"]],
                           [r[1] for r in case["annot"]],
                           [r[2] for r in case["annot"]],
                           name=[r[3] for r in case["annot"]])
    return query, annot


def _normalized(case):
    query, annot = _tables(case)
    return normalize_input_chromosomes(
        query, annot, assembly=case["assembly"], target=case["target"])


@pytest.mark.parametrize("name", sorted(CASES))
class TestNormalizedInputsAreIdenticalForBothEngines:
    def test_normalized_names_are_the_documented_ones(self, name):
        case = CASES[name]
        out = _normalized(case)
        assert out.coord_df["chr"].tolist() == case["normalized_query"]
        assert out.annot_df["chr"].tolist() == case["normalized_annot"]

    @pytest.mark.parametrize("how", ["inner", "left"])
    @pytest.mark.parametrize("engine_cls", ENGINES, ids=lambda c: c.__name__)
    def test_each_engine_matches_the_hand_computed_result(
            self, name, how, engine_cls):
        case = CASES[name]
        out = _normalized(case)
        check_expected(engine_cls, out.coord_df, out.annot_df,
                       pairs=case[how], how=how,
                       label=f"{name}/{how}/{engine_cls.__name__}")

    @pytest.mark.parametrize("how", ["inner", "left"])
    def test_bedtools_and_polars_bio_agree(self, name, how):
        out = _normalized(CASES[name])
        bedtools = run_and_canonicalize(
            BedtoolsEngine, out.coord_df, out.annot_df, how=how)
        polars = run_and_canonicalize(
            PolarsBioEngine, out.coord_df, out.annot_df, how=how)
        assert_canonical_equal(bedtools, polars, label=f"{name}/{how} parity")

    def test_coordinates_and_metadata_survive_in_the_canonical_result(
            self, name):
        case = CASES[name]
        out = _normalized(case)
        result = run_and_canonicalize(
            BedtoolsEngine, out.coord_df, out.annot_df, how="left")
        queries = {r[3]: r for r in case["query"]}
        for _, row in result.iterrows():
            _, start, end, _label = queries[row["coord_name"]]
            assert (row["coord_start"], row["coord_end"]) == (start, end)


def test_hg19_chrM_never_matches_chrMT_after_normalization():
    """The scientific point of the hg19 case, stated on its own."""
    case = CASES["hg19_mitochondria"]
    out = _normalized(case)
    for engine_cls in ENGINES:
        result = run_and_canonicalize(
            engine_cls, out.coord_df, out.annot_df, how="inner")
        pairs = set(zip(result["coord_name"], result["annot_name"]))
        assert ("q0", "a0") not in pairs and ("q0", "a1") not in pairs
        assert pairs == {("q0", "a2"), ("q1", "a0"), ("q1", "a1")}


@pytest.mark.parametrize("engine_cls", ENGINES, ids=lambda c: c.__name__)
def test_without_normalization_the_alias_tables_do_not_meet(engine_cls):
    """Sensitivity: the matches above exist because of normalization."""
    query, annot = _tables(CASES["grch38_aliases"])
    result = run_and_canonicalize(engine_cls, query, annot, how="inner")
    assert len(result) == 0


# ---- normalization stays upstream of engine dispatch -------------------------

def test_engine_modules_never_import_chromosome_normalization():
    """Structural: no engine can normalize on its own."""
    tree = ast.parse((ROOT / "streamlit_app" / "core" / "annotator.py")
                     .read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add((node.module or "") + "|"
                        + ",".join(a.name for a in node.names))
        elif isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
    joined = " ".join(sorted(modules)).lower()
    for forbidden in ("chrom_registry", "chromosome_normalization",
                      "chromosome_inputs", "normalize_chromosomes",
                      "load_registry"):
        assert forbidden not in joined, forbidden


def test_the_app_normalizes_once_and_both_engines_receive_the_same_tables(
        monkeypatch):
    from streamlit.testing.v1 import AppTest

    import streamlit_app.core.chromosome_inputs as inputs

    entry = ROOT / "streamlit_app" / "streamlit_app.py"
    received = []
    calls = []

    def spy(cls):
        original = cls.intersect

        def wrapped(self, coord_df, annot_df, *args, **kwargs):
            received.append((cls.__name__, coord_df.copy(), annot_df.copy()))
            return original(self, coord_df, annot_df, *args, **kwargs)
        monkeypatch.setattr(cls, "intersect", wrapped)

    for cls in ENGINES:
        spy(cls)
    real = inputs.normalize_input_chromosomes

    def counting(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(inputs, "normalize_input_chromosomes", counting)

    def widget(at, kind, key):
        return next(e for e in at.get(kind) if getattr(e, "key", None) == key)

    for engine in ("Bedtools", "Polars-Bio"):
        at = AppTest.from_file(str(entry), default_timeout=120)
        at.run()
        widget(at, "radio", "engine").set_value(engine)
        widget(at, "selectbox", "chr_assembly").set_value("Human — Feb. 2009 (GRCh37/hg19)")
        widget(at, "selectbox", "chr_naming").set_value("Ensembl names")
        widget(at, "file_uploader", "coord_file").set_value(
            ("q.bed", b"chrM\t0\t100\tq0\nchrMT\t0\t100\tq1\n", "text/plain"))
        gff = (b"##gff-version 3\nMT\tsrc\tgene\t11\t20\t.\t+\t.\tID=g1\n"
               b"chrM\tsrc\tgene\t1\t10\t.\t+\t.\tID=g2\n")
        widget(at, "file_uploader", "annot_file").set_value(
            ("a.gff3", gff, "text/plain"))
        at.run()
        widget(at, "button", "run_button").set_value(True)
        at.run()
        assert not at.exception

    assert len(calls) == 2                       # one normalization per run
    assert [c["assembly"] for c in calls] == ["hg19", "hg19"]
    assert [c["target"] for c in calls] == ["ensembl", "ensembl"]
    assert [r[0] for r in received] == ["BedtoolsEngine", "PolarsBioEngine"]
    (_, bq, ba), (_, pq, pa) = received
    # Both engines were handed the already-normalized tables, equal to each
    # other: chrM kept (no verified Ensembl name), chrMT -> MT.
    assert bq["chr"].tolist() == ["chrM", "MT"] == pq["chr"].tolist()
    assert ba["chr"].tolist() == ["MT", "chrM"] == pa["chr"].tolist()
    assert bq.equals(pq) and ba.equals(pa)
