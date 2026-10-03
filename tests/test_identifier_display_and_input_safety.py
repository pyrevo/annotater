"""Pre-merge safety fixes: literal identifier display, bounded validation
messages, Unicode control characters and immutable registries.

- Chromosome identifiers come from user files. The GUI shows them in plain
  text blocks (``st.code``), never in Markdown, so ``HLA-A*01:01:01:01`` is
  displayed as written. The check is on the rendered element types of the
  real app, not on a helper.
- A custom-mapping validation message stays bounded however large the
  offending value or however often an alias repeats; the issue metadata
  (code, lines, columns) stays complete.
- Every Unicode ``Cc`` character is a control character (SPEC 5.1.1(4)),
  checked against ``unicodedata`` as an independent definition. Format
  characters (``Cf``, e.g. zero-width space) are not control characters:
  they are kept and matched exactly, never normalized.
- A bundled registry is one object shared by every caller and session; no
  caller can change its identity or contents.
"""

from __future__ import annotations

import sys
import unicodedata

import pandas as pd
import pytest

from streamlit_app.core.chrom_registry import (
    ChromosomeRegistry,
    CustomRegistryError,
    custom,
    describe_issue,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.chromosome_normalization import (
    normalize_chromosomes_with_registry,
)
from streamlit_app.streamlit_app import _CUSTOM_OPTION
from tests.test_custom_mapping_gui import ANNOT, HEADER, App, _has

# ---- literal identifiers in the GUI ----------------------------------------------------

HOSTILE = ["HLA-A*01:01:01:01", "chr_[1]", "foo`bar", "<script>", "a_b"]

# HLA-A*01:01:01:01 (assembly) and chr_[1] (ucsc) name one sequence, so both
# collapse onto chr_[1] under UCSC names and have no Ensembl name; the other
# three are unknown to the mapping.
HOSTILE_MAPPING = (HEADER + "HLA-A*01:01:01:01\tchr_[1]\t\t\t\n"
                   "ctgB\tchrB\tB\t\t\n").encode()
HOSTILE_QUERY = "".join(f"{name}\t{i * 10}\t{i * 10 + 5}\tq{i}\n"
                        for i, name in enumerate(HOSTILE)).encode()


def _texts(app, kind):
    return [e.value for e in app.at.get(kind)]


def _details(app):
    return next(e for e in app.at.get("expander")
                if e.label == "Chromosome normalization details")


def _hostile_run(naming):
    app = App(HOSTILE_QUERY, ANNOT)
    app.source(_CUSTOM_OPTION).naming(naming).mapping(HOSTILE_MAPPING)
    return app.run()


def _assert_only_in_plain_text(app, names):
    plain = "\n".join(_texts(app, "code"))
    for name in names:
        assert name in plain, name
    for kind in ("markdown", "caption", "error", "warning", "info", "success"):
        for text in _texts(app, kind):
            for name in names:
                assert name not in text, (kind, name, text)


def test_unknown_and_collapsed_identifiers_are_shown_literally():
    app = _hostile_run("UCSC names")
    report = app.state["result_chr_normalization"]["coord_report"]
    assert dict(report.unknown) == {"foo`bar": 1, "<script>": 1, "a_b": 1}
    assert dict(report.collapses) == {
        "chr_[1]": ("HLA-A*01:01:01:01", "chr_[1]")}
    codes = [c.value for c in _details(app).get("code")]
    assert codes == ["foo`bar (1 rows)\n<script> (1 rows)\na_b (1 rows)",
                     "HLA-A*01:01:01:01, chr_[1] \u2192 chr_[1]",
                     "chrA (1 rows)\nchrZ (1 rows)"]      # annotation table
    _assert_only_in_plain_text(app, HOSTILE)


def test_no_target_identifiers_are_shown_literally():
    app = _hostile_run("Ensembl names")
    report = app.state["result_chr_normalization"]["coord_report"]
    assert dict(report.no_alias_for_target) == {"HLA-A*01:01:01:01": 1,
                                                "chr_[1]": 1}
    assert "HLA-A*01:01:01:01 (1 rows)\nchr_[1] (1 rows)" in [
        c.value for c in _details(app).get("code")]
    _assert_only_in_plain_text(app, HOSTILE)


def test_identifiers_themselves_are_unchanged():
    app = _hostile_run("UCSC names")
    assert app.chrs == ["chr_[1]", "chr_[1]", "foo`bar", "<script>", "a_b"]


def test_long_identifier_lists_are_capped_with_a_count():
    names = [f"u*{i}*" for i in range(25)]
    query = "".join(f"{n}\t0\t5\tq\n" for n in names).encode()
    app = App(query, ANNOT)
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(HOSTILE_MAPPING)
    app.run()
    block = next(c.value for c in _details(app).get("code"))  # query table
    assert block.splitlines() == [f"{n} (1 rows)" for n in names[:20]] + [
        "... and 5 more"]


def test_vcf_contig_conflict_names_the_contigs_literally():
    vcf = (b"##fileformat=VCFv4.2\n"
           b"##contig=<ID=HLA-A*01:01:01:01,length=5>\n"
           b"##contig=<ID=chr_[1],length=6>\n"
           b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
           b"HLA-A*01:01:01:01\t2\tv1\tA\tT\t50\tPASS\t.\n")
    app = App(vcf, ANNOT, qname="q.vcf")
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(HOSTILE_MAPPING)
    app.run()
    assert any("disagree" in e for e in _texts(app, "error"))
    assert ("HLA-A*01:01:01:01, chr_[1] \u2192 chr_[1]\n"
            "conflicting attributes: length") in _texts(app, "code")
    _assert_only_in_plain_text(app, ["HLA-A*01:01:01:01", "chr_[1]"])
    assert not _has(app.at, "download_button", "download_vcf")


# ---- bounded validation messages --------------------------------------------------------

BIG = 5_000_000                       # a multi-megabyte offending value
LIMIT = 4_000                         # generous bound for one rendered issue


def _error(text: str, **kw) -> CustomRegistryError:
    with pytest.raises(CustomRegistryError) as caught:
        load_custom_registry(text.encode(), **kw)
    return caught.value


def _bounded(error):
    assert len(str(error)) < LIMIT * (len(error.issues) + 1)
    for issue in error.issues:
        assert len(describe_issue(issue)) < LIMIT


def test_a_huge_value_with_whitespace_is_previewed_not_echoed():
    value = "s" + "x" * BIG + " "
    error = _error(HEADER + f"c1\t{value}\t\t\t\n")
    (issue,) = error.issues
    assert (issue.code, issue.rows, issue.columns) == (
        "WHITESPACE", (2,), ("ucsc",))
    assert "'sxxxx" in issue.message
    assert f"[truncated, {len(value):,} characters]" in issue.message
    _bounded(error)


def test_a_huge_value_with_a_control_character_is_previewed():
    value = "x" * BIG + "\x85"
    error = _error(HEADER + f"c1\t\t{value}\t\t\n")
    (issue,) = error.issues
    assert (issue.code, issue.rows, issue.columns) == (
        "CONTROL_CHARACTER", (2,), ("ensembl",))
    assert "U+0085" in issue.message and "truncated" in issue.message
    _bounded(error)


def test_a_huge_alias_on_two_rows_is_previewed_and_its_metadata_kept():
    value = "a" * BIG
    error = _error(HEADER + f"c1\t{value}\t\t\t\nc2\t{value}\t\t\t\n")
    (issue,) = error.issues
    assert issue.code == "ALIAS_COLLISION"
    assert issue.rows == (2, 3) and issue.columns == ("ucsc", "ucsc")
    assert issue.alias == value               # metadata intact, not shown
    _bounded(error)


def test_an_alias_repeated_on_every_row_lists_a_bounded_number_of_places():
    rows = 200_000
    text = HEADER + "".join(f"GRCh38\tchr{i}\t\t\t\n" for i in range(rows))
    assert len(text) > 3_000_000
    error = _error(text)
    (issue,) = error.issues
    assert issue.code == "ALIAS_COLLISION" and issue.alias == "GRCh38"
    assert issue.rows == tuple(range(2, rows + 2))      # complete metadata
    line = describe_issue(issue)
    assert line.startswith("line 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ... "
                           f"({rows:,} in total) [assembly]: ALIAS_COLLISION")
    assert f"({rows:,} in total)" in issue.message
    _bounded(error)


def test_the_twenty_issue_cap_and_remaining_count_are_kept():
    text = HEADER + "".join(f"c{i}\tv{i} \t\t\t\n" for i in range(30))
    error = _error(text)
    assert len(error.issues) == 20 and error.more == 10
    assert "... and 10 more problem(s)" in str(error)
    _bounded(error)


def test_a_huge_header_is_previewed():
    error = _error("\t".join(["assembly", "ucsc", "ensembl", "genbank",
                              "refseq", "e" * BIG]) + "\n")
    (issue,) = error.issues
    assert issue.code == "HEADER" and issue.rows == (1,)
    _bounded(error)


def test_short_values_are_shown_in_full():
    error = _error(HEADER + "c1\tchr1 \t\t\t\n")
    assert "'chr1 '" in error.issues[0].message
    assert "truncated" not in str(error)


def test_the_gui_shows_a_bounded_message_for_a_huge_collision():
    rows = 100_000
    data = (HEADER + "".join(f"GRCh38\tchr{i}\t\t\t\n"
                             for i in range(rows))).encode()
    app = App()
    app.source(_CUSTOM_OPTION).naming("UCSC names").mapping(data)
    shown = "\n".join(_texts(app, "code"))
    assert "ALIAS_COLLISION" in shown and "'GRCh38'" in shown
    assert f"({rows:,} in total)" in shown
    assert len(shown) < LIMIT
    assert not app.run().done


# ---- Unicode control characters ---------------------------------------------------------

CC = {cp for cp in range(sys.maxunicode + 1)
      if unicodedata.category(chr(cp)) == "Cc"}


def test_the_control_definition_is_exactly_unicode_cc():
    rejected = {cp for cp in range(sys.maxunicode + 1)
                if custom._control_character(chr(cp)) is not None}
    assert rejected == CC
    assert len(CC) == 65 and 0x85 in CC


@pytest.mark.parametrize("cp", sorted(CC - {0x09, 0x0A}),
                         ids=lambda cp: f"U+{cp:04X}")
def test_every_control_character_inside_a_name_is_rejected(cp):
    error = _error(HEADER + f"c1\tch{chr(cp)}r1\t\t\t\n")
    assert error.codes == ("CONTROL_CHARACTER",)
    assert f"U+{cp:04X}" in error.issues[0].message
    assert error.issues[0].rows == (2,)


def test_tab_and_newline_keep_their_structural_meaning():
    # A tab separates fields and a newline separates rows.
    assert _error(HEADER + "c1\tch\tr1\t\t\t\n").codes == ("FIELD_COUNT",)
    assert len(load_custom_registry((HEADER + "c1\t\t\t\t\nc2\t\t\t\t\n")
                                    .encode())) == 2


def test_c1_controls_at_the_edges_are_controls_not_whitespace():
    # U+0085 is also Unicode whitespace; it is reported as a control.
    assert _error(HEADER + "c1\t\x85chr1\t\t\t\n").codes == (
        "CONTROL_CHARACTER",)


@pytest.mark.parametrize("name", ["chr1\u200b", "chr\u202e1", "chr\ufeff1",
                                  "chr\u200d1"])
def test_format_characters_are_kept_and_matched_exactly(name):
    # Cf characters are not control characters: accepted as written, never
    # stripped or normalized, so the visually similar "chr1" does not match.
    assert unicodedata.category(next(c for c in name if not c.isascii())) \
        == "Cf"
    registry = load_custom_registry((HEADER + f"{name}\tX\t\t\t\n").encode())
    out = normalize_chromosomes_with_registry(
        pd.DataFrame({"chr": [name, "chr1"], "start": [0, 0], "end": [1, 1]}),
        registry=registry, target="ucsc")
    assert out.dataframe["chr"].tolist() == ["X", "chr1"]
    assert dict(out.report.unknown) == {"chr1": 1}


# ---- immutable, shared registries ---------------------------------------------------------

@pytest.mark.parametrize("attribute,value", [
    ("name", "Mouse"), ("assembly_id", "mm10"), ("_index", {}),
    ("_records", {}), ("extra", 1)])
def test_a_cached_registry_cannot_be_reassigned(attribute, value):
    registry = load_registry("hg38")
    with pytest.raises(AttributeError):
        setattr(registry, attribute, value)
    with pytest.raises(AttributeError):
        delattr(registry, "name")
    other = load_registry("GRCh38")              # another caller, another spelling
    assert other is registry
    assert (other.name, other.assembly_id) == ("GRCh38", "GRCh38")
    assert other.resolve("chr1").seq_id == "GRCh38:chr1"


def test_registry_contents_are_read_only():
    registry = load_registry("GRCh38")
    record = registry.record(registry.resolve("chr1").seq_id)
    with pytest.raises(TypeError):
        record.aliases["ucsc"] = "chrZ"
    with pytest.raises(TypeError):
        registry._records["x"] = record
    with pytest.raises(TypeError):
        registry._index["x"] = "y"
    assert load_registry("GRCh38").render(record.seq_id, "ucsc").alias == "chr1"


def test_custom_registries_are_immutable_and_independent():
    data = (HEADER + "c1\tchrA\t\t\t\n").encode()
    first, second = load_custom_registry(data), load_custom_registry(data)
    assert first is not second
    assert isinstance(first, ChromosomeRegistry)
    with pytest.raises(AttributeError):
        first.name = "GRCh38"
    with pytest.raises(AttributeError):
        first.assembly_id = "GRCh38"
    assert first.assembly_id is None and second.name == first.name
