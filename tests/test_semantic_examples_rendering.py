"""Rendering contract for the generated scientific example blocks.

Scientific truth is verified elsewhere (tests/oracle/); this module pins how
declared facts are *presented*: labels, legend, required fields per kind,
field order, grammar, width, and golden output for the key examples.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_semantic_examples", ROOT / "scripts" / "generate_semantic_examples.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

ALL_EXAMPLES = gen.load_examples()
# Interval examples share one diagram layout; chromosome-naming examples have
# their own rendering contract (tests/test_chromosome_semantic_examples.py).
EXAMPLES = {n: e for n, e in ALL_EXAMPLES.items() if e["kind"] in gen.KINDS}
BLOCKS = {n: gen.render_block(e) for n, e in ALL_EXAMPLES.items()}


def body(name):
    """Block text without the code fence, as a list of lines."""
    return BLOCKS[name].split("\n")[1:-1]


def _example(name):
    return copy.deepcopy(EXAMPLES[name])


# ---- labels ----------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_diagram_has_standard_labels(name):
    # diagram rows are the lines ending in an interval such as "[10, 20)"
    rows = [l for l in body(name) if l.endswith(")") and "boundary" not in l]
    labels = [l.split("  ")[0].strip() for l in rows]
    n = len(EXAMPLES[name]["annotations"])
    want = (["query", "annotation"] if n == 1 else
            ["query"] + [f"annotation A{i}" for i in range(1, n + 1)])
    assert labels == want
    assert not any(l.startswith(("A ", "A1 ")) for l in body(name))


def test_interval_labels_helper():
    assert gen.interval_labels(EXAMPLES["touching_intervals"]) == [
        "query", "annotation"]
    assert gen.interval_labels(EXAMPLES["closest_tie"]) == [
        "query", "annotation A1", "annotation A2", "annotation A3"]


# ---- legend / base-vs-boundary wording ------------------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_exactly_one_legend_and_base_boundary_wording(name):
    lines = body(name)
    assert lines.count(gen.LEGEND) == 1
    assert "# = included base" in gen.LEGEND and ". = outside interval" in gen.LEGEND
    spans = [l for l in lines if "boundary coordinates" in l]
    assert len(spans) == 1 + len(EXAMPLES[name]["annotations"])
    assert all("share a boundary point" not in l for l in lines)


# ---- required fields / order -----------------------------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_example_satisfies_its_kind(name):
    ex = EXAMPLES[name]
    order, required, _ = gen.KINDS[ex["kind"]]
    assert all(gen._token_present(t, ex) for t in required)


def _drop(path):
    def mutate(ex):
        target = ex
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return mutate


@pytest.mark.parametrize("name,mutate", [
    ("min_overlap_on_threshold", _drop(["expected", "overlap_fraction"])),
    ("min_overlap_on_threshold", _drop(["min_overlap"])),
    ("touching_intervals", _drop(["expected", "closest_distance"])),
    ("one_base_gap", _drop(["expected", "closest_distance"])),
    ("closest_tie", _drop(["expected", "candidate_distances"])),
    ("closest_tie", _drop(["expected", "closest_ties"])),
    ("strand_missing", _drop(["expected", "stranded_match"])),
    ("strand_missing", _drop(["use_strand"])),
    ("contains_example", _drop(["expected", "within"])),
    ("true_overlap", _drop(["expected", "query_length"])),
], ids=lambda v: v if isinstance(v, str) else "")
def test_missing_required_fact_fails_validation(name, mutate):
    data = json.loads(gen.FIXTURE.read_text())
    ex = next(e for e in data["examples"] if e["name"] == name)
    mutate(ex)
    with pytest.raises(gen.FixtureError):
        gen.validate_examples(data)


def test_extra_valid_fact_not_rendered_by_kind_is_allowed_and_ignored():
    from tests.oracle import reference as ref

    ex = _example("touching_intervals")
    q, a = ex["query"], ex["annotations"][0]
    # Scientifically valid facts the touching kind does not display.
    extra = {
        "query_length": q["end"] - q["start"],
        "overlap_fraction": ref.overlap_length(
            q["start"], q["end"], a["start"], a["end"]) / (q["end"] - q["start"]),
    }
    assert extra == {"query_length": 10, "overlap_fraction": 0.0}
    ex["expected"].update(extra)
    data = json.loads(gen.FIXTURE.read_text())
    next(e for e in data["examples"]
         if e["name"] == "touching_intervals")["expected"].update(extra)
    gen.validate_examples(data)  # accepted
    assert gen.render_block(ex) == BLOCKS["touching_intervals"]  # ignored


def test_unknown_fact_name_is_still_rejected():
    data = json.loads(gen.FIXTURE.read_text())
    data["examples"][0]["expected"]["not_a_fact"] = 1
    with pytest.raises(gen.FixtureError, match="unknown expected fact"):
        gen.validate_examples(data)


def test_every_interval_kind_rule_still_applies_to_the_interval_subset():
    assert EXAMPLES and set(ALL_EXAMPLES) - set(EXAMPLES)
    assert {e["kind"] for e in ALL_EXAMPLES.values()
            if e["name"] not in EXAMPLES} == {gen.CHROMOSOME_KIND}


def test_unknown_or_missing_kind_is_rejected():
    for value in ("nope", None):
        data = json.loads(gen.FIXTURE.read_text())
        if value is None:
            del data["examples"][0]["kind"]
        else:
            data["examples"][0]["kind"] = value
        with pytest.raises(gen.FixtureError, match="kind"):
            gen.validate_examples(data)


def test_annotation_count_rule_per_kind():
    data = json.loads(gen.FIXTURE.read_text())
    ex = next(e for e in data["examples"] if e["name"] == "closest_tie")
    ex["annotations"] = ex["annotations"][:1]
    with pytest.raises(gen.FixtureError):
        gen.validate_examples(data)


def test_candidate_distances_must_cover_every_annotation():
    data = json.loads(gen.FIXTURE.read_text())
    ex = next(e for e in data["examples"] if e["name"] == "closest_tie")
    del ex["expected"]["candidate_distances"]["A3"]
    with pytest.raises(gen.FixtureError, match="candidate_distances"):
        gen.validate_examples(data)


def _summary_labels(name):
    lines = body(name)
    last_blank = max(i for i, l in enumerate(lines) if l == "")
    return [l.split(":")[0] for l in lines[last_blank + 1:] if not l.startswith("  ")]


def test_summary_order_is_pedagogical_not_json_order():
    assert _summary_labels("min_overlap_on_threshold") == [
        "overlap", "query length", "overlap length",
        "overlap fraction (query-relative)", "min_overlap threshold",
        "passes min_overlap"]
    assert _summary_labels("strand_missing") == [
        "overlap", "strand matching", "query strand", "annotation strand",
        "stranded match"]
    assert _summary_labels("closest_tie") == [
        "candidate distances", "closest distance", "retained"]
    assert _summary_labels("touching_intervals") == [
        "overlap", "overlap length", "closest distance"]


def test_json_key_order_does_not_change_output():
    ex = _example("min_overlap_on_threshold")
    ex["expected"] = dict(reversed(list(ex["expected"].items())))
    assert gen.render_block(ex) == BLOCKS["min_overlap_on_threshold"]


# ---- grammar ----------------------------------------------------------------

@pytest.mark.parametrize("n,noun,want", [
    (1, "base", "1 base"), (2, "base", "2 bases"), (0, "base", "0 bases"),
    (1, "annotation", "1 annotation"), (2, "annotation", "2 annotations"),
])
def test_plural(n, noun, want):
    assert gen.plural(n, noun) == want


@pytest.mark.parametrize("start,end,want", [
    (19, 20, "base 19"), (19, 21, "bases 19–20"), (10, 20, "bases 10–19"),
])
def test_base_span(start, end, want):
    assert gen.base_span(start, end) == want


def test_rendered_text_has_no_degenerate_grammar():
    for name, block in BLOCKS.items():
        assert "1 bases" not in block and "1 annotations" not in block
        for start in range(0, 40):
            assert f"bases {start}–{start} " not in block


def test_one_base_overlap_and_tie_grammar_in_blocks():
    assert "base 19 (1 base); boundary coordinates 19 and 20" in BLOCKS["one_base_overlap"]
    assert "retained: 2 annotations," in BLOCKS["closest_tie"]
    ex = _example("closest_tie")
    ex["expected"]["closest_ties"] = ["A1"]
    ex["expected"]["candidate_distances"] = {"A1": 2, "A2": 3, "A3": 9}
    assert "retained: 1 annotation," in gen.render_block(ex)


# ---- width ------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(ALL_EXAMPLES))
def test_no_generated_line_exceeds_max_width(name):
    assert max(len(l) for l in BLOCKS[name].split("\n")) <= gen.MAX_WIDTH


def test_too_wide_fixture_fails_instead_of_wrapping():
    ex = _example("closest_large_gap")
    ex["annotations"][0].update(start=60, end=64)
    with pytest.raises(gen.RenderError, match="MAX_WIDTH"):
        gen.render_block(ex)


# ---- golden output (explicit, human-readable diffs) ------------------------

GOLDEN = {
    "touching_intervals": """\
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query         #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
annotation    .  .  .  .  .  .  .  .  .  .  #  #  #  #  #  [20, 25)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  bases 20–24 (5 bases); boundary coordinates 20 and 25

