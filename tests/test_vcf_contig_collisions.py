"""Collision-safe ##contig reconciliation when chromosome renames collapse."""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
from streamlit_app.core.vcf_contigs import (
    ChromosomeContigCollisionError,
    parse_contig_attributes,
    reconcile_contig_lines,
)
from streamlit_app.streamlit_app import _reconcile_contig_lines, convert_df_to_vcf

RENAMES = {"1": "chr1"}


def test_gui_module_uses_the_core_reconciler():
    assert _reconcile_contig_lines is reconcile_contig_lines


# --- attribute parsing ---------------------------------------------------------

def test_attribute_parser_keeps_values_verbatim_and_respects_quotes():
    line = ('##contig=<ID=1,length=10,species="Homo sapiens, human",'
            "URL=http://x.org/a=b>")
    assert parse_contig_attributes(line) == [
        ("ID", "1"), ("length", "10"),
        ("species", '"Homo sapiens, human"'), ("URL", "http://x.org/a=b")]


# --- compatible collapse ---------------------------------------------------------

def test_identical_declarations_merge_to_one_at_the_first_position():
    lines = ["##fileformat=VCFv4.2",
             "##contig=<ID=1,length=100>",
             "##INFO=<ID=DP,Number=1,Type=Integer,Description=\"d\">",
             "##contig=<ID=chr1,length=100>",
             "##reference=file:///x.fa"]
    assert reconcile_contig_lines(lines, RENAMES) == [
        "##fileformat=VCFv4.2", "##contig=<ID=chr1,length=100>",
        "##INFO=<ID=DP,Number=1,Type=Integer,Description=\"d\">",
        "##reference=file:///x.fa"]


def test_first_surviving_declaration_wins_even_if_it_is_not_renamed():
    lines = ["##contig=<ID=chr1,length=100>", "##contig=<ID=1,length=100>"]
    assert reconcile_contig_lines(lines, RENAMES) == [
        "##contig=<ID=chr1,length=100>"]


def test_attribute_order_does_not_create_a_conflict():
    lines = ["##contig=<ID=1,length=100,assembly=GRCh38>",
             "##contig=<ID=chr1,assembly=GRCh38,length=100>"]
    assert reconcile_contig_lines(lines, RENAMES) == [
        "##contig=<ID=chr1,length=100,assembly=GRCh38>"]


def test_three_way_collapse_with_identical_metadata():
    lines = ["##contig=<ID=1,length=100>",
             "##contig=<ID=NC_000001.11,length=100>",
             "##contig=<ID=chr1,length=100>"]
    out = reconcile_contig_lines(
        lines, {"1": "chr1", "NC_000001.11": "chr1"})
    assert out == ["##contig=<ID=chr1,length=100>"]


def test_one_declared_one_undeclared_source_invents_nothing():
    # Only ID=1 is declared; chr1 may be in the rows but is not declared.
    assert reconcile_contig_lines(["##contig=<ID=1,length=100>"],
                                  RENAMES) == ["##contig=<ID=chr1,length=100>"]
    assert reconcile_contig_lines(["##contig=<ID=chr1,length=100>"],
                                  RENAMES) == ["##contig=<ID=chr1,length=100>"]


def test_non_renamed_and_unrelated_declarations_are_untouched():
    lines = ["##contig=<ID=scaffold_9,length=777>",
             "##contig=<ID=chrM_x,length=5>",
             '##FILTER=<ID=1,Description="x">',
             "##contig=<ID=1,length=100>"]
    out = reconcile_contig_lines(lines, RENAMES)
    assert out == lines[:3] + ["##contig=<ID=chr1,length=100>"]


def test_without_renames_lines_are_returned_unchanged():
    lines = ["##contig=<ID=chr1,length=1>", "##contig=<ID=chr1,length=2>"]
    assert reconcile_contig_lines(lines, None) == lines
    assert reconcile_contig_lines(lines, {}) == lines


# --- conflicting collapse ------------------------------------------------------------

