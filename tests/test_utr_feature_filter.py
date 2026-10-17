"""Directional UTR feature-filter choices (5' UTR / 3' UTR).

The filter matches the annotation ``feature`` column exactly and
case-sensitively. The directional UI choices map to explicit sets of
accepted source spellings (GFF3 / Sequence Ontology ``five_prime_UTR`` /
``three_prime_UTR``; the pre-GFF3-1.16 lowercase ``*_utr`` spelling).
Generic ``UTR`` (GENCODE GTF) carries no direction and must NOT match
either directional choice. Source values are never rewritten.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.core.execution import (
    expand_feature_types as _expand_feature_types,
)
from streamlit_app.streamlit_app import _FEATURE_TYPE_OPTIONS
from tests.test_streamlit_app_ui import (
    _app,
    _assert_no_exception,
    _configure_and_run,
    _result,
    _run_flow,
    _widget,
)

FIVE = "5' UTR"
THREE = "3' UTR"

# One query spanning every annotation; left join keeps one row per
# matching annotation interval.
COORD = b"chr1\t0\t10000\tq1\n"

GFF3 = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t100\t900\t.\t+\t.\tID=g1\n"
    b"chr1\tsrc\texon\t100\t300\t.\t+\t.\tID=e1\n"
    b"chr1\tsrc\tfive_prime_UTR\t1000\t1100\t.\t+\t.\tID=u5\n"
    b"chr1\tsrc\tthree_prime_UTR\t2000\t2100\t.\t+\t.\tID=u3\n"
    b"chr1\tsrc\tfive_prime_utr\t3000\t3100\t.\t+\t.\tID=u5l\n"
    b"chr1\tsrc\tthree_prime_utr\t4000\t4100\t.\t+\t.\tID=u3l\n"
    b"chr1\tsrc\tUTR\t5000\t5100\t.\t+\t.\tID=ug\n"
)

GTF = (
    b'chr1\tsrc\tgene\t100\t900\t.\t+\t.\tgene_id "g1";\n'
    b'chr1\tsrc\tfive_prime_utr\t1000\t1100\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'
    b'chr1\tsrc\tthree_prime_utr\t2000\t2100\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'
    b'chr1\tsrc\tUTR\t5000\t5100\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'
)


def _features(at: AppTest) -> list[str]:
    df = _result(at)
    return sorted(df["annot_feature"].dropna().tolist())


def _run(selection, engine="Bedtools", annot=("annot.gff", GFF3)):
    at = _run_flow(_app(), "q.bed", COORD, annot[0], annot[1])
    return _configure_and_run(
        at,
        {
            "radio": {"engine": engine},
            "multiselect": {"feature_types": selection},
        },
    )


class TestMapping:
    def test_options_use_directional_labels_not_5utr_3utr(self):
        assert FIVE in _FEATURE_TYPE_OPTIONS
        assert THREE in _FEATURE_TYPE_OPTIONS
        assert "5UTR" not in _FEATURE_TYPE_OPTIONS
        assert "3UTR" not in _FEATURE_TYPE_OPTIONS

    def test_expansion_is_explicit_and_exact(self):
        assert _expand_feature_types([FIVE]) == {
            "five_prime_UTR", "five_prime_utr"}
        assert _expand_feature_types([THREE]) == {
            "three_prime_UTR", "three_prime_utr"}

    def test_generic_utr_is_not_in_either_directional_set(self):
        assert "UTR" not in _expand_feature_types([FIVE, THREE])

    def test_other_choices_pass_through_unchanged(self):
        assert _expand_feature_types(
            ["gene", "exon", "CDS", "start_codon"]
        ) == {"gene", "exon", "CDS", "start_codon"}


@pytest.mark.parametrize("engine", ["Bedtools", "Polars-Bio"])
class TestFilterOnBothBackends:
    def test_five_prime_gff3(self, engine):
        at = _run([FIVE], engine)
        # Both accepted spellings, original values preserved, no 3'.
        assert _features(at) == ["five_prime_UTR", "five_prime_utr"]

    def test_three_prime_gff3(self, engine):
        at = _run([THREE], engine)
        assert _features(at) == ["three_prime_UTR", "three_prime_utr"]

    def test_five_prime_gtf(self, engine):
        at = _run([FIVE], engine, ("annot.gtf", GTF))
        assert _features(at) == ["five_prime_utr"]

    def test_three_prime_gtf(self, engine):
        at = _run([THREE], engine, ("annot.gtf", GTF))
        assert _features(at) == ["three_prime_utr"]

    def test_both_directions_exclude_unrelated_and_generic_utr(self, engine):
        at = _run([FIVE, THREE], engine)
        assert _features(at) == [
            "five_prime_UTR", "five_prime_utr",
            "three_prime_UTR", "three_prime_utr",
        ]

    def test_generic_utr_only_file_matches_nothing(self, engine):
        generic = (
            b"##gff-version 3\n"
            b"chr1\tsrc\tUTR\t5000\t5100\t.\t+\t.\tID=ug\n"
        )
        at = _run([FIVE], engine, ("annot.gff", generic))
        assert "result_df" not in at.session_state
        assert any("No annotations match" in w.value for w in at.warning)

    def test_existing_filters_unchanged(self, engine):
        assert _features(_run(["gene"], engine)) == ["gene"]
        assert _features(_run(["exon"], engine)) == ["exon"]
        assert _features(_run(["gene", "exon"], engine)) == ["exon", "gene"]
