"""Adversarial review (Task 10): GUI state machine and error behavior.

After every transition that changes the scientific configuration, no part of
the previous result (frame, report, VCF header state, rename map, download)
may survive.
"""

from __future__ import annotations

import pytest

from streamlit_app.core.chrom_registry import (
    UnsupportedAssemblyError,
    resolve_registry_source,
)
from streamlit_app.streamlit_app import _CUSTOM_OPTION, _RESULT_STATE_KEYS
from tests.test_custom_mapping_gui import (
    ANNOT,
    HEADER,
    MAPPING_A,
    MAPPING_B,
    QUERY,
    VCF,
    App,
    _has,
    custom_run,
)

GRCH38 = "Human — Dec. 2013 (GRCh38/hg38)"
HG19 = "Human — Feb. 2009 (GRCh37/hg19)"
HUMAN_Q = b"chrM\t0\t100\tq0\nchrMT\t0\t100\tq1\n"
HUMAN_A = (b"##gff-version 3\nMT\tsrc\tgene\t11\t20\t.\t+\t.\tID=g1\n"
           b"chrM\tsrc\tgene\t1\t10\t.\t+\t.\tID=g2\n")


def nothing_stale(app):
    leftovers = [k for k in _RESULT_STATE_KEYS if k in app.state]
    assert leftovers == [], leftovers
    assert not _has(app.at, "download_button", "download_vcf")
    assert not _has(app.at, "download_button", "download_csv")


def test_every_result_key_is_cleared_together():
    assert {"result_df", "result_coord_df", "result_chr_normalization",
            "result_vcf_contig_renames", "result_vcf_header_lines",
            "result_signature"} <= set(_RESULT_STATE_KEYS)


def test_bundled_assembly_a_to_bundled_assembly_b_uses_the_new_registry():
    app = App(HUMAN_Q, HUMAN_A).source(HG19).naming("Ensembl names").run()
    assert app.chrs == ["chrM", "MT"]               # hg19: chrM has no Ensembl name
    assert app.state["result_chr_normalization"]["assembly_label"] == HG19
    app.source(GRCH38)
    nothing_stale(app)
    app.run()
    # GRCh38: chrM names the mitochondrion (two annotations meet it) while
    # chrMT does not exist there and stays unrecognized
    assert app.chrs == ["MT", "MT", "chrMT"]
    assert dict(app.state["result_chr_normalization"]["coord_report"].unknown) == {
        "chrMT": 1}
    assert app.state["result_chr_normalization"]["assembly_label"] == GRCH38
    assert app.state["result_chr_normalization"]["coord_report"].assembly == "GRCh38"


def test_a_successful_run_then_an_invalid_file_leaves_no_result():
    app = custom_run(MAPPING_A)
    assert app.done
    app.mapping(HEADER.encode() + b"c1\tchrA\t\t\t\nc2\tchrA\t\t\t\n")
    nothing_stale(app)
    assert any("not valid" in e.value for e in app.at.error)
    app.run()
    assert not app.done and "ALIAS_COLLISION" in "\n".join(app.codes)


def test_an_invalid_file_then_a_valid_one_recovers_completely():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names")
    app.mapping(b"garbage")
    app.run()
    assert not app.done
    app.mapping(MAPPING_A)
    assert not any("not valid" in e.value for e in app.at.error)
    assert not app.codes
    app.run()
    assert app.done and app.chrs[0] == "chrA"


@pytest.mark.parametrize("change", ["naming", "engine"])
def test_changing_the_naming_or_engine_clears_the_result(change):
    app = custom_run(MAPPING_A)
    first = app.state["result_df"]["coord_chr"].tolist()
    if change == "naming":
        app.naming("GenBank accessions")
    else:
        from tests.test_custom_mapping_gui import _widget
        _widget(app.at, "radio", "engine").set_value("Polars-Bio")
        app.at.run()
    nothing_stale(app)
    app.run()
    after = app.state["result_df"]["coord_chr"].tolist()
    if change == "naming":
        assert after != first and after[0] == "GB1"
    else:
        assert after == first                       # same science, new engine


def test_an_unrelated_rerun_keeps_the_result_and_the_registry():
    app = custom_run(MAPPING_A)
    registry = app.state["chr_mapping_loaded"][1]
    signature = app.state["result_signature"]
    app.at.run()
    app.at.run()
    assert app.done and app.state["result_signature"] == signature
    assert app.state["chr_mapping_loaded"][1] is registry      # parsed once
    assert not app.errors


def test_the_stored_mapping_hash_tracks_the_bytes():
    import hashlib
    app = custom_run(MAPPING_A)
    assert app.state["chr_mapping_loaded"][0] == hashlib.sha256(MAPPING_A).hexdigest()
    app.mapping(MAPPING_B)
    assert app.state["chr_mapping_loaded"][0] == hashlib.sha256(MAPPING_B).hexdigest()


def test_keep_original_to_custom_does_not_resurrect_an_old_result():
    app = App().source(_CUSTOM_OPTION).run()                # keep original
    assert app.done and app.state["result_chr_normalization"] is None
    app.naming("UCSC names")
    nothing_stale(app)
    app.mapping(MAPPING_A)
    nothing_stale(app)
    app.run()
    assert app.chrs[0] == "chrA" and app.state["result_chr_normalization"]


def test_vcf_state_follows_every_source_change():
    app = App(VCF, ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A).run()
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "chrA"}
    app.source(GRCH38)
    nothing_stale(app)
    app.run()
    assert app.state["result_vcf_contig_renames"] == {}      # ctg1 unknown there
    assert app.state["result_vcf_header_lines"]               # header kept
    app.source(_CUSTOM_OPTION)
    nothing_stale(app)


# ---- error behavior: bad input, incomplete mapping, software failure -------------------------

def test_no_assembly_with_normalization_is_an_input_error_without_traceback():
    app = App(HUMAN_Q, HUMAN_A).naming("UCSC names").run()
    assert not app.done
    assert any("Select the genome assembly" in e.value for e in app.at.error)
    assert not app.at.exception


def test_custom_without_a_file_is_an_incomplete_mapping_message():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names").run()
    assert any("Upload a chromosome mapping file" in e.value for e in app.at.error)
    assert not app.at.exception and not app.done


def test_a_vcf_metadata_conflict_is_reported_not_raised_in_the_page():
    vcf = (b"##fileformat=VCFv4.2\n##contig=<ID=ctg1,length=5>\n"
           b"##contig=<ID=chrA,length=6>\n"
           b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
           b"ctg1\t120\tv1\tA\tT\t50\tPASS\t.\n")
    app = App(vcf, ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A).run()
    assert not app.at.exception
    assert any("disagree" in e.value for e in app.at.error)
    assert not _has(app.at, "download_button", "download_vcf")


def test_an_unsupported_assembly_programmatically_is_a_typed_error():
    with pytest.raises(UnsupportedAssemblyError, match="supported:"):
        resolve_registry_source(assembly="hg99")


def test_the_app_shows_custom_trust_wording_without_overclaiming():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A)
    shown = " ".join(app.captions + [c.value for c in app.at.markdown])
    from tests.test_custom_mapping_gui import _widget
    help_text = _widget(app.at, "file_uploader", "chr_mapping_file").proto.help
    for text in (shown, help_text):
        lowered = text.lower()
        for claim in ("verified", "certified", "validated", "confirmed",
                      "biologically correct names"):
            if claim in lowered:
                # only ever as a negation
                assert f"not {claim}" in lowered or f"does not {claim}" in lowered \
                    or "does not verify" in lowered, (claim, text)
    assert "does not verify" in help_text
    assert QUERY                                           # (fixture import used)
