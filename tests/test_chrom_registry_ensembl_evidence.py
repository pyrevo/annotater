"""hg19 Ensembl aliases from pinned, release-specific Ensembl evidence.

An Ensembl alias is added only when an exact versioned accession ties a
top-level Ensembl region to one hg19 record (SPEC 5.1). Offline only.
"""

from __future__ import annotations

import copy
import csv
import gzip

import pytest

from streamlit_app.core.chrom_registry import builder, load_registry
from streamlit_app.core.chrom_registry import ensembl_evidence as ev
from streamlit_app.core.chrom_registry.builder import RegistryBuildError

EVIDENCE_FILE = builder.PACKAGE_DIR / "upstream" / "hg19.ensembl-evidence.tsv"


@pytest.fixture(scope="module")
def entry():
    return builder.get_assembly(builder.load_sources(), "hg19")


@pytest.fixture(scope="module")
def evidence():
    return ev.parse_evidence(EVIDENCE_FILE.read_text())


@pytest.fixture(scope="module")
def hg19():
    return load_registry("hg19")


def gz(rows):
    return gzip.compress(
        ("".join("\t".join(r) + "\n" for r in rows)).encode(), mtime=0)


def tables(**override):
    base = {
        "attrib_type.txt.gz": gz([["6", "toplevel", "Top Level", "d"],
                                  ["9", "other", "x", "d"]]),
        "coord_system.txt.gz": gz([["2", "1", "chromosome", "GRCh37", "1", "d"],
                                   ["3", "1", "supercontig", "GRCh37", "2", "d"],
                                   ["4", "1", "chromosome", "NCBI36", "5", "d"]]),
        "external_db.txt.gz": gz([["50710", "INSDC"], ["1830", "RefSeq_genomic"],
                                  ["11000", "UCSC"], ["7", "Other"]]),
        "seq_region.txt.gz": gz([["10", "1", "2", "1000"],
                                 ["11", "GL1.1", "3", "50"],
                                 ["12", "PATCH1", "3", "40"],
                                 ["13", "old", "4", "30"]]),
        "seq_region_attrib.txt.gz": gz([["10", "6", "1"], ["11", "6", "1"]]),
        "seq_region_synonym.txt.gz": gz([
            ["1", "10", "CM1.1", "50710"], ["2", "10", "NC_1.1", "1830"],
            ["3", "10", "chr1", "11000"], ["4", "11", "NT_1.1", "1830"],
            ["5", "12", "GL9.1", "50710"], ["6", "12", "NT_9.1", "1830"],
            ["7", "13", "NC_old.1", "1830"]]),
    }
    base.update(override)
    return base


def alias_rows():
    return [("1", "chr1", "assembly"), ("CM1.1", "chr1", "genbank"),
            ("NC_1.1", "chr1", "refseq"),
            ("HSCHRUN_1", "chrUn_1", "assembly"),
            ("GL1.1", "chrUn_1", "genbank"), ("NT_1.1", "chrUn_1", "refseq")]


def ev_row(name, insdc="", refseq="", ucsc="", toplevel="1"):
    return {"ensembl_name": name, "coord_system": "chromosome",
            "length": "1", "toplevel": toplevel, "insdc": insdc,
            "refseq": refseq, "ucsc": ucsc}


# --- pinned evidence resource ------------------------------------------------

def test_evidence_is_pinned_and_release_specific(entry):
    cfg = entry["ensembl_evidence"]
    assert builder.sha256_hex(EVIDENCE_FILE.read_bytes()) == \
        cfg["evidence_sha256"]
    assert cfg["source_url"] == (
        "https://ftp.ensembl.org/pub/grch37/release-116/mysql/"
        "homo_sapiens_core_116_37/")
    assert (cfg["ensembl_release"], cfg["ensembl_assembly"],
            cfg["assembly_accession"], cfg["coord_system_version"]) == (
        116, "GRCh37.p13", "GCA_000001405.14", "GRCh37")
    assert set(cfg["tables"]) == set(ev.TABLES)
    assert all(len(v) == 64 for v in cfg["tables"].values())
    assert cfg["match_rule"] and cfg["retrieved"]


