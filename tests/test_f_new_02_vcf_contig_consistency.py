"""
Task I1 / F-NEW-02 — exported VCF CHROM values and ``##contig``
declarations must agree after chromosome-name conversion.

Pre-fix, chromosome standardization (e.g. Ensembl ``1`` -> UCSC ``chr1``)
changed the CHROM of exported records while the original
``##contig=<ID=1,...>`` header line was preserved verbatim, so the
export declared a contig no record used and used a contig it never
declared (htslib: "Contig 'chr1' is not defined in the header").

Policy under test:
- the export keeps the identifiers of the AnnotateR result (the
  converted ones); the header is reconciled to them, never the reverse;
- only the ID of a ``##contig`` line whose identifier was converted is
  rewritten; length/assembly/md5/... and all other metadata are kept;
- no duplicate declaration of one contig ID results;
- unconverted contigs and exports without any conversion keep their
  original lines untouched;
- no ``##contig`` line is invented (no contig header stays none; a
  partial header stays partial);
- the rename mapping comes from the annotation run itself (the
  converter's own output), not from a second conversion table.

Expected values are hand-written from the fixtures, never produced by
running the exporter under test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.streamlit_app import convert_df_to_vcf

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"
ENGINES = ["Bedtools", "Polars-Bio"]

GT_FORMAT = '##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">\n'
HEADER_COLS = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"

# Ensembl-style query (1, 2, X, MT) plus a custom scaffold that no
# UCSC<->Ensembl mapping covers.
QUERY_ENSEMBL = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=1,length=248956422,assembly=GRCh38,md5=aaa,species=\"Homo sapiens\","
    "URL=http://example.org/1>\n"
    "##contig=<ID=2,length=242193529>\n"
    "##contig=<ID=X,length=156040895>\n"
    "##contig=<ID=MT,length=16569>\n"
    "##contig=<ID=scaffold_9,length=777>\n"
    + GT_FORMAT
    + HEADER_COLS
    + "1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
    "2\t100\tv2\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
    "X\t100\tv3\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
    "MT\t100\tv4\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
    "scaffold_9\t100\tv5\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
).encode()

ANNOT_UCSC = (
    "##gff-version 3\n"
    + "".join(
        f"{c}\tsrc\tgene\t50\t250\t.\t+\t.\tID=g_{c};Name=G_{c}\n"
        for c in ("chr1", "chr2", "chrX", "chrM", "scaffold_9")
    )
).encode()

ANNOT_ENSEMBL = (
    "##gff-version 3\n"
    + "".join(
        f"{c}\tsrc\tgene\t50\t250\t.\t+\t.\tID=g_{c};Name=G_{c}\n"
        for c in ("1", "2", "X", "MT", "scaffold_9")
    )
).encode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _widget(at: AppTest, etype: str, key: str):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _app_export(query: bytes, annot: bytes, engine: str = "Bedtools",
                assembly: str = "Human \u2014 Dec. 2013 (GRCh38/hg38)",
                naming: str = "UCSC names") -> str:
    """
    Real app path (parse -> chromosome naming -> engine -> state),
    then the export exactly as the download button invokes it.
    """
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _widget(at, "radio", "engine").set_value(engine)
    _widget(at, "selectbox", "chr_assembly").set_value(assembly)
    _widget(at, "selectbox", "chr_naming").set_value(naming)
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.vcf", query, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", annot, "application/octet-stream")
    )
    at.run()
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    if at.exception:
        raise at.exception[0].value
    state = at.session_state
    return convert_df_to_vcf(
        state["result_df"],
        original_header_lines=state["result_vcf_header_lines"],
        contig_renames=state["result_vcf_contig_renames"],
    )


def _contig_lines(vcf: str):
    return [l for l in vcf.splitlines() if l.startswith("##contig=")]


def _contig_ids(vcf: str):
    return [re.match(r"##contig=<ID=([^,>]+)", l).group(1)
            for l in _contig_lines(vcf)]


def _record_chroms(vcf: str):
    return [l.split("\t")[0] for l in vcf.splitlines()
            if l and not l.startswith("#")]


def _frame(chroms):
    n = len(chroms)
    return pd.DataFrame({
        "coord_chr": chroms,
        "coord_start": [99] * n,
        "coord_end": [100] * n,
        "coord_id": [f"v{i}" for i in range(n)],
        "coord_ref": ["A"] * n,
        "coord_alt": ["T"] * n,
        "coord_qual": [50] * n,
        "coord_filter": ["PASS"] * n,
        "coord_info": ["."] * n,
    })


# ---------------------------------------------------------------------------
# Provenance: the rename mapping
# ---------------------------------------------------------------------------

def test_renames_come_from_the_normalization_report_only_for_changes():
    from streamlit_app.core import normalize_chromosomes
    df = pd.DataFrame({"chr": ["1", "X", "MT", "scaffold_9", "1"],
                       "start": [1] * 5, "end": [2] * 5})
    report = normalize_chromosomes(df, assembly="GRCh38",
                                   target="ucsc").report
    assert dict(report.renames) == {"1": "chr1", "X": "chrX", "MT": "chrM"}


def test_no_renames_when_nothing_is_converted():
    from streamlit_app.core import normalize_chromosomes
    df = pd.DataFrame({"chr": ["chr1", "chr2"], "start": [1, 1],
                       "end": [2, 2]})
    report = normalize_chromosomes(df, assembly="GRCh38",
                                   target="ucsc").report
    assert dict(report.renames) == {}


# ---------------------------------------------------------------------------
# Exporter-level reconciliation (explicit renames)
# ---------------------------------------------------------------------------

class TestReconciliation:
    def test_single_contig_id_renamed_other_fields_preserved(self):
        header = [
            "##fileformat=VCFv4.2",
            "##contig=<ID=1,length=1000,assembly=GRCh38,md5=abc,"
            'species="Homo sapiens",URL=http://x.org/1>',
        ]
        out = convert_df_to_vcf(
            _frame(["chr1"]), original_header_lines=header,
            contig_renames={"1": "chr1"},
        )
        assert _contig_lines(out) == [
            "##contig=<ID=chr1,length=1000,assembly=GRCh38,md5=abc,"
            'species="Homo sapiens",URL=http://x.org/1>'
        ]

    def test_stale_original_id_not_left_beside_new_one(self):
        out = convert_df_to_vcf(
            _frame(["chr1"]),
            original_header_lines=["##contig=<ID=1,length=1000>"],
            contig_renames={"1": "chr1"},
        )
        assert _contig_ids(out) == ["chr1"]

    def test_multiple_contigs_incl_mitochondrial_are_order_independent(self):
        header = [
            "##fileformat=VCFv4.2",
            "##contig=<ID=1,length=10>",
            "##contig=<ID=2,length=20>",
            "##contig=<ID=X,length=30>",
            "##contig=<ID=MT,length=40>",
        ]
        renames = {"1": "chr1", "2": "chr2", "X": "chrX", "MT": "chrM"}
        expected = [
            "##contig=<ID=chr1,length=10>",
            "##contig=<ID=chr2,length=20>",
            "##contig=<ID=chrX,length=30>",
            "##contig=<ID=chrM,length=40>",
        ]
        for rows in (["chr1", "chr2", "chrX", "chrM"],
                     ["chrM", "chrX", "chr2", "chr1"]):
            out = convert_df_to_vcf(
                _frame(rows), original_header_lines=header,
                contig_renames=renames,
            )
            assert _contig_lines(out) == expected  # source order kept
            assert set(_record_chroms(out)) <= set(_contig_ids(out))

    def test_renamed_onto_existing_declaration_is_not_duplicated(self):
        header = [
            "##contig=<ID=1,length=10>",
            "##contig=<ID=chr1,length=10>",
        ]
        out = convert_df_to_vcf(
            _frame(["chr1"]), original_header_lines=header,
            contig_renames={"1": "chr1"},
        )
        assert _contig_ids(out) == ["chr1"]

    def test_unsupported_custom_contig_untouched(self):
        header = [
            "##contig=<ID=1,length=10>",
            "##contig=<ID=scaffold_9,length=777>",
        ]
        out = convert_df_to_vcf(
            _frame(["chr1", "scaffold_9"]), original_header_lines=header,
            contig_renames={"1": "chr1"},
        )
        assert _contig_lines(out) == [
            "##contig=<ID=chr1,length=10>",
            "##contig=<ID=scaffold_9,length=777>",
        ]

    def test_no_renames_leaves_header_byte_identical(self):
        header = [
            "##fileformat=VCFv4.2",
            "##contig=<ID=chr1,length=10>",
            "##contig=<ID=scaffold_9,length=777>",
        ]
        frame = _frame(["chr1", "scaffold_9"])
        base = convert_df_to_vcf(frame, original_header_lines=header)
        for renames in (None, {}):
            out = convert_df_to_vcf(
                frame, original_header_lines=header, contig_renames=renames
            )
            # ##date aside (same day), the export is unchanged.
            assert out == base
        assert _contig_lines(base) == header[1:]

    def test_no_contig_header_stays_without_contig_lines(self):
        out = convert_df_to_vcf(
            _frame(["chr1"]),
            original_header_lines=["##fileformat=VCFv4.2", GT_FORMAT.strip()],
            contig_renames={"1": "chr1"},
        )
        assert _contig_lines(out) == []
        assert _record_chroms(out) == ["chr1"]

    def test_partial_header_stays_partial_without_invented_declarations(self):
        header = ["##contig=<ID=2,length=20>", "##contig=<ID=7,length=70>"]
        out = convert_df_to_vcf(
            _frame(["chr1", "chr2"]), original_header_lines=header,
            contig_renames={"1": "chr1", "2": "chr2"},
        )
        # declared + converted -> renamed; chr1 never declared -> not
        # invented; declared but unconverted-and-unused (7) -> kept.
        assert _contig_lines(out) == [
            "##contig=<ID=chr2,length=20>",
            "##contig=<ID=7,length=70>",
        ]

    def test_declared_contig_absent_from_rows_is_still_renamed(self):
        out = convert_df_to_vcf(
            _frame(["chr1"]),
            original_header_lines=[
                "##contig=<ID=1,length=10>", "##contig=<ID=2,length=20>",
            ],
            contig_renames={"1": "chr1", "2": "chr2"},
        )
        assert _contig_ids(out) == ["chr1", "chr2"]

    def test_other_metadata_untouched_by_reconciliation(self):
        header = [
            "##fileformat=VCFv4.3",
            "##contig=<ID=1,length=10>",
            '##INFO=<ID=DP,Number=1,Type=Integer,Description="1 and ID=1">',
            '##FILTER=<ID=1,Description="filter literally named 1">',
            GT_FORMAT.strip(),
            "##reference=file:///1.fa",
        ]
        with_r = convert_df_to_vcf(
            _frame(["chr1"]), original_header_lines=header,
            contig_renames={"1": "chr1"},
        )
        without = convert_df_to_vcf(
            _frame(["chr1"]), original_header_lines=header
        )
        changed = [
            (a, b) for a, b in zip(without.splitlines(), with_r.splitlines())
            if a != b
        ]
        assert changed == [(
            "##contig=<ID=1,length=10>", "##contig=<ID=chr1,length=10>"
        )]


# ---------------------------------------------------------------------------
# End to end through the app (both engines)
# ---------------------------------------------------------------------------

EXPECTED_CONTIGS_CONVERTED = [
    "##contig=<ID=chr1,length=248956422,assembly=GRCh38,md5=aaa,"
    'species="Homo sapiens",URL=http://example.org/1>',
    "##contig=<ID=chr2,length=242193529>",
    "##contig=<ID=chrX,length=156040895>",
    "##contig=<ID=chrM,length=16569>",
    "##contig=<ID=scaffold_9,length=777>",
]


@pytest.mark.parametrize("engine", ENGINES)
class TestAppEndToEnd:
    def test_ensembl_query_converted_header_matches_records(self, engine):
        out = _app_export(QUERY_ENSEMBL, ANNOT_UCSC, engine)
        assert _contig_lines(out) == EXPECTED_CONTIGS_CONVERTED
        assert sorted(set(_record_chroms(out))) == sorted(
            ["chr1", "chr2", "chrX", "chrM", "scaffold_9"]
        )
        # every exported CHROM is declared, none declared twice
        ids = _contig_ids(out)
        assert set(_record_chroms(out)) <= set(ids)
        assert len(ids) == len(set(ids))

    def test_unchanged_chromosomes_keep_original_header(self, engine):
        query = (
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=chr1,length=248956422,assembly=GRCh38>\n"
            "##contig=<ID=scaffold_9,length=777>\n"
            + GT_FORMAT + HEADER_COLS
            + "chr1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
            "scaffold_9\t100\tv5\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
        ).encode()
        out = _app_export(query, ANNOT_UCSC, engine)
        assert _contig_lines(out) == [
            "##contig=<ID=chr1,length=248956422,assembly=GRCh38>",
            "##contig=<ID=scaffold_9,length=777>",
        ]

    def test_ucsc_query_ensembl_annotation_is_standardized_to_ucsc(
        self, engine
    ):
        # Normalizing to UCSC names: a UCSC query is not
        # renamed, so its declarations stay untouched.
        query = (
            "##fileformat=VCFv4.2\n##contig=<ID=chr1,length=10>\n"
            + GT_FORMAT + HEADER_COLS
            + "chr1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
        ).encode()
        out = _app_export(query, ANNOT_ENSEMBL, engine)
        assert _contig_lines(out) == ["##contig=<ID=chr1,length=10>"]
        assert _record_chroms(out) == ["chr1"]

    def test_query_without_contig_header_has_none_after_conversion(
        self, engine
    ):
        query = (
            "##fileformat=VCFv4.2\n" + GT_FORMAT + HEADER_COLS
            + "1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
        ).encode()
        out = _app_export(query, ANNOT_UCSC, engine)
        assert _contig_lines(out) == []
        assert _record_chroms(out) == ["chr1"]

    def test_partial_contig_header_after_conversion(self, engine):
        query = (
            "##fileformat=VCFv4.2\n##contig=<ID=2,length=20>\n"
            + GT_FORMAT + HEADER_COLS
            + "1\t100\tv1\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
            "2\t100\tv2\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
        ).encode()
        out = _app_export(query, ANNOT_UCSC, engine)
        assert _contig_lines(out) == ["##contig=<ID=chr2,length=20>"]
        assert set(_record_chroms(out)) == {"chr1", "chr2"}


def test_both_engines_export_identical_vcf_after_conversion():
    def normalized(text):
        return "\n".join(l for l in text.splitlines()
                         if not l.startswith("##date="))

    outs = [
        normalized(_app_export(QUERY_ENSEMBL, ANNOT_UCSC, e))
        for e in ENGINES
    ]
    assert outs[0] == outs[1]


# ---------------------------------------------------------------------------
# Independent validation with pysam / htslib
# ---------------------------------------------------------------------------

def test_pysam_reads_converted_export_without_undefined_contig_warning(
    tmp_path, capfd
):
    pysam = pytest.importorskip(
        "pysam", reason="independent VCF validation needs pysam"
    )
    out = _app_export(QUERY_ENSEMBL, ANNOT_UCSC, "Bedtools")
    path = tmp_path / "out.vcf"
    path.write_text(out)
    capfd.readouterr()  # drop output from the app run

    with pysam.VariantFile(str(path)) as vf:
        contigs = vf.header.contigs
        assert list(contigs) == ["chr1", "chr2", "chrX", "chrM", "scaffold_9"]
        assert contigs["chr1"].length == 248956422
        assert contigs["chrM"].length == 16569
        assert contigs["scaffold_9"].length == 777
        assert "GT" in vf.header.formats
        records = list(vf)

    assert [r.chrom for r in records] == [
        "chr1", "chr2", "chrX", "chrM", "scaffold_9"
    ]
    assert [r.pos for r in records] == [100] * 5
    assert [r.id for r in records] == ["v1", "v2", "v3", "v4", "v5"]
    assert all(r.samples["S1"]["GT"] == (0, 1) for r in records)
    for r in records:
        assert r.chrom in contigs
        assert r.info["ANNOT_ID"] == (f"g_{r.chrom}",)

    captured = capfd.readouterr()
    assert "not defined in the header" not in captured.err + captured.out
