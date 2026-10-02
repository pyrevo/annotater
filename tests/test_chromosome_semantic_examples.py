"""Chromosome-naming semantic examples: real normalization and rendering.

Each declared fact is compared with the actual ``normalize_chromosomes``
result (the independent upstream check lives in
``tests/oracle/test_chromosome_semantic_examples.py``), and the rendering
contract of the new ``chromosome_naming`` kind is pinned here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from streamlit_app.core import normalize_chromosomes

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_semantic_examples", ROOT / "scripts" / "generate_semantic_examples.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

ALL = gen.load_examples()
EXAMPLES = {n: e for n, e in ALL.items() if e["kind"] == gen.CHROMOSOME_KIND}
BLOCKS = {n: gen.render_block(e) for n, e in EXAMPLES.items()}


def body(name):
    return BLOCKS[name].split("\n")[1:-1]


def _frame(example):
    if "rows" in example:
        return pd.DataFrame(example["rows"])
    return pd.DataFrame({"chr": example["inputs"]})


# ---- declared facts versus the real normalization ---------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
class TestDeclaredFactsMatchNormalization:
    def _run(self, name):
        ex = EXAMPLES[name]
        return ex, normalize_chromosomes(
            _frame(ex), assembly=ex["assembly"], target=ex["target"])

    def test_outputs(self, name):
        ex, result = self._run(name)
        rename = dict(zip(_frame(ex)["chr"], result.dataframe["chr"]))
        assert rename == {i: ex["expected"]["outputs"][i] for i in rename}

    def test_outcomes_match_the_report(self, name):
        ex, result = self._run(name)
        report = result.report
        for ident, outcome in ex["expected"]["outcomes"].items():
            actual = ("unknown" if ident in report.unknown
                      else "no_alias_for_target"
                      if ident in report.no_alias_for_target
                      else "renamed" if ident in report.renames
                      else "unchanged")
            assert actual == outcome, ident

    def test_collapses(self, name):
        ex, result = self._run(name)
        declared = {c["output"]: tuple(c["inputs"])
                    for c in ex["expected"].get("collapses", [])}
        assert {k: tuple(sorted(v)) for k, v in result.report.collapses.items()
                } == {k: tuple(sorted(v)) for k, v in declared.items()}

    def test_only_the_chromosome_column_changes(self, name):
        ex, result = self._run(name)
        before, after = _frame(ex), result.dataframe
        assert list(after.columns) == list(before.columns)
        pd.testing.assert_frame_equal(
            before.drop(columns="chr"), after.drop(columns="chr"))
        if "rows_after" in ex["expected"]:
            assert after.to_dict("records") == ex["expected"]["rows_after"]


def test_coordinate_example_leaves_every_other_column_exactly_equal():
    ex = EXAMPLES["chromosome_coordinates_preserved"]
    result = normalize_chromosomes(_frame(ex), assembly="GRCh38", target="ucsc")
    for column in ("start", "end", "strand", "name"):
        assert result.dataframe[column].tolist() == [r[column] for r in ex["rows"]]
    assert result.report.changed_rows == 2


# ---- schema: scientifically inconsistent fixtures are rejected ---------------

def _data():
    return json.loads(gen.FIXTURE.read_text())


def _example(data, name):
    return next(e for e in data["examples"] if e["name"] == name)


@pytest.mark.parametrize("name,mutate", [
    ("chromosome_hg19_mitochondria", lambda e: e.update(assembly="hg99")),
    ("chromosome_hg19_mitochondria", lambda e: e.update(target="refseq2")),
    ("chromosome_hg19_mitochondria", lambda e: e.update(inputs=[])),
    ("chromosome_hg19_mitochondria", lambda e: e.update(inputs=["chrM", "chrM"])),
    ("chromosome_hg19_mitochondria", lambda e: e.update(extra=1)),
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"].update(bogus=1)),
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"]["outcomes"].pop("chrM")),
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"]["outcomes"].update(chrM="mapped")),
    # an unresolved name may not be shown as renamed, nor a rename as unchanged
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"]["outputs"].update(chrM="MT")),
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"]["outcomes"].update(chrMT="unchanged")),
    ("chromosome_hg19_mitochondria",
     lambda e: e["expected"].update(distinct_sequences=[["chrM", "chr1"]])),
    ("chromosome_many_to_one",
     lambda e: e["expected"]["collapses"][0].update(output="chr2")),
    ("chromosome_wrong_assembly",
     lambda e: e["expected"]["recognized_in_other_assembly"].update(
         chr2L="GRCh38")),
    ("chromosome_coordinates_preserved",
     lambda e: e["expected"]["rows_after"][0].update(start=101)),
    ("chromosome_coordinates_preserved", lambda e: e.pop("rows")),
], ids=range(15))
def test_schema_rejects_inconsistent_chromosome_fixture(name, mutate):
    data = _data()
    mutate(_example(data, name))
    with pytest.raises(gen.FixtureError):
        gen.validate_examples(data)


def test_missing_expected_outputs_are_rejected():
    data = _data()
    del _example(data, "chromosome_dm6_non_human")["expected"]["outputs"]
    with pytest.raises(gen.FixtureError, match="outputs"):
        gen.validate_examples(data)


# ---- rendering contract -------------------------------------------------------

def test_hg19_block_is_exactly_this():
    assert BLOCKS["chromosome_hg19_mitochondria"] == """\