def test_modified_evidence_fails_checksum(entry, tmp_path):
    for rel in (entry["upstream_file"],
                entry["ensembl_evidence"]["evidence_file"]):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((builder.PACKAGE_DIR / rel).read_bytes())
    builder.build_from_entry(entry, tmp_path)
    target = tmp_path / entry["ensembl_evidence"]["evidence_file"]
    target.write_text(target.read_text().replace("NC_000001.10", "NC_000001.11"))
    with pytest.raises(RegistryBuildError, match="evidence SHA-256"):
        builder.build_from_entry(entry, tmp_path)


def test_evidence_parses_and_has_expected_shape(evidence):
    assert len(evidence) == 297
    assert sum(r["toplevel"] == "1" for r in evidence) == 84
    assert all(r["insdc"] or r["refseq"] for r in evidence)
    by_name = {r["ensembl_name"]: r for r in evidence}
    assert by_name["1"]["refseq"] == "NC_000001.10"
    assert by_name["MT"]["refseq"] == "NC_012920.1"
    assert by_name["MT"]["insdc"] == ""  # Ensembl has no INSDC for MT
    assert by_name["MT"]["ucsc"] == "chrM"  # Ensembl's own UCSC synonym
    assert by_name["HSCHR17_1_CTG5"]["toplevel"] == "0"


# --- extraction from raw tables (synthetic) ----------------------------------

def test_extraction_selects_version_flags_toplevel_and_is_sorted():
    text = ev.extract_evidence(tables(), "GRCh37")
    assert text == ev.extract_evidence(tables(), "GRCh37")
    lines = [line.split("\t") for line in text.splitlines()]
    assert lines[0] == list(ev.EVIDENCE_HEADER)
    assert lines[1:] == [
        ["1", "chromosome", "1000", "1", "CM1.1", "NC_1.1", "chr1"],
        ["GL1.1", "supercontig", "50", "1", "", "NT_1.1", ""],
        ["PATCH1", "supercontig", "40", "0", "GL9.1", "NT_9.1", ""],
    ]  # NCBI36 region excluded by coordinate-system version


def test_extraction_ignores_synonyms_without_an_external_database():
    syn = gz([["1", "10", "CM1.1", "50710"], ["2", "10", "NC_1.1", "1830"],
              ["3", "10", "scaffold_1", "\\N"]])
    text = ev.extract_evidence(tables(**{"seq_region_synonym.txt.gz": syn}),
                               "GRCh37")
    assert text.splitlines()[1].split("\t") == [
        "1", "chromosome", "1000", "1", "CM1.1", "NC_1.1", ""]
    assert "scaffold_1" not in text


def test_extraction_rejects_unexpected_or_repeated_synonyms():
    extra = gz([["1", "10", "CM1.1", "7"]])
    with pytest.raises(RegistryBuildError, match="unexpected synonym source"):
        ev.extract_evidence(tables(**{"seq_region_synonym.txt.gz": extra}),
                            "GRCh37")
    twice = gz([["1", "10", "A", "1830"], ["2", "10", "B", "1830"]])
    with pytest.raises(RegistryBuildError, match="several refseq"):
        ev.extract_evidence(tables(**{"seq_region_synonym.txt.gz": twice}),
                            "GRCh37")
    with pytest.raises(RegistryBuildError, match="cannot read"):
        ev.extract_evidence(tables(**{"seq_region.txt.gz": b"junk"}), "GRCh37")


def test_raw_table_checksums_must_match_pin(entry):
    cfg = entry["ensembl_evidence"]
    with pytest.raises(RegistryBuildError, match="does not match pinned"):
        ev.verify_tables(tables(), cfg)
    with pytest.raises(RegistryBuildError, match="missing Ensembl table"):
        ev.verify_tables({}, cfg)


@pytest.mark.parametrize("mutate,match", [
    (lambda t: t.replace("toplevel\t", "toplevel_x\t", 1), "header"),
    (lambda t: t.rstrip("\n"), "final newline"),
    (lambda t: t + "1\tchromosome\t1\t1\tX\tY\tz\n", "duplicate"),
    (lambda t: t.replace("\t1\tCM000663.1", "\t2\tCM000663.1", 1), "invalid"),
    (lambda t: t + "Q\tchromosome\t1\t1\t\t\t\n", "no accession"),
])
def test_evidence_parser_rejects_malformed(mutate, match):
    with pytest.raises(RegistryBuildError, match=match):
        ev.parse_evidence(mutate(EVIDENCE_FILE.read_text()))