def test_conflicting_length_hard_fails_with_structured_detail():
    lines = ["##contig=<ID=1,length=100>", "##contig=<ID=chr1,length=101>"]
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        reconcile_contig_lines(lines, RENAMES)
    err = caught.value
    assert err.target == "chr1"
    assert err.sources == ("1", "chr1")
    assert err.conflicts == {"length": (("1", "100"), ("chr1", "101"))}


@pytest.mark.parametrize("a,b,key", [
    ("assembly=GRCh38", "assembly=GRCh37", "assembly"),
    ("md5=aaa", "md5=bbb", "md5"),
    ('species="Homo sapiens"', 'species="Mus musculus"', "species"),
    ("URL=http://x/1", "URL=http://y/1", "URL"),
])
def test_conflicting_arbitrary_metadata_hard_fails(a, b, key):
    lines = [f"##contig=<ID=1,length=100,{a}>",
             f"##contig=<ID=chr1,length=100,{b}>"]
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        reconcile_contig_lines(lines, RENAMES)
    assert set(caught.value.conflicts) == {key}


def test_attribute_present_on_only_one_side_is_a_conflict():
    lines = ["##contig=<ID=1,length=100,md5=aaa>",
             "##contig=<ID=chr1,length=100>"]
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        reconcile_contig_lines(lines, RENAMES)
    assert caught.value.conflicts == {"md5": (("1", "aaa"), ("chr1", None))}


def test_value_spelling_differences_are_conflicts_not_guessed_equal():
    lines = ["##contig=<ID=1,length=100>", "##contig=<ID=chr1,length=0100>"]
    with pytest.raises(ChromosomeContigCollisionError):
        reconcile_contig_lines(lines, RENAMES)


# --- end to end: normalization -> renames -> VCF export --------------------------------

def _export_frame(chroms):
    n = len(chroms)
    return pd.DataFrame({
        "coord_chr": chroms, "coord_start": [99] * n,
        "coord_end": [100] * n, "coord_id": [f"v{i}" for i in range(n)],
        "coord_ref": ["A"] * n, "coord_alt": ["T"] * n,
        "coord_qual": [50] * n, "coord_filter": ["PASS"] * n,
        "coord_info": ["."] * n,
    })


def _contigs(vcf):
    return [line for line in vcf.splitlines() if line.startswith("##contig")]


def _normalize(query_chroms):
    q = pd.DataFrame({"chr": query_chroms, "start": [99] * len(query_chroms),
                      "end": [100] * len(query_chroms)})
    a = pd.DataFrame({"chr": ["chr1"], "start": [0], "end": [10]})
    return normalize_input_chromosomes(q, a, assembly="GRCh38", target="ucsc")


def test_export_after_normalization_merges_compatible_collapse():
    out = _normalize(["1", "chr1", "X", "scaffold_9"])
    header = ["##fileformat=VCFv4.2", "##contig=<ID=1,length=248956422>",
              "##contig=<ID=chr1,length=248956422>",
              "##contig=<ID=X,length=156040895>",
              "##contig=<ID=scaffold_9,length=777>"]
    vcf = convert_df_to_vcf(_export_frame(out.coord_df["chr"].tolist()),
                            original_header_lines=header,
                            contig_renames=out.coord_renames)
    assert _contigs(vcf) == [
        "##contig=<ID=chr1,length=248956422>",
        "##contig=<ID=chrX,length=156040895>",
        "##contig=<ID=scaffold_9,length=777>"]  # unknown contig untouched


def test_export_after_normalization_fails_on_conflicting_collapse():
    out = _normalize(["1", "chr1"])
    header = ["##contig=<ID=1,length=100>", "##contig=<ID=chr1,length=101>"]
    with pytest.raises(ChromosomeContigCollisionError):
        convert_df_to_vcf(_export_frame(out.coord_df["chr"].tolist()),
                          original_header_lines=header,
                          contig_renames=out.coord_renames)


