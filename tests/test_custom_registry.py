"""User-supplied chromosome mappings (core/backend only).

A custom TSV becomes an ordinary ``ChromosomeRegistry`` with no assembly
identity; normalization runs the same code as for bundled assemblies. These
tests pin the schema, the structural validation (ambiguity is rejected,
biological syntax is not), exact matching, partial aliases, report identity
and strict mode, equivalence with a bundled registry, resource limits, and
that nothing touches the network or the bundled catalog.
"""

from __future__ import annotations

import io
import socket
import urllib.request

import pandas as pd
import pytest

from streamlit_app.core import (
    normalize_chromosomes,
    normalize_chromosomes_with_registry,
)
from streamlit_app.core.chrom_registry import (
    CUSTOM_HEADER,
    CUSTOM_REGISTRY_NAME,
    NO_ALIAS_FOR_TARGET,
    UNKNOWN,
    ChromosomeRegistry,
    CustomRegistryError,
    SequenceRecord,
    UnsupportedAuthorityError,
    load_catalog,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.chromosome_inputs import (
    StrictInputNormalizationError,
    normalize_input_chromosomes,
)
from streamlit_app.core.chromosome_normalization import (
    ChromosomeNormalizationError,
    StrictChromosomeNormalizationError,
)
from streamlit_app.core.vcf_contigs import reconcile_contig_lines

HEADER = "\t".join(CUSTOM_HEADER)


def tsv(*rows: str, header: str = HEADER, newline: str = "\n") -> bytes:
    return f"{newline.join([header, *rows])}{newline}".encode()


def row(assembly="", ucsc="", ensembl="", genbank="", refseq="") -> str:
    return f"{assembly}\t{ucsc}\t{ensembl}\t{genbank}\t{refseq}"


BASIC = tsv(
    row("1", "chr1", "1", "CM012345.1", "NC_012345.1"),
    row("2", "chr2", "2", "CM012346.1", "NC_012346.1"),
    row("MT", "chrM", "MT", "JX123456.1", "NC_099999.1"),
    row("scaffold_1", "scaffold_1", "", "ABCD01000001.1", "NW_012345678.1"),
)


def codes(data: bytes, **kwargs) -> tuple[str, ...]:
    with pytest.raises(CustomRegistryError) as info:
        load_custom_registry(data, **kwargs)
    return info.value.codes


def frame(chroms, **extra):
    n = len(chroms)
    data = {"chr": chroms, "start": list(range(10, 10 + n)),
            "end": [i + 5 for i in range(10, 10 + n)],
            "strand": ["+"] * n, "name": [f"n{i}" for i in range(n)]}
    data.update(extra)
    return pd.DataFrame(data)


# ---- schema and internal ids ---------------------------------------------------

def test_the_schema_is_exactly_five_columns_in_one_order():
    assert CUSTOM_HEADER == ("assembly", "ucsc", "ensembl", "genbank", "refseq")


def test_basic_mapping_loads_without_a_seq_id_column():
    registry = load_custom_registry(BASIC)
    assert isinstance(registry, ChromosomeRegistry) and len(registry) == 4
    assert registry.assembly_id is None
    assert registry.name == CUSTOM_REGISTRY_NAME
    for authority, alias in (("ucsc", "chr1"), ("ensembl", "1"),
                             ("assembly", "1"), ("genbank", "CM012345.1"),
                             ("refseq", "NC_012345.1")):
        seq_id = registry.resolve(alias).seq_id
        assert registry.render(seq_id, authority).alias == alias


def test_seq_ids_are_deterministic_ordered_unique_and_opaque():
    first, second = load_custom_registry(BASIC), load_custom_registry(BASIC)
    assert list(first) == list(second) == [
        "custom:000001", "custom:000002", "custom:000003", "custom:000004"]
    # row order decides the ids; nothing about the names does
    swapped = tsv(row("2", "chr2"), row("1", "chr1"))
    ids = load_custom_registry(swapped)
    assert ids.resolve("chr2").seq_id == "custom:000001"
    assert ids.resolve("chr1").seq_id == "custom:000002"
    assert all(i.startswith("custom:") for i in ids)


def test_seq_ids_are_unique_and_zero_padded_at_scale():
    rows = [row(ucsc=f"s{i}") for i in range(1, 1201)]
    registry = load_custom_registry(tsv(*rows))
    ids = list(registry)
    assert len(set(ids)) == 1200 and ids[0] == "custom:000001"
    assert ids[-1] == "custom:001200"


def test_header_may_be_followed_by_rows_without_a_final_newline_or_with_crlf():
    assert len(load_custom_registry(
        (HEADER + "\n" + row("1", "chr1")).encode())) == 1
    crlf = tsv(row("1", "chr1"), row("2", "chr2"), newline="\r\n")
    registry = load_custom_registry(crlf)
    assert registry.resolve("chr2").resolved                 # no stray "\r"
    assert not registry.resolve("chr2\r").resolved


def test_a_utf8_byte_order_mark_is_not_part_of_the_header():
    assert len(load_custom_registry(b"\xef\xbb\xbf" + BASIC)) == 4


# ---- structural validation: what is rejected -------------------------------------

@pytest.mark.parametrize("data,expected", [
    (b"", "EMPTY_FILE"),
    (b"\n\n", "EMPTY_FILE"),
    (b"1\tchr1\t1\tCM1.1\tNC_1.1\n", "HEADER"),                       # no header
    (tsv(row("1", "chr1"), header="assembly\tucsc\tensembl\tgenbank"),
     "HEADER"),                                                    # missing col
    (tsv(row("1", "chr1"), header=HEADER + "\tsource"), "HEADER"),  # extra col
    (tsv(row("1", "chr1"),
         header="assembly\tucsc\tucsc\tgenbank\trefseq"), "HEADER"),  # dup col
    (tsv(row("1", "chr1"),
         header="ucsc\tassembly\tensembl\tgenbank\trefseq"), "HEADER"),  # order
    (tsv(row("1", "chr1"), header="seq_id\t" + HEADER), "HEADER"),
    (tsv(), "NO_DATA"),
    (tsv("1\tchr1\t1\tCM1.1"), "FIELD_COUNT"),                       # too few
    (tsv(row("1", "chr1") + "\textra"), "FIELD_COUNT"),             # too many
    (tsv(row("1", "chr1"), "", row("2", "chr2")), "EMPTY_ROW"),
    (tsv(row("1", "chr1"), "\t\t\t\t"), "NO_ALIAS"),
    (tsv(row()), "NO_ALIAS"),
    (tsv("# a comment", row("1", "chr1")), "COMMENT"),
])
def test_structurally_invalid_files_are_rejected_with_a_code(data, expected):
    assert expected in codes(data)


def test_invalid_utf8_is_rejected_clearly():
    assert codes(HEADER.encode() + b"\n\xff\xfe\tchr1\t\t\t\n") == ("ENCODING",)


@pytest.mark.parametrize("cell", [" chr1", "chr1 ", " ", "x "])
def test_leading_or_trailing_whitespace_is_rejected_not_trimmed(cell):
    assert "WHITESPACE" in codes(tsv(row(ucsc=cell)))


@pytest.mark.parametrize("cell", ["chr\x001", "chr\x0b1", "ch\rr1", "chr1\x7f"])
def test_control_characters_are_rejected(cell):
    assert "CONTROL_CHARACTER" in codes(tsv(row(ucsc=cell)))


def test_embedded_tabs_split_fields_and_are_a_field_count_error():
    assert codes(tsv(row("1", "chr\t1"))) == ("FIELD_COUNT",)


def test_comment_lines_are_not_supported_to_keep_the_format_plain():
    assert codes(tsv(row("1", "chr1"), "# note")) == ("COMMENT",)


def test_errors_list_every_problem_with_line_numbers_and_cap_the_report():
    data = tsv(*(["1\tx"] * 30))                  # 30 bad rows (2 fields)
    with pytest.raises(CustomRegistryError) as info:
        load_custom_registry(data)
    err = info.value
    assert len(err.issues) == 20 and err.more == 10
    assert err.issues[0].rows == (2,) and err.issues[19].rows == (21,)
    assert "10 more" in str(err)


# ---- ambiguity: collisions and duplicates -----------------------------------------

def test_an_alias_on_two_rows_is_rejected_with_rows_and_columns():
    data = tsv(row(ucsc="chr1"), row(ensembl="chr1"))
    with pytest.raises(CustomRegistryError) as info:
        load_custom_registry(data)
    (issue,) = info.value.issues
    assert issue.code == "ALIAS_COLLISION" and issue.alias == "chr1"
    assert issue.rows == (2, 3) and issue.columns == ("ucsc", "ensembl")
    assert "line 2 ucsc" in issue.message and "line 3 ensembl" in issue.message


def test_the_same_alias_in_several_columns_of_one_row_is_valid():
    registry = load_custom_registry(tsv(row("1", "chr1", "1")))
    seq_id = registry.resolve("1").seq_id
    assert registry.resolve("chr1").seq_id == seq_id
    assert registry.render(seq_id, "assembly").alias == "1"
    assert registry.render(seq_id, "ensembl").alias == "1"


def test_identical_rows_are_rejected_not_merged():
    data = tsv(row("1", "chr1"), row("2", "chr2"), row("1", "chr1"))
    with pytest.raises(CustomRegistryError) as info:
        load_custom_registry(data)
    (issue,) = info.value.issues                  # one issue, not also a clash
    assert issue.code == "DUPLICATE_ROW" and issue.rows == (2, 4)


def test_rows_that_overlap_partially_are_a_collision_not_a_duplicate():
    data = tsv(row("1", "chr1"), row("1", "chrX"))
    assert codes(data) == ("ALIAS_COLLISION",)


# ---- exact, case-sensitive matching -------------------------------------------------

def test_matching_is_exact_and_case_sensitive():
    registry = load_custom_registry(tsv(
        row(ucsc="chr1"), row(ucsc="Chr1"), row(ucsc="CHR1")))
    assert len({registry.resolve(x).seq_id for x in ("chr1", "Chr1", "CHR1")}
               ) == 3
    assert not registry.resolve("cHr1").resolved
    assert not registry.resolve(" chr1").resolved
    assert not registry.resolve("chr1 ").resolved


def test_explicit_case_variants_in_one_row_are_aliases_of_one_sequence():
    registry = load_custom_registry(tsv(row("Chr1", "chr1", "CHR1")))
    assert len({registry.resolve(x).seq_id for x in ("Chr1", "chr1", "CHR1")}
               ) == 1


def test_interior_spaces_and_unusual_characters_are_allowed():
    registry = load_custom_registry(tsv(row(ucsc="contig 7"),
                                        row(ucsc="chr-1|a:b")))
    assert registry.resolve("contig 7").resolved
    assert registry.resolve("chr-1|a:b").resolved


# ---- non-model identifiers (no syntax rules) ----------------------------------------

NON_MODEL = tsv(
    row("LG01", "LG01", "", "", ""),
    row("sex_chr_Z", "chrZ", "Z", "", ""),
    row("mitochondrial_contig", "mito", "MtDNA", "", ""),
    row("scaffold-alpha", "", "", "ZZZZ01000007.1", ""),
)


def test_non_standard_identifiers_work_when_present_in_the_mapping():
    registry = load_custom_registry(NON_MODEL)
    res = normalize_chromosomes_with_registry(
        frame(["LG01", "Z", "mito", "scaffold-alpha", "ZZZZ01000007.1"]),
        registry=registry, target="ucsc")
    assert res.dataframe["chr"].tolist() == [
        "LG01", "chrZ", "mito", "scaffold-alpha", "ZZZZ01000007.1"]
    assert dict(res.report.no_alias_for_target) == {
        "scaffold-alpha": 1, "ZZZZ01000007.1": 1}        # recognized, no ucsc


def test_no_accession_or_naming_syntax_is_enforced():
    registry = load_custom_registry(tsv(
        row("1", "weird name!", "x", "not-an-accession", "NC_1")))
    seq_id = registry.resolve("not-an-accession").seq_id
    assert registry.render(seq_id, "refseq").alias == "NC_1"   # no shape rule


# ---- partial aliases / empty cells ------------------------------------------------------

def test_empty_cells_mean_no_alias_and_give_no_alias_for_target():
    registry = load_custom_registry(tsv(row("scaffold_1", "scaffold_1")))
    seq_id = registry.resolve("scaffold_1").seq_id
    for target in ("ensembl", "genbank", "refseq"):
        result = registry.render(seq_id, target)
        assert not result.rendered and result.reason == NO_ALIAS_FOR_TARGET
    assert registry.record(seq_id).aliases == {
        "ucsc": "scaffold_1", "assembly": "scaffold_1"}
    res = normalize_chromosomes_with_registry(
        frame(["scaffold_1"]), registry=registry, target="ensembl")
    assert res.dataframe["chr"].tolist() == ["scaffold_1"]        # kept
    assert dict(res.report.no_alias_for_target) == {"scaffold_1": 1}
    assert not res.report.unknown and not res.report.complete


@pytest.mark.parametrize("column", CUSTOM_HEADER)
def test_a_row_with_a_single_alias_in_any_one_authority_resolves(column):
    registry = load_custom_registry(tsv(row(**{column: "only-name"})))
    result = registry.resolve("only-name")
    assert result.resolved
    assert registry.render(result.seq_id, column).alias == "only-name"
    others = [a for a in CUSTOM_HEADER if a != column]
    assert all(not registry.render(result.seq_id, a).rendered for a in others)


def test_unknown_is_distinct_from_no_alias_for_target():
    registry = load_custom_registry(BASIC)
    assert registry.resolve("nope").reason == UNKNOWN
    seq_id = registry.resolve("scaffold_1").seq_id
    assert registry.render(seq_id, "ensembl").reason == NO_ALIAS_FOR_TARGET
    with pytest.raises(UnsupportedAuthorityError):
        registry.render(seq_id, "bogus")


# ---- runtime registry abstraction ---------------------------------------------------------

def test_custom_and_bundled_share_one_registry_type_and_api():
    custom, bundled = load_custom_registry(BASIC), load_registry("GRCh38")
    assert type(custom) is type(bundled) is ChromosomeRegistry
    for name in ("resolve", "render", "record", "__len__", "__iter__",
                 "__contains__"):
        assert callable(getattr(custom, name))
    seq_id = custom.resolve("chr1").seq_id
    assert isinstance(custom.record(seq_id), SequenceRecord)
    assert seq_id in custom and "custom:999999" not in custom


def test_custom_registry_records_are_immutable():
    registry = load_custom_registry(BASIC)
    record = registry.record("custom:000001")
    with pytest.raises(AttributeError):
        record.seq_id = "other"
    with pytest.raises(TypeError):
        record.aliases["ucsc"] = "x"
    with pytest.raises(TypeError):
        registry._records["custom:000009"] = record
    with pytest.raises(TypeError):
        registry._index["x"] = "custom:000001"
    assert registry.resolve("chr1").seq_id == "custom:000001"


def test_a_registry_without_assembly_needs_a_display_name():
    with pytest.raises(Exception, match="display name"):
        ChromosomeRegistry(None, {})


# ---- dataframe normalization and reports -------------------------------------------------

def test_custom_normalization_rewrites_only_the_chromosome_column():
    registry = load_custom_registry(BASIC)
    df = frame(["NC_012345.1", "chr2", "MT", "unseen", "1"])
    res = normalize_chromosomes_with_registry(
        df, registry=registry, target="ucsc")
    assert res.dataframe["chr"].tolist() == [
        "chr1", "chr2", "chrM", "unseen", "chr1"]
    pd.testing.assert_frame_equal(df.drop(columns="chr"),
                                  res.dataframe.drop(columns="chr"))
    assert df["chr"].tolist()[0] == "NC_012345.1"            # input untouched
    assert dict(res.report.unknown) == {"unseen": 1}
    assert dict(res.report.renames) == {"NC_012345.1": "chr1", "MT": "chrM",
                                        "1": "chr1"}
    assert res.report.collapses == {"chr1": ("NC_012345.1", "1")}


def test_report_identity_does_not_pretend_to_be_an_assembly():
    custom = normalize_chromosomes_with_registry(
        frame(["chr1"]), registry=load_custom_registry(BASIC), target="ensembl")
    assert custom.report.assembly is None
    assert custom.report.registry_name == CUSTOM_REGISTRY_NAME
    bundled = normalize_chromosomes(frame(["chr1"]), assembly="GRCh38",
                                    target="ensembl")
    assert bundled.report.assembly == "GRCh38"
    assert bundled.report.registry_name == "GRCh38"


def test_strict_mode_raises_with_the_custom_report_and_name():
    registry = load_custom_registry(BASIC)
    with pytest.raises(StrictChromosomeNormalizationError) as info:
        normalize_chromosomes_with_registry(
            frame(["chr1", "ghost", "scaffold_1"]), registry=registry,
            target="ensembl", strict=True)
    report = info.value.report
    assert dict(report.unknown) == {"ghost": 1}
    assert dict(report.no_alias_for_target) == {"scaffold_1": 1}
    assert CUSTOM_REGISTRY_NAME in str(info.value)
    complete = normalize_chromosomes_with_registry(
        frame(["chr1", "MT"]), registry=registry, target="ucsc", strict=True)
    assert complete.report.complete


def test_registry_argument_is_validated():
    with pytest.raises(ChromosomeNormalizationError, match="ChromosomeRegistry"):
        normalize_chromosomes_with_registry(
            frame(["chr1"]), registry="GRCh38", target="ucsc")
    with pytest.raises(UnsupportedAuthorityError):
        normalize_chromosomes_with_registry(
            frame(["chr1"]), registry=load_custom_registry(BASIC),
            target="nope")


def test_categorical_and_string_columns_keep_their_dtype():
    registry = load_custom_registry(BASIC)
    df = frame(["chr1", "chr2", "chr1"])
    df["chr"] = df["chr"].astype("category")
    res = normalize_chromosomes_with_registry(
        df, registry=registry, target="ensembl")
    assert isinstance(res.dataframe["chr"].dtype, pd.CategoricalDtype)
    assert res.dataframe["chr"].astype(str).tolist() == ["1", "2", "1"]


# ---- dual-table orchestration --------------------------------------------------------------

def test_input_orchestration_accepts_a_registry_and_keeps_both_reports():
    registry = load_custom_registry(BASIC)
    out = normalize_input_chromosomes(
        frame(["1", "chr1", "weird"]), frame(["NC_012345.1", "MT"]),
        registry=registry, target="ucsc")
    assert out.assembly is None and out.registry_name == CUSTOM_REGISTRY_NAME
    assert out.coord_df["chr"].tolist() == ["chr1", "chr1", "weird"]
    assert out.annot_df["chr"].tolist() == ["chr1", "chrM"]
    assert dict(out.coord_renames) == {"1": "chr1"}
    assert out.coord_collapses == {"chr1": ("1", "chr1")}
    assert dict(out.annot_renames) == {"NC_012345.1": "chr1", "MT": "chrM"}
    assert not out.complete                     # 'weird' is unresolved
    with pytest.raises(StrictInputNormalizationError):
        normalize_input_chromosomes(
            frame(["weird"]), frame(["chr1"]), registry=registry,
            target="ucsc", strict=True)


def test_input_orchestration_needs_exactly_one_of_assembly_or_registry():
    registry = load_custom_registry(BASIC)
    with pytest.raises(ChromosomeNormalizationError, match="exactly one"):
        normalize_input_chromosomes(frame(["a"]), frame(["a"]),
                                    target="ucsc")
    with pytest.raises(ChromosomeNormalizationError, match="exactly one"):
        normalize_input_chromosomes(frame(["a"]), frame(["a"]),
                                    assembly="GRCh38", registry=registry,
                                    target="ucsc")


def test_bundled_input_orchestration_is_unchanged():
    out = normalize_input_chromosomes(
        frame(["1"]), frame(["NC_000001.11"]), assembly="GRCh38",
        target="ucsc")
    assert out.assembly == "GRCh38" and out.registry_name == "GRCh38"
    assert out.coord_df["chr"].tolist() == out.annot_df["chr"].tolist() == [
        "chr1"]


# ---- equivalence with a bundled registry ----------------------------------------------------

SUBSET = ["chr1", "chr2", "chrM", "chr1_KI270706v1_random",
          "chr1_KI270762v1_alt", "chrUn_KI270302v1"]


def _custom_from_bundled(assembly="GRCh38", handles=SUBSET):
    bundled = load_registry(assembly)
    rows = []
    for handle in handles:
        aliases = bundled.record(bundled.resolve(handle).seq_id).aliases
        rows.append(row(*(aliases.get(c, "") for c in CUSTOM_HEADER)))
    return bundled, load_custom_registry(tsv(*rows))


def _probe_identifiers(bundled):
    probes = []
    for handle in SUBSET:
        probes += list(bundled.record(
            bundled.resolve(handle).seq_id).aliases.values())
    return sorted(set(probes)) + ["not-a-chromosome", "chr1 ", "CHR1"]


def test_equivalent_custom_registry_resolves_and_renders_like_the_bundled_one():
    bundled, custom = _custom_from_bundled()
    for identifier in _probe_identifiers(bundled):
        b, c = bundled.resolve(identifier), custom.resolve(identifier)
        assert b.resolved == c.resolved, identifier
        if not b.resolved:
            assert c.reason == b.reason == UNKNOWN
            continue
        for authority in CUSTOM_HEADER:
            rb = bundled.render(b.seq_id, authority)
            rc = custom.render(c.seq_id, authority)
            assert (rb.alias, rb.reason) == (rc.alias, rc.reason), (
                identifier, authority)


@pytest.mark.parametrize("target", CUSTOM_HEADER)
def test_equivalent_custom_registry_normalizes_identically(target):
    bundled, custom = _custom_from_bundled()
    ids = _probe_identifiers(bundled) * 2        # duplicates -> row counts
    df = frame(ids)
    b = normalize_chromosomes(df, assembly="GRCh38", target=target)
    c = normalize_chromosomes_with_registry(df, registry=custom, target=target)
    pd.testing.assert_frame_equal(b.dataframe, c.dataframe)
    for field in ("renames", "unknown", "no_alias_for_target", "collapses"):
        assert dict(getattr(b.report, field)) == dict(
            getattr(c.report, field)), field
    for field in ("total_rows", "unique_identifiers", "changed_rows",
                  "resolved_changed_identifiers",
                  "resolved_unchanged_identifiers"):
        assert getattr(b.report, field) == getattr(c.report, field), field
    assert b.report.complete == c.report.complete


def test_equivalent_registries_agree_on_unknown_no_alias_and_collapse():
    _, custom = _custom_from_bundled()
    df = frame(["1", "chr1", "chr1_KI270762v1_alt", "zzz", "HSCHR1_1_CTG3"])
    b = normalize_chromosomes(df, assembly="GRCh38", target="ensembl")
    c = normalize_chromosomes_with_registry(df, registry=custom,
                                            target="ensembl")
    assert dict(b.report.unknown) == dict(c.report.unknown) == {"zzz": 1}
    assert dict(b.report.no_alias_for_target) == dict(
        c.report.no_alias_for_target) == {"chr1_KI270762v1_alt": 1,
                                          "HSCHR1_1_CTG3": 1}
    assert b.report.collapses == c.report.collapses == {"1": ("1", "chr1")}


def test_equivalent_registries_give_identical_vcf_contig_inputs():
    _, custom = _custom_from_bundled()
    query = frame(["1", "chr1", "MT", "chrUn_KI270302v1"])
    annot = frame(["chr1", "chrM"])
    b = normalize_input_chromosomes(query, annot, assembly="GRCh38",
                                    target="ucsc")
    c = normalize_input_chromosomes(query, annot, registry=custom,
                                    target="ucsc")
    assert dict(b.coord_renames) == dict(c.coord_renames)
    assert b.coord_collapses == c.coord_collapses
    header = ["##contig=<ID=1,length=248956422>",
              "##contig=<ID=chr1,length=248956422>",
              "##contig=<ID=MT,length=16569>",
              "##contig=<ID=chrUn_KI270302v1,length=2274>"]
    assert reconcile_contig_lines(header, c.coord_renames) == \
        reconcile_contig_lines(header, b.coord_renames)
    assert reconcile_contig_lines(header, c.coord_renames) == [
        "##contig=<ID=chr1,length=248956422>",
        "##contig=<ID=chrM,length=16569>",
        "##contig=<ID=chrUn_KI270302v1,length=2274>"]


def test_a_registry_with_a_different_subset_differs_as_expected():
    _, custom = _custom_from_bundled(handles=["chr1", "chrM"])
    assert load_registry("GRCh38").resolve("chr2").resolved
    assert not custom.resolve("chr2").resolved


# ---- offline, isolated, limited ---------------------------------------------------------------

def test_loading_and_normalizing_a_custom_mapping_uses_no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    registry = load_custom_registry(BASIC)
    res = normalize_chromosomes_with_registry(
        frame(["1", "x"]), registry=registry, target="ucsc")
    assert res.dataframe["chr"].tolist() == ["chr1", "x"]


def test_custom_registries_do_not_touch_the_bundled_catalog_or_cache():
    catalog = load_catalog()
    load_registry.cache_clear()
    registry = load_custom_registry(BASIC)
    normalize_chromosomes_with_registry(frame(["1"]), registry=registry,
                                        target="ucsc")
    assert load_registry.cache_info().currsize == 0       # nothing cached
    assert load_catalog() is catalog and len(catalog) == 64
    assert load_custom_registry(BASIC) is not registry    # no global cache


def test_file_like_inputs_are_accepted_without_framework_types():
    assert len(load_custom_registry(io.BytesIO(BASIC))) == 4
    assert len(load_custom_registry(io.StringIO(BASIC.decode()))) == 4
    assert len(load_custom_registry(bytearray(BASIC))) == 4
    with pytest.raises(TypeError, match="bytes or a file object"):
        load_custom_registry(BASIC.decode())                 # ambiguous str
    with pytest.raises(TypeError):
        load_custom_registry(42)


def test_size_limit_is_checked_before_parsing_and_is_configurable():
    assert codes(BASIC, max_bytes=len(BASIC) - 1) == ("TOO_LARGE",)
    assert len(load_custom_registry(BASIC, max_bytes=len(BASIC))) == 4

    class Counting(io.BytesIO):
        asked = None

        def read(self, size=-1):
            Counting.asked = size
            return super().read(size)
    assert codes(Counting(b"x" * 5000), max_bytes=1000) == ("TOO_LARGE",)
    assert Counting.asked == 1001                  # never reads the whole file


def test_row_limit_is_configurable_and_counts_data_rows_only():
    data = tsv(*[row(ucsc=f"s{i}") for i in range(5)])
    assert len(load_custom_registry(data, max_rows=5)) == 5
    assert codes(data, max_rows=4) == ("TOO_MANY_ROWS",)


def test_the_default_limits_cover_real_assemblies_and_are_overridable():
    from streamlit_app.core.chrom_registry import custom
    assert custom.DEFAULT_MAX_ROWS >= 500_000      # > 99% of catalog genomes
    # ~100 bytes per row at the row limit fits, and stays under Streamlit's
    # default 200 MB per-file upload limit
    assert custom.DEFAULT_MAX_ROWS * 100 <= custom.DEFAULT_MAX_BYTES
    assert custom.DEFAULT_MAX_BYTES < 200 * 1000 * 1000