# --- exact-accession matching (synthetic) ------------------------------------

def test_match_adds_alias_by_exact_accession_only():
    out = ev.match_evidence(alias_rows(), [
        ev_row("1", "CM1.1", "NC_1.1", "chr1"),
        ev_row("GL1.1", "", "NT_1.1")])
    assert out == [("1", "chr1", "ensembl"), ("GL1.1", "chrUn_1", "ensembl")]


@pytest.mark.parametrize("refseq", ["NC_1.2", "NC_1", "NC_1.1 ", "nc_1.1"])
def test_versioned_accessions_are_exact(refseq):
    with pytest.raises(RegistryBuildError, match="matches 0 registry"):
        ev.match_evidence(alias_rows(), [ev_row("1", refseq=refseq)])


def test_name_resemblance_never_matches():
    # Ensembl "1" with an unknown accession must not attach to chr1/"1".
    with pytest.raises(RegistryBuildError, match="matches 0"):
        ev.match_evidence(alias_rows(), [ev_row("1", "CMX.1", "NCX.1")])


def test_accession_contradicting_the_record_fails():
    with pytest.raises(RegistryBuildError, match="contradicts"):
        ev.match_evidence(alias_rows(), [ev_row("1", "CM_other.1", "NC_1.1")])


def test_ambiguous_or_duplicate_matches_fail():
    rows = alias_rows() + [("NC_1.1", "chr1b", "refseq")]
    with pytest.raises(RegistryBuildError, match="matches 2"):
        ev.match_evidence(rows, [ev_row("1", refseq="NC_1.1")])
    with pytest.raises(RegistryBuildError, match="matched by Ensembl regions"):
        ev.match_evidence(alias_rows(), [ev_row("1", "CM1.1", "NC_1.1"),
                                         ev_row("1b", "CM1.1")])


def test_non_toplevel_regions_are_ignored():
    assert ev.match_evidence(alias_rows(),
                             [ev_row("PATCH", "GL9.1", toplevel="0")]) == []


def test_explicit_upstream_ensembl_alias_is_never_overwritten():
    rows = alias_rows() + [("E1", "chr1", "ensembl")]
    with pytest.raises(RegistryBuildError, match="explicit upstream ensembl"):
        ev.match_evidence(rows, [ev_row("1", "CM1.1", "NC_1.1")])


def test_ucsc_name_disagreement_needs_explicit_acknowledgement():
    row = ev_row("1", "CM1.1", "NC_1.1", ucsc="chrOther")
    with pytest.raises(RegistryBuildError, match="acknowledge explicitly"):
        ev.match_evidence(alias_rows(), [row])
    ack = [{"ensembl_name": "1", "evidence_ucsc": "chrOther",
            "registry_ucsc": "chr1", "rationale": "reviewed"}]
    assert ev.match_evidence(alias_rows(), [row], ack) == [
        ("1", "chr1", "ensembl")]
    with pytest.raises(RegistryBuildError, match="stale"):
        ev.match_evidence(alias_rows(), [ev_row("1", "CM1.1", "NC_1.1")], ack)
    with pytest.raises(RegistryBuildError, match="incomplete"):
        ev.match_evidence(alias_rows(), [row], [{**ack[0], "rationale": ""}])


def real_shaped_rows():
    return [("1", "chr1", "assembly"), ("CM000001.1", "chr1", "genbank"),
            ("NC_000001.1", "chr1", "refseq"),
            ("HSCHRUN_1", "chrUn_1", "assembly"),
            ("GL000001.1", "chrUn_1", "genbank"),
            ("NT_000001.1", "chrUn_1", "refseq")]


def test_enriched_alias_cannot_collide_with_another_record():
    rows = real_shaped_rows() + [("E-clash", "chrZ", "assembly"),
                                 ("CM000009.1", "chrZ", "genbank")]
    with pytest.raises(RegistryBuildError, match="resolves to both"):
        builder.build_registry(  # chr1 would receive chrZ's alias
            rows, "T", (), [ev_row("E-clash", "CM000001.1")], {})


def test_enrichment_is_deterministic_and_order_independent():
    evid = [ev_row("1", "CM000001.1", "NC_000001.1"),
            ev_row("GL000001.1", "", "NT_000001.1")]
    a = builder.build_registry(real_shaped_rows(), "T", (), evid, {})
    b = builder.build_registry(list(reversed(real_shaped_rows())), "T", (),
                               list(reversed(evid)), {})
    assert a == b
    assert ("T:chr1\tchr1\t1\t1\tCM000001.1\tNC_000001.1"
            in a.splitlines())