def test_resolved_unchanged_and_unresolved_contigs_are_not_renamed():
    out = _normalize(["chr1", "custom"])
    assert dict(out.coord_renames) == {}
    header = ["##contig=<ID=chr1,length=1>", "##contig=<ID=custom,length=2>"]
    vcf = convert_df_to_vcf(_export_frame(out.coord_df["chr"].tolist()),
                            original_header_lines=header,
                            contig_renames=out.coord_renames)
    assert _contigs(vcf) == header


# --- legacy application path: conflict is reported, never silently merged ----------

def _run_app(query: bytes, annot: bytes, engine: str | None = None):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    entry = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"
    at = AppTest.from_file(str(entry), default_timeout=120)
    at.run()

    def widget(kind, key):
        return next(e for e in at.get(kind) if getattr(e, "key", None) == key)

    if engine is not None:
        widget("radio", "engine").set_value(engine)
    widget("selectbox", "chr_assembly").set_value("Human \u2014 Dec. 2013 (GRCh38/hg38)")
    widget("selectbox", "chr_naming").set_value("UCSC names")
    widget("file_uploader", "coord_file").set_value(
        ("q.vcf", query, "application/octet-stream"))
    widget("file_uploader", "annot_file").set_value(
        ("a.gff3", annot, "application/octet-stream"))
    at.run()
    widget("button", "run_button").set_value(True)
    at.run()
    return at


_VCF_HEAD = ("##fileformat=VCFv4.2\n{contigs}"
             '##FORMAT=<ID=GT,Number=1,Type=String,Description="g">\n'
             "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n")
_ROWS = "1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
_GFF = (b"##gff-version 3\n"
        b"chr1\tsrc\tgene\t50\t250\t.\t+\t.\tID=g1;Name=G1\n")


def test_app_shows_an_error_instead_of_dropping_conflicting_contigs():
    contigs = "##contig=<ID=1,length=100>\n##contig=<ID=chr1,length=101>\n"
    at = _run_app((_VCF_HEAD.format(contigs=contigs) + _ROWS).encode(), _GFF)
    assert not at.exception
    messages = [e.value for e in at.error]
    assert any("contig metadata disagree (length)" in m
               and "1, chr1" in m and "(chr1)" in m
               and "cannot safely choose" in m for m in messages)
    assert not [b for b in at.get("download_button")
                if getattr(b, "key", None) == "download_vcf"]


def test_app_still_exports_when_collapsing_contigs_are_identical():
    contigs = "##contig=<ID=1,length=100>\n##contig=<ID=chr1,length=100>\n"
    at = _run_app((_VCF_HEAD.format(contigs=contigs) + _ROWS).encode(), _GFF)
    assert not at.exception and not at.error


def test_both_engines_export_identical_vcf_after_a_compatible_collapse():
    """Integration boundary: query contigs ``1`` and ``chr1`` collapse to
    ``chr1`` with identical metadata; Bedtools and Polars-Bio must export the
    same VCF (one merged contig, every record on chr1)."""
    contigs = "##contig=<ID=1,length=100>\n##contig=<ID=chr1,length=100>\n"
    rows = _ROWS + "chr1\t120\tv2\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
    query = (_VCF_HEAD.format(contigs=contigs) + rows).encode()
    exports = []
    for engine in ("Bedtools", "Polars-Bio"):
        at = _run_app(query, _GFF, engine=engine)
        assert not at.exception and not at.error
        state = at.session_state
        vcf = convert_df_to_vcf(
            state["result_df"],
            original_header_lines=state["result_vcf_header_lines"],
            contig_renames=state["result_vcf_contig_renames"])
        exports.append("\n".join(
            line for line in vcf.splitlines() if not line.startswith("##date=")))
    assert exports[0] == exports[1]
    assert _contigs(exports[0]) == ["##contig=<ID=chr1,length=100>"]
    records = [l.split("\t")[:3] for l in exports[0].splitlines()
               if not l.startswith("#")]
    assert records == [["chr1", "100", "v1"], ["chr1", "120", "v2"]]
