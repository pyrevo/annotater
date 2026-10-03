"""VCF ``##contig`` declarations follow the selected registry (Task 10.1).

When chromosome naming normalization is active, every declared contig ID is
resolved and rendered through the same registry and target as the data rows,
including contigs no row uses. Unknown identifiers and sequences without a
verified target alias stay as declared; declarations that end up with one ID
merge only when their other metadata agree.

Expected values are derived here from the registry *text* (csv) and by hand,
not from ``header_contig_renames`` / ``reconcile_contig_lines``.
"""

from __future__ import annotations

import csv

import pytest

from streamlit_app.core.chrom_registry import (
    builder,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.vcf_contigs import (
    ChromosomeContigCollisionError,
    declared_contig_ids,
    header_contig_renames,
    reconcile_contig_lines,
)
from streamlit_app.streamlit_app import _CUSTOM_OPTION, convert_df_to_vcf
from tests.test_custom_mapping_gui import ANNOT, HEADER, App, _has

GRCH38 = "Human — Dec. 2013 (GRCh38/hg38)"
HUMAN_ANNOT = (b"##gff-version 3\n"
               b"chr1\tsrc\tgene\t50\t250\t.\t+\t.\tID=g1;Name=G1\n")
COLUMNS = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"


def vcf(contigs, rows):
    body = "##fileformat=VCFv4.2\n" + "".join(c + "\n" for c in contigs)
    body += COLUMNS + "".join(f"{c}\t100\tv{i}\tA\tT\t50\tPASS\t.\n"
                              for i, c in enumerate(rows))
    return body.encode()


def contig_lines(text):
    return [line for line in text.splitlines() if line.startswith("##contig=")]


def ids_of(lines):
    out = []
    for line in lines:
        body = line[len("##contig=<"):].rstrip(">")
        out.append(next(p[3:] for p in body.split(",") if p.startswith("ID=")))
    return out


def exported(app):
    state = app.state
    return convert_df_to_vcf(
        state["result_df"],
        original_header_lines=state["result_vcf_header_lines"],
        contig_renames=state["result_vcf_contig_renames"])


def tsv_expected(assembly, target, identifiers):
    """Independent expectation from the registry text (csv), by alias."""
    text = (builder.PACKAGE_DIR / "data" / f"{assembly}.tsv").read_text()
    rows = list(csv.DictReader(text.splitlines(), delimiter="\t"))
    out = {}
    for ident in identifiers:
        hits = [r for r in rows if ident in
                (r["ucsc"], r["assembly"], r["ensembl"], r["genbank"], r["refseq"])]
        if len(hits) == 1 and hits[0][target]:
            out[ident] = hits[0][target]
        else:
            out[ident] = ident
    return out


# ---- the function: registry + target -> header renames ---------------------------------

def test_header_renames_match_an_independent_derivation_from_the_registry_text():
    declared = ["1", "2", "NC_000003.12", "chr4", "CM000666.2", "chrUn_KI270302v1",
                "GL000195.1", "mystery", "chrM", "MT", "X"]
    lines = [f"##contig=<ID={i},length=1>" for i in declared]
    registry = load_registry("GRCh38")
    for target in ("ucsc", "ensembl", "refseq", "genbank", "assembly"):
        got = header_contig_renames(lines, registry, target)
        want = tsv_expected("GRCh38", target, declared)
        assert got == {k: v for k, v in want.items() if k != v}, target


def test_unknown_and_no_target_contigs_are_absent_never_failures():
    registry = load_custom_registry(
        (HEADER + "a\tchrA\tA\t\t\nb\tchrB\t\t\t\n").encode())
    lines = ["##contig=<ID=a>", "##contig=<ID=b>", "##contig=<ID=mystery>"]
    assert header_contig_renames(lines, registry, "ensembl") == {"a": "A"}
    assert header_contig_renames(lines, registry, "ucsc") == {
        "a": "chrA", "b": "chrB"}


def test_bundled_and_custom_registries_give_the_same_header_renames():
    bundled = load_registry("hg19")
    text = (builder.PACKAGE_DIR / "data" / "hg19.tsv").read_text()
    out = [HEADER.rstrip("\n")]
    for r in csv.DictReader(text.splitlines(), delimiter="\t"):
        out.append("\t".join(r[c] for c in
                             ("assembly", "ucsc", "ensembl", "genbank", "refseq")))
    custom = load_custom_registry(("\n".join(out) + "\n").encode())
    lines = [f"##contig=<ID={i}>" for i in
             ("1", "chrM", "chrMT", "MT", "NC_001807.4", "X", "nope")]
    for target in ("ucsc", "ensembl", "refseq", "genbank", "assembly"):
        assert (header_contig_renames(lines, bundled, target)
                == header_contig_renames(lines, custom, target))


def test_the_header_scan_is_quote_aware_and_tolerates_malformed_lines():
    lines = ['##contig=<length=5,Description="x,ID=zzz",ID=ctg1>',
             '##contig=<ID=ctg2,Description="ID=ctg1">',
             "##contig=<ID=ctg3", "##contig=<>", "##contig=ID=ctg4",
             '##INFO=<ID=ctg5,Description="not a contig">', "#CHROM\tPOS"]
    assert declared_contig_ids(lines) == ["ctg1", "ctg2", "ctg3"]
    registry = load_custom_registry((HEADER + "ctg1\tchrA\t\t\t\nzzz\tchrZ\t\t\t\n"
                                     "ctg3\tchrC\t\t\t\n").encode())
    assert header_contig_renames(lines, registry, "ucsc") == {
        "ctg1": "chrA", "ctg3": "chrC"}                     # zzz never touched


# ---- reconciliation of header-only declarations ---------------------------------------------

def _custom(*rows):
    return load_custom_registry((HEADER + "".join(rows)).encode())


def _reconcile(lines, registry, target="ucsc"):
    return reconcile_contig_lines(
        lines, header_contig_renames(lines, registry, target))


def test_two_unused_contigs_collapse_compatibly_into_one_declaration():
    registry = _custom("ctgX\tchrX\t\t\t\n")
    out = _reconcile(["##contig=<ID=ctgX,length=9>", "##contig=<ID=chrX,length=9>"],
                     registry)
    assert out == ["##contig=<ID=chrX,length=9>"]


def test_two_unused_contigs_with_conflicting_metadata_fail_explicitly():
    registry = _custom("ctgX\tchrX\t\t\t\n")
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        _reconcile(["##contig=<ID=ctgX,length=9>", "##contig=<ID=chrX,length=10>"],
                   registry)
    assert caught.value.target == "chrX" and "length" in caught.value.conflicts


def test_three_or_more_unused_contigs_collapse_or_fail():
    registry = _custom("ctgX\tchrX\t\tGBX.1\tRSX.1\n")
    same = ["##contig=<ID=ctgX,length=9,md5=a>",
            "##contig=<ID=GBX.1,md5=a,length=9>",
            "##contig=<ID=RSX.1,length=9,md5=a>"]
    assert _reconcile(same, registry) == ["##contig=<ID=chrX,length=9,md5=a>"]
    with pytest.raises(ChromosomeContigCollisionError) as caught:
        _reconcile(same[:2] + ["##contig=<ID=RSX.1,length=9,md5=b>"], registry)
    assert set(caught.value.sources) == {"ctgX", "GBX.1", "RSX.1"}


def test_the_surviving_declaration_keeps_the_first_position_and_nothing_is_sorted():
    registry = _custom("A\tX\t\t\t\nfoo\tfoo-u\t\t\t\n")
    lines = ["##contig=<ID=A,length=1>", "##contig=<ID=foo,length=2>",
             "##contig=<ID=X,length=1>", "##contig=<ID=zeta,length=3>"]
    assert _reconcile(lines, registry) == [
        "##contig=<ID=X,length=1>", "##contig=<ID=foo-u,length=2>",
        "##contig=<ID=zeta,length=3>"]


def test_a_collapse_between_a_row_used_and_a_header_only_declaration():
    registry = _custom("ctgX\tchrX\t\tGBX.1\t\n")
    header = ["##contig=<ID=ctgX,length=9>", "##contig=<ID=GBX.1,length=9>"]
    rows_only = {"ctgX": "chrX"}                      # what the rows alone give
    # rows-only renames leave GBX.1 as a second, differently named declaration
    assert ids_of(reconcile_contig_lines(header, rows_only)) == ["chrX", "GBX.1"]
    both = {**header_contig_renames(header, registry, "ucsc"), **rows_only}
    assert reconcile_contig_lines(header, both) == ["##contig=<ID=chrX,length=9>"]


def test_quote_aware_id_placement_survives_header_normalization():
    registry = _custom("ctg1\tchrA\t\t\t\nzzz\tchrZ\t\t\t\n")
    line = '##contig=<length=5,Description="x,ID=zzz",ID=ctg1>'
    assert _reconcile([line], registry) == [
        '##contig=<length=5,Description="x,ID=zzz",ID=chrA>']


def test_a_malformed_declaration_does_not_crash_the_normalization():
    registry = _custom("ctg1\tchrA\t\t\t\n")
    out = _reconcile(["##contig=<ID=ctg1,length=5", "##contig=<ID=chrA,length=5>"],
                     registry)
    assert ids_of(out) == ["chrA"] and len(out) == 1


# ---- the application: bundled and custom, used and unused contigs -----------------------------

def bundled_app(contigs, rows, naming="UCSC names"):
    app = App(vcf(contigs, rows), HUMAN_ANNOT, qname="q.vcf")
    return app.source(GRCH38).naming(naming).run()


def custom_app(mapping, contigs, rows, naming="UCSC names"):
    app = App(vcf(contigs, rows), ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming(naming).mapping(mapping).run()
    return app


MAP = (HEADER + "ctg1\tchrA\tA\tGB1\tRS1\nctg2\tchrB\t\t\t\n"
       "ctgX\tchrX\t\tGBX.1\tRSX.1\n").encode()


def test_bundled_header_contigs_used_and_unused_all_follow_the_target():
    declared = ["1", "2", "3", "NC_000004.12", "chrUn_KI270302v1", "mystery"]
    app = bundled_app([f"##contig=<ID={d},length=7>" for d in declared], ["1"])
    out = exported(app)
    want = tsv_expected("GRCh38", "ucsc", declared)
    assert ids_of(contig_lines(out)) == [want[d] for d in declared]
    assert ids_of(contig_lines(out))[-1] == "mystery"        # unknown unchanged
    assert [ln.split("\t")[0] for ln in out.splitlines()
            if ln and not ln.startswith("#")] == ["chr1"]
    assert not app.errors


def test_all_header_contigs_unused_still_normalized():
    app = bundled_app(["##contig=<ID=2,length=1>", "##contig=<ID=3,length=1>"],
                      ["mystery"])
    assert ids_of(contig_lines(exported(app))) == ["chr2", "chr3"]


def test_custom_header_contigs_unused_unknown_and_no_target():
    declared = ["##contig=<ID=ctg1,length=1>", "##contig=<ID=ctg2,length=2>",
                "##contig=<ID=mystery,length=3>"]
    ucsc = custom_app(MAP, declared, ["ctg1"])
    assert ids_of(contig_lines(exported(ucsc))) == ["chrA", "chrB", "mystery"]
    ensembl = custom_app(MAP, declared, ["ctg1"], naming="Ensembl names")
    # ctg2 resolves but has no Ensembl name: kept, not invented, no failure
    assert ids_of(contig_lines(exported(ensembl))) == ["A", "ctg2", "mystery"]
    assert not ensembl.errors


def test_gui_collapse_of_header_only_sources_merges_or_fails_explicitly():
    ok = custom_app(MAP, ["##contig=<ID=ctgX,length=9>",
                          "##contig=<ID=GBX.1,length=9>",
                          "##contig=<ID=RSX.1,length=9>"], ["ctg1"])
    assert ids_of(contig_lines(exported(ok))) == ["chrX"]
    bad = custom_app(MAP, ["##contig=<ID=ctgX,length=9>",
                           "##contig=<ID=GBX.1,length=10>"], ["ctg1"])
    assert not bad.at.exception
    assert any("disagree" in e.value for e in bad.at.error)
    assert any("\u2192 chrX" in c for c in bad.codes)
    assert not _has(bad.at, "download_button", "download_vcf")


def test_gui_mixture_of_row_used_and_header_only_sources_merge():
    app = custom_app(MAP, ["##contig=<ID=ctgX,length=9>",
                           "##contig=<ID=GBX.1,length=9>"], ["ctgX"])
    assert ids_of(contig_lines(exported(app))) == ["chrX"]


def test_keep_original_leaves_the_header_byte_for_byte_alone():
    contigs = ["##contig=<ID=1,length=7>", "##contig=<ID=2,length=8>",
               '##contig=<length=5,Description="x,ID=zzz",ID=3>']
    app = App(vcf(contigs, ["1"]), HUMAN_ANNOT, qname="q.vcf").source(GRCH38).run()
    assert app.state["result_vcf_contig_renames"] == {}
    assert contig_lines(exported(app)) == contigs


def test_the_header_renames_are_part_of_session_state_and_change_with_the_inputs():
    contigs = ["##contig=<ID=ctg1,length=1>", "##contig=<ID=ctg2,length=2>"]
    app = custom_app(MAP, contigs, ["ctg1"])
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "chrA",
                                                     "ctg2": "chrB"}
    app.naming("Ensembl names")                              # target change
    assert "result_vcf_contig_renames" not in app.state
    assert not _has(app.at, "download_button", "download_vcf")
    app.run()
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "A"}
    other = (HEADER + "ctg1\tchrZ\tZ\t\t\n").encode()
    app.mapping(other)                                       # mapping change
    assert "result_vcf_contig_renames" not in app.state
    app.run()
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "Z"}
    app.naming("Keep original names")                        # normalize -> keep
    assert "result_vcf_contig_renames" not in app.state
    app.run()
    assert app.state["result_vcf_contig_renames"] == {}


def test_source_change_between_bundled_and_custom_never_reuses_header_renames():
    contigs = ["##contig=<ID=1,length=1>", "##contig=<ID=ctg1,length=2>"]
    app = custom_app(MAP, contigs, ["ctg1"])
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "chrA"}
    app.source(GRCH38)
    assert "result_vcf_contig_renames" not in app.state
    app.run()
    assert app.state["result_vcf_contig_renames"] == {"1": "chr1"}   # not ctg1