```text
genome assembly: hg19
chromosome naming: Ensembl names
only chromosome names can change; coordinates and assembly are unchanged

input  output  result
chrM   chrM    recognized; no verified Ensembl name; kept as provided
chrMT  MT      renamed

different sequences: chrM, chrMT
```"""


def test_hg19_block_never_suggests_chrM_maps_to_MT():
    lines = body("chromosome_hg19_mitochondria")
    assert not any("→" in l or "->" in l for l in lines)
    row = next(l for l in lines if l.startswith("chrM "))
    assert row.split()[:2] == ["chrM", "chrM"]       # output of chrM is chrM
    assert "renamed" not in row
    assert next(l for l in lines if l.startswith("chrMT")).split()[:3] == [
        "chrMT", "MT", "renamed"]
    assert "different sequences: chrM, chrMT" in lines


def test_unknown_and_no_target_alias_are_worded_differently():
    unknown = BLOCKS["chromosome_wrong_assembly"]
    no_alias = BLOCKS["chromosome_dm6_non_human"]
    assert "not recognized in GRCh38; kept as provided" in unknown
    assert "recognized; no verified Ensembl name; kept as provided" in no_alias
    assert "not recognized" not in no_alias
    assert "no verified" not in unknown
    for block in BLOCKS.values():
        assert "unmapped" not in block.lower()


def test_wrong_assembly_block_names_the_assembly_that_knows_the_identifier():
    assert ("recognized in another assembly: NC_000001.10 (hg19), chr2L (dm6)"
            in body("chromosome_wrong_assembly"))


def test_many_to_one_is_informational_not_an_error():
    lines = body("chromosome_many_to_one")
    assert "merged output name (informational): 1, chr1 → chr1" in lines
    assert not any(w in " ".join(lines).lower()
                   for w in ("error", "warning", "conflict", "failed"))


def test_coordinate_block_shows_before_and_after_with_identical_coordinates():
    lines = body("chromosome_coordinates_preserved")
    before = lines[lines.index("rows before") + 1:lines.index("rows after") - 1]
    after = lines[lines.index("rows after") + 1:]
    assert [l.split()[1:] for l in before] == [l.split()[1:] for l in after]
    assert before[0].split()[0] == "chr" and after[0].split()[0] == "chr"
    assert before[1].split()[0] == "NC_000001.11" and after[1].split()[0] == "chr1"


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_block_header_declares_assembly_naming_and_unchanged_coordinates(name):
    lines = body(name)
    ex = EXAMPLES[name]
    assert lines[0] == f"genome assembly: {ex['assembly']}"
    assert lines[1] == f"chromosome naming: {gen.TARGET_LABELS[ex['target']]}"
    assert lines[2].startswith("only chromosome names can change;")
    assert max(len(l) for l in lines) <= gen.MAX_WIDTH


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_input_has_one_row_with_its_declared_output(name):
    ex = EXAMPLES[name]
    lines = body(name)
    start = lines.index("") + 1
    table = [l.split("  ")[0].strip() for l in lines[start:]
             if l.strip() and not l.startswith(("different", "recognized in",
                                                "merged", "rows", "chr "))]
    for ident in ex["inputs"]:
        assert ident in table


def test_chromosome_labels_match_the_apps_naming_menu():
    from streamlit_app.streamlit_app import _NAMING_OPTIONS
    menu = {target: label for label, target in _NAMING_OPTIONS.items() if target}
    assert gen.TARGET_LABELS == menu


def test_known_assemblies_are_the_registry_assemblies():
    from streamlit_app.core.chrom_registry import load_catalog
    assert set(gen.known_assemblies()) == {i.assembly_id
                                           for i in load_catalog()}


def test_render_is_deterministic_and_input_order_is_preserved():
    ex = copy.deepcopy(EXAMPLES["chromosome_hg19_mitochondria"])
    assert gen.render_block(ex) == BLOCKS["chromosome_hg19_mitochondria"]
    # the rendered row order follows the declared inputs, not JSON key order
    ex["expected"]["outcomes"] = dict(reversed(list(ex["expected"]["outcomes"].items())))
    ex["expected"]["outputs"] = dict(reversed(list(ex["expected"]["outputs"].items())))
    assert gen.render_block(ex) == BLOCKS["chromosome_hg19_mitochondria"]


def test_too_wide_chromosome_fixture_fails_instead_of_wrapping():
    ex = copy.deepcopy(EXAMPLES["chromosome_dm6_non_human"])
    long_name = "x" * 90
    ex["inputs"] = ["chr2L", long_name]
    ex["expected"]["outcomes"][long_name] = "unknown"
    ex["expected"]["outputs"][long_name] = long_name
    with pytest.raises(gen.RenderError, match="MAX_WIDTH"):
        gen.render_block(ex)
