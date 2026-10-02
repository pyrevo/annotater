"""``transcript`` feature-filter choice (F-NEW-07).

The single user-facing ``transcript`` choice maps to an explicit,
case-sensitive set of source ``feature`` values: GENCODE/Ensembl
``transcript`` (GTF and GFF3) and the GFF3 specification's ``mRNA``.
Other RNA classes (``lnc_RNA``, ``ncRNA``, ``rRNA``, ...) are distinct
feature types and must NOT match. Source values are never rewritten.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.streamlit_app import _expand_feature_types
from tests.test_streamlit_app_ui import (
    _app,
    _configure_and_run,
    _result,
    _run_flow,
)

TRANSCRIPT = "transcript"
COORD = b"chr1\t0\t10000\tq1\n"

# Real parser-to-filter inputs: GENCODE-style GTF and GFF3 with mRNA.
GTF = (
    b'chr1\tHAVANA\tgene\t100\t900\t.\t+\t.\tgene_id "g1";\n'
    b'chr1\tHAVANA\ttranscript\t100\t900\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'
    b'chr1\tHAVANA\texon\t100\t300\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'
)

GFF3 = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t100\t900\t.\t+\t.\tID=g1\n"
    b"chr1\tsrc\tmRNA\t100\t900\t.\t+\t.\tID=m1;Parent=g1\n"
    b"chr1\tsrc\texon\t100\t300\t.\t+\t.\tID=e1;Parent=m1\n"
)

MIXED = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t100\t900\t.\t+\t.\tID=g1\n"
    b"chr1\tsrc\ttranscript\t100\t900\t.\t+\t.\tID=t1;Parent=g1\n"
    b"chr1\tsrc\tmRNA\t1000\t1900\t.\t+\t.\tID=m1\n"
    b"chr1\tsrc\texon\t100\t300\t.\t+\t.\tID=e1;Parent=t1\n"
)

DUPLICATES = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tmRNA\t100\t900\t.\t+\t.\tID=m1\n"
    b"chr1\tsrc\tmRNA\t100\t900\t.\t+\t.\tID=m2\n"
    b"chr1\tsrc\ttranscript\t100\t900\t.\t+\t.\tID=t1\n"
    b"chr1\tsrc\ttranscript\t100\t900\t.\t+\t.\tID=t2\n"
)

INCLUDED = [
    "transcript", "mRNA", "lnc_RNA", "ncRNA", "rRNA", "tRNA", "snoRNA",
    "primary_transcript", "pseudogenic_transcript", "noncoding_transcript",
]

NOT_MAPPED = [
    "snRNA", "miRNA", "lincRNA", "RNA", "processed_transcript",
    "NMD_transcript_variant", "aberrant_processed_transcript",
    "tmRNA", "miscRNA", "scRNA", "transcript_region", "ncRNA_gene",
    "pseudogene", "gene", "exon", "CDS",
    "Transcript", "MRNA", "mrna", "LNC_RNA", "lncRNA",
]

# Ensembl GFF3: ncRNA_gene -> lnc_RNA -> exon (README: "a specific type of
# RNA transcript such as snoRNA or lnc_RNA").
ENSEMBL_NONCODING = (
    b"##gff-version 3\n"
    b"1\tensembl\tncRNA_gene\t100\t900\t.\t+\t.\tID=gene:G1;biotype=lncRNA\n"
    b"1\tensembl\tlnc_RNA\t100\t900\t.\t+\t.\tID=transcript:T1;Parent=gene:G1\n"
    b"1\tensembl\texon\t100\t300\t.\t+\t.\tParent=transcript:T1\n"
)

REFSEQ_QUERY = b"NC_000001.11\t0\t10000\tq1\n"

# NCBI RefSeq GFF3: coding = mRNA-exon-CDS; non-coding = transcript-exon.
REFSEQ_CODING = (
    b"##gff-version 3\n"
    b"NC_000001.11\tBestRefSeq\tgene\t100\t900\t.\t+\t.\tID=gene0\n"
    b"NC_000001.11\tBestRefSeq\tmRNA\t100\t900\t.\t+\t.\tID=rna0;Parent=gene0\n"
    b"NC_000001.11\tBestRefSeq\texon\t100\t300\t.\t+\t.\tID=exon0;Parent=rna0\n"
    b"NC_000001.11\tBestRefSeq\tCDS\t150\t300\t.\t+\t0\tID=cds0;Parent=rna0\n"
)
REFSEQ_NONCODING = (
    b"##gff-version 3\n"
    b"NC_000001.11\tBestRefSeq\tgene\t100\t900\t.\t+\t.\tID=gene1\n"
    b"NC_000001.11\tBestRefSeq\ttranscript\t100\t900\t.\t+\t.\tID=rna1;Parent=gene1\n"
    b"NC_000001.11\tBestRefSeq\tgene\t1000\t1900\t.\t+\t.\tID=gene2\n"
    b"NC_000001.11\tBestRefSeq\tncRNA\t1000\t1900\t.\t+\t.\tID=rna2;Parent=gene2\n"
    b"NC_000001.11\tBestRefSeq\tgene\t2000\t2900\t.\t+\t.\tID=gene3\n"
    b"NC_000001.11\tBestRefSeq\tprimary_transcript\t2000\t2900\t.\t+\t.\tID=rna3;Parent=gene3\n"
    b"NC_000001.11\tBestRefSeq\texon\t100\t300\t.\t+\t.\tID=exon1;Parent=rna1\n"
)


def _single(value):
    return (
        b"##gff-version 3\n"
        + f"chr1\tsrc\t{value}\t100\t900\t.\t+\t.\tID=r1\n".encode()
    )


def _features(at: AppTest) -> list[str]:
    return sorted(_result(at)["annot_feature"].dropna().tolist())


def _run(selection, engine="Bedtools", annot=("annot.gff", GFF3),
         query=COORD):
    at = _run_flow(_app(), "q.bed", query, annot[0], annot[1])
    return _configure_and_run(
        at,
        {
            "radio": {"engine": engine},
            "multiselect": {"feature_types": selection},
        },
    )


class TestMapping:
    def test_expansion_is_explicit_and_exact(self):
        assert _expand_feature_types([TRANSCRIPT]) == set(INCLUDED)

    @pytest.mark.parametrize("value", NOT_MAPPED)
    def test_excluded_values_not_mapped(self, value):
        assert value not in _expand_feature_types([TRANSCRIPT])

    def test_other_choices_unchanged(self):
        assert _expand_feature_types(["gene", "exon", "CDS"]) == {
            "gene", "exon", "CDS"}
        assert _expand_feature_types(["5' UTR"]) == {
            "five_prime_UTR", "five_prime_utr"}
        assert _expand_feature_types([]) == set()


@pytest.mark.parametrize("engine", ["Bedtools", "Polars-Bio"])
class TestFilterOnBothBackends:
    def test_matches_source_transcript_gtf(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gtf", GTF))
        assert _features(at) == ["transcript"]

    def test_matches_gff3_mrna_and_preserves_value(self, engine):
        at = _run([TRANSCRIPT], engine)
        assert _features(at) == ["mRNA"]

    def test_mixed_file_returns_both(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gff", MIXED))
        assert _features(at) == ["mRNA", "transcript"]

    def test_duplicates_remain_duplicated(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gff", DUPLICATES))
        assert _features(at) == ["mRNA", "mRNA", "transcript", "transcript"]

    def test_gene_and_exon_excluded(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gff", MIXED))
        assert not {"gene", "exon"} & set(_features(at))

    @pytest.mark.parametrize("value", INCLUDED)
    def test_every_included_value_matches_and_is_preserved(self, engine, value):
        at = _run([TRANSCRIPT], engine, ("annot.gff", _single(value)))
        assert _features(at) == [value]

    @pytest.mark.parametrize("value", NOT_MAPPED)
    def test_every_excluded_value_matches_nothing(self, engine, value):
        at = _run([TRANSCRIPT], engine, ("annot.gff", _single(value)))
        assert "result_df" not in at.session_state
        assert any("No annotations match" in w.value for w in at.warning)

    def test_ensembl_noncoding(self, engine):
        # Ensembl-style names in both files: this test is about the feature
        # filter, so no chromosome normalization is involved.
        at = _run([TRANSCRIPT], engine, ("annot.gff", ENSEMBL_NONCODING),
                  query=b"1\t0\t10000\tq1\n")
        assert _features(at) == ["lnc_RNA"]

    def test_refseq_coding(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gff", REFSEQ_CODING),
                 query=REFSEQ_QUERY)
        assert _features(at) == ["mRNA"]

    def test_refseq_noncoding(self, engine):
        at = _run([TRANSCRIPT], engine, ("annot.gff", REFSEQ_NONCODING),
                 query=REFSEQ_QUERY)
        assert _features(at) == ["ncRNA", "primary_transcript", "transcript"]

    def test_empty_selection_includes_all(self, engine):
        at = _run([], engine, ("annot.gff", MIXED))
        assert _features(at) == ["exon", "gene", "mRNA", "transcript"]

    def test_other_filters_unchanged(self, engine):
        assert _features(_run(["gene"], engine, ("annot.gff", MIXED))) == ["gene"]
        assert _features(_run(["exon"], engine, ("annot.gff", MIXED))) == ["exon"]


def test_engines_return_identical_results():
    def norm(df):
        df = df.astype(object).where(df.notna(), "<missing>").astype(str)
        cols = sorted(df.columns)
        return cols, df[cols].sort_values(cols).reset_index(drop=True)

    cols_a, a = norm(_result(_run([TRANSCRIPT], "Bedtools", ("annot.gff", MIXED))))
    cols_b, b = norm(_result(_run([TRANSCRIPT], "Polars-Bio", ("annot.gff", MIXED))))
    assert cols_a == cols_b
    assert len(a) == 2
    assert a.equals(b)