overlap: no
overlap length: 0
closest distance: 0
```""",
    "one_base_overlap": """\
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19
query         #  #  #  #  #  #  #  #  #  #  [10, 20)
annotation    .  .  .  .  .  .  .  .  .  #  [19, 20)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  base 19 (1 base); boundary coordinates 19 and 20

overlap: yes
overlap length: 1
query length: 10
overlap fraction (query-relative): 0.1
```""",
    "min_overlap_on_threshold": """\
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query         #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
annotation    .  .  .  .  .  #  #  #  #  #  #  #  #  #  #  [15, 25)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  bases 15–24 (10 bases); boundary coordinates 15 and 25

overlap: yes
query length: 10
overlap length: 5
overlap fraction (query-relative): 0.5
min_overlap threshold: 0.5
passes min_overlap: yes
```""",
    "strand_missing": """\
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query         #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
annotation    .  .  .  .  .  #  #  #  #  #  #  #  #  #  #  [15, 25)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  bases 15–24 (10 bases); boundary coordinates 15 and 25

overlap: yes
strand matching: on
query strand: +
annotation strand: missing
stranded match: no
```""",
    "closest_tie": """\
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases            6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query            .  .  .  .  #  #  #  .  .  .  .  .  .  .  .  .  .  .  .  [10, 13)
annotation A1    #  #  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  [6, 8)
annotation A2    .  .  .  .  .  .  .  .  .  #  #  .  .  .  .  .  .  .  .  [15, 17)
annotation A3    .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  #  #  #  [22, 25)

