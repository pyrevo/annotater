"""Every declared chromosome-naming fact, checked against pinned upstream data.

The fixture's expected outcomes/outputs are recomputed here from the
independent alias oracle (``chrom_reference``) alone: no production code, no
generated registry. ``tests/test_chromosome_semantic_examples.py`` then checks
the same facts against the real normalization.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.oracle import chrom_reference as ref

FIXTURE = (Path(__file__).resolve().parent.parent
           / "fixtures" / "semantic_examples.json")
EXAMPLES = [e for e in json.loads(FIXTURE.read_text())["examples"]
            if e["kind"] == "chromosome_naming"]
ORACLES = {a: ref.build_oracle(a) for a in ref.sources()}

REQUIRED = {
    "chromosome_accession_identity", "chromosome_hg19_mitochondria",
    "chromosome_dm6_non_human", "chromosome_wrong_assembly",
    "chromosome_many_to_one", "chromosome_coordinates_preserved",
}


def _outcome(oracle, identifier, target):
    chrom = oracle.resolve(identifier)
    if chrom is None:
        return "unknown", identifier
    alias = oracle.render(chrom, target)
    if alias is None:
        return "no_alias_for_target", identifier
    return ("unchanged" if alias == identifier else "renamed"), alias


def test_required_examples_exist_and_stay_small():
    assert REQUIRED <= {e["name"] for e in EXAMPLES}
    assert len(EXAMPLES) <= 6      # distinct failure modes, not one per assembly
    assert len({e["assembly"] for e in EXAMPLES}) <= 3


@pytest.mark.parametrize("ex", EXAMPLES, ids=lambda e: e["name"])
class TestDeclaredFactsMatchUpstream:
    def test_outcomes_and_outputs(self, ex):
        oracle = ORACLES[ex["assembly"]]
        for ident in ex["inputs"]:
            outcome, output = _outcome(oracle, ident, ex["target"])
            assert outcome == ex["expected"]["outcomes"][ident], ident
            assert output == ex["expected"]["outputs"][ident], ident

    def test_distinct_sequences(self, ex):
        oracle = ORACLES[ex["assembly"]]
        for group in ex["expected"].get("distinct_sequences", []):
            chroms = [oracle.resolve(i) for i in group]
            assert None not in chroms
            assert len(set(chroms)) == len(group)

    def test_collapses_are_exactly_the_shared_outputs(self, ex):
        oracle = ORACLES[ex["assembly"]]
        by_output = {}
        for ident in ex["inputs"]:
            outcome, output = _outcome(oracle, ident, ex["target"])
            if outcome in ("renamed", "unchanged"):
                by_output.setdefault(output, []).append(ident)
        computed = sorted((sorted(v), k) for k, v in by_output.items()
                          if len(v) > 1)
        declared = sorted((sorted(c["inputs"]), c["output"])
                          for c in ex["expected"].get("collapses", []))
        assert computed == declared

    def test_unknown_inputs_are_valid_in_the_declared_other_assembly(self, ex):
        oracle = ORACLES[ex["assembly"]]
        other = ex["expected"].get("recognized_in_other_assembly", {})
        for ident, assembly in other.items():
            assert oracle.resolve(ident) is None
            assert ORACLES[assembly].resolve(ident) is not None
        # An unknown input without a declared home must not be valid in any
        # other configured assembly (the fixture would be hiding a fact).
        for ident, outcome in ex["expected"]["outcomes"].items():
            if outcome == "unknown" and ident not in other:
                assert not [a for a, o in ORACLES.items()
                            if a != ex["assembly"] and o.resolve(ident)]

    def test_rows_change_only_the_chromosome(self, ex):
        if "rows_after" not in ex["expected"]:
            return
        oracle = ORACLES[ex["assembly"]]
        for before, after in zip(ex["rows"], ex["expected"]["rows_after"]):
            _, output = _outcome(oracle, before["chr"], ex["target"])
            assert after == {**before, "chr": output}


def test_hg19_chrM_and_chrMT_are_different_sequences_with_different_accessions():
    oracle = ORACLES["hg19"]
    assert oracle.resolve("chrM") != oracle.resolve("chrMT")
    assert oracle.render("chrM", "refseq") == "NC_001807.4"
    assert oracle.render("chrMT", "refseq") == "NC_012920.1"
    assert oracle.render("chrM", "ensembl") is None
    assert oracle.render("chrMT", "ensembl") == "MT"
    assert oracle.resolve("MT") == "chrMT"          # MT names chrMT, not chrM


def test_unknown_and_missing_target_are_different_outcomes_in_the_fixtures():
    outcomes = {o for e in EXAMPLES for o in e["expected"]["outcomes"].values()}
    assert {"unknown", "no_alias_for_target"} <= outcomes
