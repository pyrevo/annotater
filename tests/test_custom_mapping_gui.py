"""Custom chromosome mapping in the application (one source, one registry).

The single "Genome assembly" control gains one alternative, "Custom
chromosome mapping…". The run resolves the chosen source once to a
``ChromosomeRegistry`` and calls the same orchestration as for a bundled
assembly; these tests exercise that through the real app (AppTest) and check
that no state leaks between sources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.core.chrom_registry import (
    CUSTOM_REGISTRY_NAME,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ROWS,
)
from streamlit_app.streamlit_app import _CUSTOM_OPTION

APP = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"
GRCH38 = "Human — Dec. 2013 (GRCh38/hg38)"
HEADER = "assembly\tucsc\tensembl\tgenbank\trefseq\n"

# Non-model names on purpose: nothing here resembles a real assembly.
MAPPING_A = (HEADER
             + "ctg1\tchrA\tA\tGB1\tRS1\n"
             + "ctg2\tchrB\t\t\t\n").encode()
# Same byte length and name as A, different content.
MAPPING_B = (HEADER
             + "ctg1\tchrZ\tA\tGB1\tRS1\n"
             + "ctg2\tchrB\t\t\t\n").encode()
assert len(MAPPING_A) == len(MAPPING_B) and MAPPING_A != MAPPING_B

QUERY = b"ctg1\t100\t200\tq1\nctg2\t100\t200\tq2\nother\t0\t10\tq3\n"
ANNOT = (b"##gff-version 3\n"
         b"chrA\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=GA\n"
         b"chrB\tsrc\tgene\t150\t250\t.\t+\t.\tID=g2;Name=GB\n"
         b"chrZ\tsrc\tgene\t150\t250\t.\t+\t.\tID=g3;Name=GZ\n")
HUMAN_QUERY = b"1\t100\t200\tq1\n"
HUMAN_ANNOT = (b"##gff-version 3\n"
               b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n")


def _widget(at, kind, key):
    for element in at.get(kind):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {kind} with key {key!r}")


def _has(at, kind, key):
    return any(getattr(e, "key", None) == key for e in at.get(kind))


class App:
    """A user driving one session."""

    def __init__(self, query=QUERY, annot=ANNOT, qname="q.bed"):
        self.at = AppTest.from_file(str(APP), default_timeout=120)
        self.at.run()
        _widget(self.at, "file_uploader", "coord_file").set_value(
            (qname, query, "application/octet-stream"))
        _widget(self.at, "file_uploader", "annot_file").set_value(
            ("a.gff3", annot, "application/octet-stream"))
        self.at.run()

    def source(self, label):
        _widget(self.at, "selectbox", "chr_assembly").set_value(label)
        self.at.run()
        return self

    def naming(self, label):
        _widget(self.at, "selectbox", "chr_naming").set_value(label)
        self.at.run()
        return self

    def mapping(self, data, name="mapping.tsv"):
        _widget(self.at, "file_uploader", "chr_mapping_file").set_value(
            (name, data, "text/tab-separated-values"))
        self.at.run()
        return self

    def run(self):
        _widget(self.at, "button", "run_button").set_value(True)
        self.at.run()
        assert not self.at.exception, self.at.exception
        return self

    @property
    def state(self):
        return self.at.session_state

    @property
    def done(self):
        return "result_df" in self.state

    @property
    def errors(self):
        return [e.value for e in self.at.error]

    @property
    def captions(self):
        return [c.value for c in self.at.caption]

    @property
    def codes(self):
        return [c.value for c in self.at.get("code")]

    @property
    def chrs(self):
        return self.state["result_df"]["coord_chr"].tolist()


def custom_run(mapping=MAPPING_A, naming="UCSC names", **kw):
    app = App(**kw)
    app.source(_CUSTOM_OPTION).naming(naming)
    if mapping is not None:
        app.mapping(mapping)
    return app.run()


# ---- selector and uploader -------------------------------------------------------

def test_custom_is_the_first_option_after_the_placeholder_and_nothing_is_preselected():
    app = App()
    box = _widget(app.at, "selectbox", "chr_assembly")
    assert list(box.options)[:2] == ["Select genome assembly",
                                     "Custom chromosome mapping…"]
    assert box.value == "Select genome assembly"
    assert [e.label for e in app.at.get("selectbox")].count("Genome assembly") == 1


def test_the_uploader_appears_only_for_the_custom_option():
    app = App()
    assert not _has(app.at, "file_uploader", "chr_mapping_file")
    app.source(_CUSTOM_OPTION)
    uploader = _widget(app.at, "file_uploader", "chr_mapping_file")
    assert uploader.label == "Chromosome mapping file"
    assert list(uploader.proto.type) == [".tsv"]
    assert "does not verify" in uploader.proto.help      # the honest caveat
    app.source(GRCH38)
    assert not _has(app.at, "file_uploader", "chr_mapping_file")


def test_there_are_no_extra_source_controls():
    app = App().source(_CUSTOM_OPTION)
    labels = [e.label for e in app.at.get("selectbox") + app.at.get("radio")]
    for forbidden in ("Species", "Assembly", "Mapping mode", "Registry source"):
        assert forbidden not in labels
    assert labels.count("Genome assembly") == 1


# ---- keep original -----------------------------------------------------------------

def test_keep_original_with_custom_selected_needs_no_file_and_parses_nothing(
        monkeypatch):
    import streamlit_app.core.chrom_registry as package
    calls = []
    real = package.resolve_registry_source
    monkeypatch.setattr(package, "resolve_registry_source",
                        lambda **kw: calls.append(kw) or real(**kw))
    app = App().source(_CUSTOM_OPTION).run()
    assert app.done and app.state["result_chr_normalization"] is None
    assert calls == []
    assert "chr_mapping_loaded" not in app.state


def test_an_unused_upload_is_not_parsed_under_keep_original(monkeypatch):
    import streamlit_app.core.chrom_registry as package
    calls = []
    monkeypatch.setattr(package, "resolve_registry_source",
                        lambda **kw: calls.append(kw))
    app = App().source(_CUSTOM_OPTION).mapping(b"not even a table")
    app.run()
    assert app.done and calls == []
    assert not app.errors


# ---- missing / invalid file --------------------------------------------------------

def test_custom_without_a_file_blocks_a_normalizing_run_with_a_clear_message():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names")
    assert any("Upload a chromosome mapping file" in w.value
               for w in app.at.warning)
    app.run()
    assert not app.done
    assert ("Upload a chromosome mapping file before normalizing chromosome "
            "names.") in app.errors


@pytest.mark.parametrize("data,code", [
    (b"ucsc\tassembly\tensembl\tgenbank\trefseq\nchr1\t1\t\t\t\n", "HEADER"),
    (HEADER.encode() + b"c1\tchrA\t\t\t\nc2\tchrA\t\t\t\n", "ALIAS_COLLISION"),
    (HEADER.encode() + b"c1\tchrA\t\t\t\n\n", "EMPTY_ROW"),
    (HEADER.encode() + b"c1\tchrA\t\t\t\nc1\tchrA\t\t\t\n", "DUPLICATE_ROW"),
    (HEADER.encode() + b" c1\tchrA\t\t\t\n", "WHITESPACE"),
    (b"\xff\xfe\x00", "ENCODING"),
    (b"", "EMPTY_FILE"),
])
def test_invalid_mappings_show_a_plain_error_and_block_the_run(data, code):
    app = custom_run(data)
    assert not app.done
    assert "The chromosome mapping file is not valid" in app.errors[0]
    shown = "\n".join(app.codes)
    assert code in shown
    assert "Traceback" not in shown and "CustomRegistryError" not in shown


def test_validation_issues_show_lines_and_columns():
    app = custom_run(HEADER.encode() + b"c1\tchrA\t\t\t\nc2\tchrA\t\t\t\n")
    shown = "\n".join(app.codes)
    assert "line 2, 3 [ucsc]: ALIAS_COLLISION" in shown
    assert "'chrA'" in shown
    assert shown.count("ALIAS_COLLISION") == 1            # reported once


def test_the_file_is_never_repaired_silently():
    # a padded cell is rejected, not trimmed into a working mapping
    app = custom_run(HEADER.encode() + b"c1\tchrA \t\t\t\n")
    assert not app.done and app.codes


def test_uploaded_content_is_shown_as_plain_text_not_markdown_or_html():
    hostile = "<b>x</b> **bold** [l](http://e.x) <script>alert(1)</script>"
    data = (HEADER + f"c1\t{hostile}\t\t\t\nc2\t{hostile}\t\t\t\n").encode()
    app = custom_run(data)
    assert hostile in "\n".join(app.codes)               # literal, in a code block
    assert all(hostile not in e for e in app.errors)
    assert all(hostile not in m.value for m in app.at.markdown)
    assert all(hostile not in c for c in app.captions)


def test_the_loader_limits_apply_and_oversized_files_get_a_clear_message():
    assert DEFAULT_MAX_ROWS == 500_000 and DEFAULT_MAX_BYTES == 64 * 2**20
    app = custom_run(HEADER.encode() + b"x" * DEFAULT_MAX_BYTES)
    assert not app.done and "TOO_LARGE" in "\n".join(app.codes)


# ---- valid mappings use the existing report semantics ---------------------------------

def test_a_valid_mapping_normalizes_through_the_shared_path():
    app = custom_run()
    assert app.done
    # ctg1 -> chrA, ctg2 -> chrB, "other" is not in the mapping
    assert app.chrs == ["chrA", "chrB", "other"]
    summary = app.state["result_chr_normalization"]
    assert summary["assembly_label"] is None
    assert summary["source_label"] == CUSTOM_REGISTRY_NAME
    assert summary["coord_report"].assembly is None
    assert summary["coord_report"].registry_name == CUSTOM_REGISTRY_NAME
    assert "Loaded 2 sequence mappings" in app.captions
    # annotations normalized too: matches exist only via the mapping
    assert app.state["result_df"]["has_overlap"].tolist()[:2] == [True, True]


def test_the_source_label_is_custom_and_never_a_fake_assembly():
    app = custom_run()
    text = " ".join(app.captions)
    assert "Custom chromosome mapping" in text
    assert "Genome assembly: " not in text
    assert "Coordinates are unchanged." in text


def test_unknown_input_is_reported_and_left_as_provided():
    app = custom_run()
    report = app.state["result_chr_normalization"]["coord_report"]
    assert report.unknown == {"other": 1}
    assert any("Not recognized in Custom chromosome mapping" in m.value
               for m in app.at.markdown)


def test_missing_target_names_are_reported_as_no_alias_for_target():
    app = custom_run(naming="Ensembl names")
    report = app.state["result_chr_normalization"]["coord_report"]
    assert app.chrs == ["A", "ctg2", "other"]          # ctg2 has no ensembl name
    assert report.no_alias_for_target == {"ctg2": 1}
    assert any("no verified name is available in Ensembl names" in m.value
               for m in app.at.markdown)


def test_every_naming_option_stays_available_for_a_partial_mapping():
    app = App().source(_CUSTOM_OPTION).mapping(MAPPING_A)
    assert list(_widget(app.at, "selectbox", "chr_naming").options) == [
        "Keep original names", "UCSC names", "Ensembl names",
        "NCBI RefSeq accessions", "GenBank accessions", "Assembly names"]


def test_a_mapping_can_merge_names_and_the_merge_is_reported():
    mapping = (HEADER + "ctg1\tchrA\t\t\t\nctg2\tchrA2\t\t\t\n").encode()
    # two query names that name the same sequence: ctg1 (assembly) and chrA (ucsc)
    app = custom_run(mapping, query=b"ctg1\t100\t200\tq1\nchrA\t300\t400\tq2\n")
    report = app.state["result_chr_normalization"]["coord_report"]
    assert list(report.collapses) == ["chrA"]
    assert set(app.chrs) == {"chrA"}
    assert any("normalized to the same output name" in i.value
               for i in app.at.info)


def test_the_filename_has_no_meaning():
    a = custom_run(MAPPING_A)
    b = App().source(_CUSTOM_OPTION).naming("UCSC names")
    b.mapping(MAPPING_A, name="GRCh38_hg38_ensembl.tsv").run()
    assert b.chrs == a.chrs
    assert (b.state["result_chr_normalization"]["source_label"]
            == CUSTOM_REGISTRY_NAME)


def test_the_run_calls_the_same_orchestration_with_a_registry(monkeypatch):
    import streamlit_app.core.chromosome_inputs as inputs
    calls = []
    real = inputs.normalize_input_chromosomes

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(inputs, "normalize_input_chromosomes", spy)
    custom_run()
    App(HUMAN_QUERY, HUMAN_ANNOT).source(GRCH38).naming("UCSC names").run()
    assert len(calls) == 2
    for call in calls:
        assert set(call) == {"registry", "target"}       # never assembly=
    assert calls[0]["registry"].assembly_id is None
    assert calls[1]["registry"].assembly_id == "GRCh38"


def test_a_bundled_assembly_still_reports_its_genome_assembly():
    app = App(HUMAN_QUERY, HUMAN_ANNOT).source(GRCH38).naming("UCSC names").run()
    assert app.chrs == ["chr1"]
    assert app.state["result_chr_normalization"]["assembly_label"] == GRCH38
    assert any("Genome assembly: " + GRCH38 in c for c in app.captions)
    assert app.state["result_chr_normalization"]["coord_report"].assembly == "GRCh38"


def test_a_bundled_alias_resolves_to_the_canonical_identity_internally():
    # the GUI maps a label straight to the canonical id; programmatic aliases
    # land on the same registry
    from streamlit_app.core.chrom_registry import load_registry
    from streamlit_app.streamlit_app import _ASSEMBLY_OPTIONS
    assert _ASSEMBLY_OPTIONS[GRCH38] == "GRCh38"
    assert load_registry("hg38") is load_registry(_ASSEMBLY_OPTIONS[GRCH38])


# ---- switching sources: nothing leaks --------------------------------------------------

def test_custom_to_bundled_switch_clears_results_and_uses_the_bundled_registry():
    app = App(b"1\t100\t200\tq1\nctg1\t0\t10\tq2\n", HUMAN_ANNOT)
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A).run()
    assert app.done and app.chrs == ["1", "chrA"]  # "1" unknown in the mapping
    app.source(GRCH38)
    assert not app.done                                   # results invalidated
    assert "chr_mapping_loaded" not in app.state          # custom registry dropped
    assert not _has(app.at, "file_uploader", "chr_mapping_file")
    app.run()
    assert app.chrs == ["chr1", "ctg1"]                   # ctg1 unknown in GRCh38
    assert app.state["result_chr_normalization"]["assembly_label"] == GRCH38


def test_bundled_to_custom_switch_clears_results_and_requires_a_file():
    app = App(HUMAN_QUERY, HUMAN_ANNOT).source(GRCH38).naming("UCSC names").run()
    assert app.done
    app.source(_CUSTOM_OPTION)
    assert not app.done                                   # no stale bundled result
    app.run()
    assert not app.done
    assert ("Upload a chromosome mapping file before normalizing chromosome "
            "names.") in app.errors
    app.mapping(MAPPING_A)
    assert not app.done


def test_custom_file_a_to_custom_file_b_invalidates_and_uses_the_new_mapping():
    app = custom_run(MAPPING_A)
    assert app.chrs[0] == "chrA"
    app.mapping(MAPPING_B)
    assert not app.done                                   # A's results are gone
    app.run()
    assert app.chrs[0] == "chrZ"                          # B's mapping, not A's


def test_same_filename_and_size_but_different_bytes_invalidate_results():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names")
    app.mapping(MAPPING_A, name="same.tsv").run()
    first = app.state["result_signature"]
    app.mapping(MAPPING_B, name="same.tsv")
    assert not app.done
    app.run()
    assert app.state["result_signature"] != first
    assert hashlib.sha256(MAPPING_A).hexdigest() != hashlib.sha256(
        MAPPING_B).hexdigest()


def test_identical_bytes_under_another_name_keep_the_same_identity():
    app = App().source(_CUSTOM_OPTION).naming("UCSC names")
    app.mapping(MAPPING_A, name="one.tsv").run()
    signature = app.state["result_signature"]
    app.mapping(MAPPING_A, name="two.tsv")
    assert app.state["result_signature"] == signature     # content is the identity


def test_custom_to_keep_original_and_back():
    app = custom_run()
    assert app.chrs[0] == "chrA"
    app.naming("Keep original names")
    assert not app.done                                   # no stale normalized result
    assert "chr_mapping_loaded" not in app.state          # nothing kept unused
    app.run()
    assert app.chrs == ["ctg1", "ctg2", "other"]          # originals untouched
    assert app.state["result_chr_normalization"] is None
    app.naming("UCSC names")
    assert not app.done
    app.run()
    assert app.chrs[0] == "chrA"


def test_removing_the_file_after_a_successful_run_invalidates_the_result():
    app = custom_run()
    assert app.done
    uploader = _widget(app.at, "file_uploader", "chr_mapping_file")
    uploader.set_value(None)
    app.at.run()
    assert not app.done
    app.run()
    assert not app.done
    assert ("Upload a chromosome mapping file before normalizing chromosome "
            "names.") in app.errors


def test_the_mapping_exists_only_in_this_session():
    first = custom_run(MAPPING_A)
    second = App().source(_CUSTOM_OPTION).naming("UCSC names")
    assert "chr_mapping_loaded" not in second.state       # another session
    second.run()
    assert not second.done                                # needs its own upload
    assert first.done


# ---- VCF export safety --------------------------------------------------------------------

VCF = (b"##fileformat=VCFv4.2\n"
       b"##contig=<ID=ctg1,length=1000>\n"
       b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
       b"ctg1\t120\tv1\tA\tT\t50\tPASS\t.\n")


def test_vcf_contigs_follow_the_custom_mapping_and_stale_state_is_cleared():
    app = App(VCF, ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A).run()
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "chrA"}
    from streamlit_app.streamlit_app import convert_df_to_vcf
    vcf = convert_df_to_vcf(
        app.state["result_df"],
        original_header_lines=app.state["result_vcf_header_lines"],
        contig_renames=app.state["result_vcf_contig_renames"])
    assert "##contig=<ID=chrA,length=1000>" in vcf
    assert "ctg1" not in vcf
    assert _has(app.at, "download_button", "download_vcf")
    app.mapping(MAPPING_B)                                 # different mapping
    for key in ("result_df", "result_vcf_contig_renames",
                "result_vcf_header_lines", "result_coord_df"):
        assert key not in app.state                        # nothing stale
    assert not _has(app.at, "download_button", "download_vcf")
    app.run()
    assert app.state["result_vcf_contig_renames"] == {"ctg1": "chrZ"}


def test_switching_to_keep_original_clears_vcf_renames():
    app = App(VCF, ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(MAPPING_A).run()
    assert app.state["result_vcf_contig_renames"]
    app.naming("Keep original names")
    assert "result_vcf_contig_renames" not in app.state
    app.run()
    assert app.state["result_vcf_contig_renames"] == {}