query          bases 10–12 (3 bases); boundary coordinates 10 and 13
annotation A1  bases 6–7 (2 bases); boundary coordinates 6 and 8
annotation A2  bases 15–16 (2 bases); boundary coordinates 15 and 17
annotation A3  bases 22–24 (3 bases); boundary coordinates 22 and 25

candidate distances:
  annotation A1    2  retained
  annotation A2    2  retained
  annotation A3    9  excluded
closest distance: 2
retained: 2 annotations, in annotation order: annotation A1, annotation A2
```""",
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_block(name):
    assert BLOCKS[name] == GOLDEN[name]


def test_renderer_generates_no_explanatory_prose():
    # Facts only: no sentence-style explanations in any block.
    for block in BLOCKS.values():
        for word in ("because", "therefore", "is not an overlap"):
            assert word not in block.lower()


# ---- page-level layout invariants -------------------------------------------

def _doc_blocks():
    """[(path, name, block lines)] for every generated region in docs/."""
    out = []
    for path in gen.markdown_files():
        lines = path.read_text().split("\n")
        i = 0
        while i < len(lines):
            m = gen.BEGIN_RE.match(lines[i])
            if m:
                j = next(k for k in range(i, len(lines))
                         if gen.END_RE.match(lines[k]))
                out.append((path, m.group(1), lines[i + 1:j]))
                i = j
            i += 1
    return out


def test_docs_blocks_match_renderer_width_and_single_legend():
    blocks = _doc_blocks()
    assert blocks
    for path, name, lines in blocks:
        assert max(len(l) for l in lines) <= gen.MAX_WIDTH, (path, name)
        if name not in EXAMPLES:  # chromosome-naming block: no interval legend
            assert gen.LEGEND not in lines, (path, name)
            continue
        assert lines.count(gen.LEGEND) == 1, (path, name)
        assert lines[0] == "```text" and lines[-1] == "```", (path, name)


def test_each_marker_pair_appears_once_per_page():
    for path in gen.markdown_files():
        names = [m.group(1) for l in path.read_text().splitlines()
                 if (m := gen.BEGIN_RE.match(l))]
        assert len(names) == len(set(names)), path


def test_no_orphan_fixtures_and_no_unknown_markers():
    used = {name for _, name, _ in _doc_blocks()}
    assert used == set(ALL_EXAMPLES)


def test_docs_blocks_are_current():
    assert gen.run(check=True, out=io.StringIO()) == 0
