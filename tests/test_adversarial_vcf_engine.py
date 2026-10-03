"""Adversarial review (Task 10): VCF ``##contig`` reconciliation and
engine parity on normalized inputs.

The contig expectations are checked with an independent attribute parser
(``csv`` with a quote character), not with ``parse_contig_attributes``.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.chrom_registry import ChromosomeRegistry, SequenceRecord
from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
from streamlit_app.core.vcf_contigs import (
    ChromosomeContigCollisionError,
    reconcile_contig_lines,
)
from streamlit_app.streamlit_app import convert_df_to_vcf
from tests.parity.comparator import (
    assert_canonical_equal,
    interval_table,
    run_and_canonicalize,
)

# ---- independent contig parsing ---------------------------------------------------

def attrs(line: str) -> dict[str, list[str]]:
    """Attributes of a ``##contig=<...>`` line (commas inside double quotes
    do not split; written here, independent of the production parser)."""
    assert line.startswith("##contig=<")
    body = line.rstrip()[len("##contig=<"):]
    body = body.removesuffix(">")
    parts, current, quoted = [], "", False
    for ch in body:
        if ch == '"':
            quoted = not quoted
        if ch == "," and not quoted:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    out: dict[str, list[str]] = {}
    for part in parts:
        key, _, value = part.partition("=")
        out.setdefault(key, []).append(value)
    return out


def ids(lines):
    return [attrs(line)["ID"][0].strip('"') for line in lines
            if line.startswith("##contig")]


def nonid(line):
    return {k: sorted(v) for k, v in attrs(line).items() if k != "ID"}


RENAMES = {"1": "chr1", "NC_000001.11": "chr1", "CM000663.2": "chr1",
           "2": "chr2"}


# ---- compatible merges ---------------------------------------------------------------

def test_two_source_compatible_collapse_keeps_one_declaration():
    out = reconcile_contig_lines(
        ["##contig=<ID=1,length=10>", "##contig=<ID=chr1,length=10>"], RENAMES)
    assert out == ["##contig=<ID=chr1,length=10>"]


def test_three_or_more_sources_collapse_to_one_identical_declaration():
    lines = ["##contig=<ID=1,length=10,md5=ff>",
             "##contig=<ID=NC_000001.11,md5=ff,length=10>",   # order differs
             "##contig=<ID=CM000663.2,length=10,md5=ff>",
             "##contig=<ID=chr1,length=10,md5=ff>"]
    out = reconcile_contig_lines(lines, RENAMES)
    assert ids(out) == ["chr1"] and len(out) == 1
    assert all(nonid(out[0]) == nonid(line) for line in lines)


@pytest.mark.parametrize("conflict", [
    ["##contig=<ID=1,length=10>", "##contig=<ID=chr1,length=11>"],
    ["##contig=<ID=1,length=10,md5=a>", "##contig=<ID=chr1,length=10,md5=b>"],
    ["##contig=<ID=1,length=10,species=\"x\">", "##contig=<ID=chr1,length=10>"],
    ["##contig=<ID=1,length=10>", "##contig=<ID=chr1,length=10,extra=y>"],
    ["##contig=<ID=1,length=10,species=\"x,y\">",
     "##contig=<ID=chr1,length=10,species=\"x\">"],
    ["##contig=<ID=1,length=10,a=1>", "##contig=<ID=NC_000001.11,length=10,a=1>",
     "##contig=<ID=CM000663.2,length=10,a=2>"],          # third disagrees
])
def test_any_conflict_fails_explicitly_and_names_the_sources(conflict):
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        reconcile_contig_lines(conflict, RENAMES)
    assert caught.value.target == "chr1"
    assert "chr1" in str(caught.value)
    assert set(caught.value.sources) <= {"1", "NC_000001.11", "CM000663.2",
                                         "chr1"}
    assert caught.value.conflicts           # which attribute, which values


def test_quoted_attributes_with_commas_are_compared_as_one_value():
    a = '##contig=<ID=1,length=10,Description="Homo sapiens, chromosome 1">'
    b = '##contig=<ID=chr1,Description="Homo sapiens, chromosome 1",length=10>'
    out = reconcile_contig_lines([a, b], RENAMES)
    assert len(out) == 1
    assert attrs(out[0])["Description"] == ['"Homo sapiens, chromosome 1"']
    c = '##contig=<ID=chr1,Description="Homo sapiens; chromosome 1",length=10>'
    with pytest.raises(ChromosomeContigCollisionError):
        reconcile_contig_lines([a, c], RENAMES)


def test_duplicate_declarations_identical_merge_conflicting_raise():
    same = ["##contig=<ID=1,length=10>", "##contig=<ID=1,length=10>"]
    assert reconcile_contig_lines(same, RENAMES) == ["##contig=<ID=chr1,length=10>"]
    with pytest.raises(ChromosomeContigCollisionError):
        reconcile_contig_lines(
            ["##contig=<ID=1,length=10>", "##contig=<ID=1,length=11>"], RENAMES)


def test_contigs_that_do_not_collide_are_renamed_and_everything_else_untouched():
    lines = ["##fileformat=VCFv4.2", "##contig=<ID=1,length=10>",
             '##INFO=<ID=1,Number=1,Type=String,Description="ID=1,ID=2">',
             "##contig=<ID=2,length=20>", "##contig=<ID=7,length=70>",
             "#CHROM\tPOS"]
    out = reconcile_contig_lines(lines, RENAMES)
    assert out == ["##fileformat=VCFv4.2", "##contig=<ID=chr1,length=10>",
                   lines[2], "##contig=<ID=chr2,length=20>",
                   "##contig=<ID=7,length=70>", "#CHROM\tPOS"]


def test_no_renames_and_no_contigs_are_identity():
    lines = ["##fileformat=VCFv4.2", "##contig=<ID=1,length=1>"]
    assert reconcile_contig_lines(lines, {}) == lines
    assert reconcile_contig_lines(lines, None) == lines
    assert reconcile_contig_lines(["##fileformat=VCFv4.2"], RENAMES) == [
        "##fileformat=VCFv4.2"]
    assert reconcile_contig_lines([], RENAMES) == []


# ---- the ID attribute is located by quote-aware parsing ---------------------------------

@pytest.mark.parametrize("line", [
    '##contig=<length=5,Description="x,ID=zzz",ID=1>',          # ID not first
    '##contig=<Description="ID=zzz,ID=2",length=5,ID=1>',
    '##contig=<Description="a,ID=zzz",ID=1,md5=ff>',
])
def test_a_quoted_value_that_looks_like_an_id_is_not_the_contig_id(line):
    out = reconcile_contig_lines([line], {"1": "chr1", "zzz": "WRONG",
                                          "2": "WRONG"})
    (new,) = out
    assert ids([new]) == ["chr1"]
    assert "WRONG" not in new                       # description untouched
    original = attrs(line)
    assert {k: v for k, v in attrs(new).items() if k != "ID"} == {
        k: v for k, v in original.items() if k != "ID"}


@pytest.mark.parametrize("line", [
    '##contig=<ID="1",length=5>', "##contig=<length=5,ID=1>",
    "##contig=<ID=1>", '##contig=<ID=1,length=5,Description="a>b">',
])
def test_id_forms_are_renamed_in_place(line):
    (new,) = reconcile_contig_lines([line], {"1": "chr1"})
    assert ids([new]) == ["chr1"]
    assert {k: v for k, v in attrs(new).items() if k != "ID"} == {
        k: v for k, v in attrs(line).items() if k != "ID"}


# ---- export integration ---------------------------------------------------------------------

def _export(chroms, header, renames):
    df = pd.DataFrame({
        "coord_chr": chroms, "coord_start": range(len(chroms)),
        "coord_end": [i + 1 for i in range(len(chroms))],
        "coord_name": [f"v{i}" for i in range(len(chroms))],
        "coord_ref": "A", "coord_alt": "T", "coord_qual": "50",
        "coord_filter": "PASS", "coord_info": ".", "has_overlap": True})
    return convert_df_to_vcf(df, original_header_lines=header,
                             contig_renames=renames)


def _contig_lines(vcf):
    return [line for line in vcf.splitlines() if line.startswith("##contig=")]


def test_header_contigs_absent_from_the_records_keep_their_original_ids():
    """Characterization of the current contract: only identifiers present in
    the query rows are renamed, so a declared-but-unused contig keeps its
    source name (it is neither renamed nor invented)."""
    header = ["##contig=<ID=1,length=10>", "##contig=<ID=2,length=20>"]
    vcf = _export(["chr1"], header, {"1": "chr1"})
    assert ids(_contig_lines(vcf)) == ["chr1", "2"]


def test_record_contigs_absent_from_the_header_are_not_invented():
    vcf = _export(["chr1", "chr9"], ["##contig=<ID=1,length=10>"], {"1": "chr1"})
    assert ids(_contig_lines(vcf)) == ["chr1"]
    assert [ln.split("\t")[0] for ln in vcf.splitlines()
            if ln and not ln.startswith("#")] == ["chr1", "chr9"]


def test_header_only_vcf_and_no_contig_header():
    empty = _export([], ["##contig=<ID=1,length=10>"], {"1": "chr1"})
    assert ids(_contig_lines(empty)) == ["chr1"]
    assert _contig_lines(_export(["chr1"], ["##fileformat=VCFv4.2"],
                                 {"1": "chr1"})) == []


def test_export_with_a_conflicting_collapse_raises_instead_of_picking_one():
    header = ["##contig=<ID=1,length=10>", "##contig=<ID=chr1,length=11>"]
    with pytest.raises(ChromosomeContigCollisionError):
        _export(["chr1"], header, {"1": "chr1"})


# ---- engine parity on normalized inputs -------------------------------------------------------

ENGINES = [BedtoolsEngine, PolarsBioEngine]

REGISTRY = ChromosomeRegistry("ENG", {
    "s1": SequenceRecord("s1", {"ucsc": "chr1", "ensembl": "1", "genbank": "G1"}),
    "s2": SequenceRecord("s2", {"ucsc": "chr2", "ensembl": "2", "genbank": "G2"}),
    "s3": SequenceRecord("s3", {"ucsc": "chr3", "genbank": "G3"}),    # no ensembl
})
SOUP = ["chr1", "1", "G1", "chr2", "2", "G2", "chr3", "G3", "mystery", "other"]


def random_pair(seed: int):
    rng = random.Random(seed)

    def table(n, tag):
        rows = []
        for i in range(n):
            start = rng.randint(0, 200)
            rows.append((rng.choice(SOUP), start, start + rng.randint(1, 60),
                         f"{tag}{i}", rng.choice(["+", "-", None])))
        rows += rows[:3]                                     # duplicate rows
        return interval_table(
            [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
            name=[r[3] for r in rows], strand=[r[4] for r in rows])
    return table(18, "q"), table(14, "a")


def _normalized(seed, target="ucsc"):
    q, a = random_pair(seed)
    return q, a, normalize_input_chromosomes(
        q, a, registry=REGISTRY, target=target)


OPERATIONS = [
    ("overlap", {}), ("overlap", {"min_overlap": 0.5}),
    ("overlap", {"use_strand": True}), ("contains", {}), ("within", {}),
    ("closest", {}), ("closest", {"use_strand": True}),
]


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("how", ["inner", "left"])
@pytest.mark.parametrize("mode,options", OPERATIONS,
                         ids=[f"{m}-{'-'.join(o) or 'plain'}" for m, o in OPERATIONS])
def test_both_engines_agree_on_normalized_inputs(seed, how, mode, options):
    _, _, out = _normalized(seed)
    extra = ("distance",) if mode == "closest" else ()
    results = [run_and_canonicalize(cls, out.coord_df, out.annot_df, how=how,
                                    mode=mode, extra_columns=extra, **options)
               for cls in ENGINES]
    assert_canonical_equal(*results, label=f"{mode}/{how}/{seed}")


@pytest.mark.parametrize("seed", range(4))
def test_engines_agree_on_categorical_chromosomes_and_reordered_inputs(seed):
    _, _, out = _normalized(seed, target="ensembl")
    coord, annot = out.coord_df.copy(), out.annot_df.copy()
    annot = annot.sample(frac=1, random_state=seed).reset_index(drop=True)
    coord = coord.iloc[::-1].reset_index(drop=True)
    for frame_ in (coord, annot):
        frame_["chr"] = frame_["chr"].astype("category")
    results = [run_and_canonicalize(cls, coord, annot, how="left")
               for cls in ENGINES]
    assert_canonical_equal(*results, label=f"categorical/{seed}")


@pytest.mark.parametrize("seed", range(6))
def test_normalization_changes_the_join_and_both_engines_see_the_same_tables(seed):
    q, a, out = _normalized(seed)
    raw = [run_and_canonicalize(cls, q, a, how="inner") for cls in ENGINES]
    norm = [run_and_canonicalize(cls, out.coord_df, out.annot_df, how="inner")
            for cls in ENGINES]
    assert_canonical_equal(*raw, label="raw")
    assert_canonical_equal(*norm, label="normalized")
    # sensitivity: alias spellings meet only after normalization
    assert len(norm[0]) > len(raw[0])
    # the normalized chromosome column is what every engine received
    assert set(out.coord_df["chr"]) <= {"chr1", "chr2", "chr3", "mystery", "other"}


def test_unknown_identifiers_never_match_a_real_chromosome():
    q = interval_table(["mystery", "G1"], [0, 0], [100, 100], name=["a", "b"])
    a = interval_table(["chr1", "mystery"], [0, 0], [100, 100], name=["x", "y"])
    out = normalize_input_chromosomes(q, a, registry=REGISTRY, target="ucsc")
    for cls in ENGINES:
        result = run_and_canonicalize(cls, out.coord_df, out.annot_df, how="inner")
        pairs = set(zip(result["coord_name"], result["annot_name"]))
        assert pairs == {("a", "y"), ("b", "x")}   # unknown meets only itself


# ---- malformed declarations never crash the reconciliation --------------------------------

@pytest.mark.parametrize("lines", [
    ["##contig=<ID=1,length=5", "##contig=<ID=chr1,length=5>"],
    ["##contig=<ID=1,length=5>", "##contig=<ID=chr1,length=5"],
    ["##contig=<ID=1", "##contig=<ID=chr1"],
])
def test_a_declaration_without_a_closing_bracket_does_not_raise_a_valueerror(lines):
    out = reconcile_contig_lines(lines, {"1": "chr1"})
    assert ids(out) == ["chr1"] and len(out) == 1


def test_a_malformed_declaration_still_conflicts_when_metadata_differs():
    with pytest.raises(ChromosomeContigCollisionError):
        reconcile_contig_lines(["##contig=<ID=1,length=5",
                                "##contig=<ID=chr1,length=6>"], {"1": "chr1"})


@pytest.mark.parametrize("line", ["##contig=<>", "##contig=<length=5>",
                                  "##contig=ID=1", "##contig=<ID=>"])
def test_declarations_without_a_usable_id_are_left_alone(line):
    assert reconcile_contig_lines([line, "##contig=<ID=1,length=9>"],
                                  {"1": "chr1"})[0] == line