# --- real hg19 results ---------------------------------------------------------

def _registry_rows(entry):
    path = builder.PACKAGE_DIR / entry["registry_file"]
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_exactly_84_hg19_records_gain_verified_ensembl_aliases(entry):
    rows = [r for r in _registry_rows(entry) if r["ensembl"]]
    assert len(rows) == 84
    chroms = [r for r in rows if r["ucsc"] in
              {f"chr{n}" for n in [*range(1, 23), "X", "Y"]}]
    assert len(chroms) == 24
    assert all(r["ensembl"] == r["assembly"] for r in chroms)
    unplaced = [r for r in rows if r["ucsc"].startswith(("chrUn_", ))
                or r["ucsc"].endswith("_random")]
    assert len(unplaced) == 59
    assert len(rows) == len(chroms) + len(unplaced) + 1  # + chrMT


def test_every_added_alias_traces_to_exact_toplevel_evidence(entry, evidence):
    by_name = {r["ensembl_name"]: r for r in evidence}
    for rec in _registry_rows(entry):
        if not rec["ensembl"]:
            continue
        row = by_name[rec["ensembl"]]
        assert row["toplevel"] == "1"
        assert (row["insdc"] and row["insdc"] == rec["genbank"]) or \
            (row["refseq"] and row["refseq"] == rec["refseq"])
        for column, field in (("insdc", "genbank"), ("refseq", "refseq")):
            assert not row[column] or row[column] == rec[field]


def test_no_blanket_assembly_to_ensembl_rule(entry):
    rows = _registry_rows(entry)
    # Assembly aliases that are NOT Ensembl names: unplaced/random contigs
    # whose Ensembl name is the GenBank-style name instead.
    differing = [r for r in rows if r["ensembl"] and r["assembly"]
                 and r["ensembl"] != r["assembly"]]
    assert len(differing) == 59
    # Records with an assembly alias but no Ensembl evidence stay empty.
    assert sum(1 for r in rows if r["assembly"] and not r["ensembl"]) == 213


def test_regions_ensembl_does_not_list_as_toplevel_stay_empty(
        entry, evidence):
    names = {r["ensembl_name"] for r in evidence if r["toplevel"] == "0"}
    assert len(names) == 213
    assert not any(r["ensembl"] in names for r in _registry_rows(entry))


def test_chrM_has_no_ensembl_evidence_and_chrMT_does(entry, evidence):
    rows = {r["ucsc"]: r for r in _registry_rows(entry)}
    assert rows["chrM"]["ensembl"] == ""
    assert rows["chrM"]["refseq"] == "NC_001807.4"
    assert all(r["refseq"] != "NC_001807.4" for r in evidence)
    assert rows["chrMT"]["ensembl"] == "MT"
    assert rows["chrMT"]["refseq"] == "NC_012920.1"


def test_mt_ucsc_name_disagreement_is_explicitly_acknowledged(entry):
    cfg = copy.deepcopy(entry)
    cfg["ensembl_evidence"]["ucsc_name_disagreements"] = []
    with pytest.raises(RegistryBuildError, match="acknowledge explicitly"):
        builder.build_from_entry(cfg)
    (ack,) = entry["ensembl_evidence"]["ucsc_name_disagreements"]
    assert (ack["ensembl_name"], ack["evidence_ucsc"],
            ack["registry_ucsc"]) == ("MT", "chrM", "chrMT")
    assert "NC_012920.1" in ack["rationale"] and "NC_001807.4" in ack["rationale"]


def test_runtime_sees_new_aliases_without_runtime_changes(hg19):
    for alias in ("1", "chr1", "NC_000001.10", "CM000663.1"):
        assert hg19.resolve(alias).seq_id == "hg19:chr1"
    assert hg19.render("hg19:chr1", "ensembl").alias == "1"
    gl = hg19.resolve("GL000211.1").seq_id
    assert gl == hg19.resolve("chrUn_gl000211").seq_id
    assert hg19.render(gl, "ensembl").alias == "GL000211.1"
    assert not hg19.resolve("NC_000001").resolved
