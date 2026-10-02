"""Offline tests for the GRCh38 chromosome-alias registry builder (SPEC 5.1).

The builder is build-time tooling only; nothing here touches the network or
the runtime normalization.
"""

from __future__ import annotations

import copy
import csv
import gzip
import sys
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import builder
from streamlit_app.core.chrom_registry.builder import RegistryBuildError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update_chrom_aliases


def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def parse(text: str):
    return builder.parse_alias_table(gz(text))


GOOD = (
    "1\tchr1\tassembly,ensembl\n"
    "CM000663.2\tchr1\tgenbank\n"
    "NC_000001.11\tchr1\trefseq\n"
)


@pytest.fixture(scope="module")
def entry():
    return builder.get_assembly(builder.load_sources(), "GRCh38")


@pytest.fixture(scope="module")
def registry(entry):
    path = builder.PACKAGE_DIR / entry["registry_file"]
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# --- parser / validation ---------------------------------------------------

def test_valid_source_parses():
    assert parse(GOOD) == [
        ("1", "chr1", "assembly,ensembl"),
        ("CM000663.2", "chr1", "genbank"),
        ("NC_000001.11", "chr1", "refseq"),
    ]


@pytest.mark.parametrize("text", ["1\tchr1\n", "1\tchr1\tassembly\textra\n",
                                  "1\tchr1\tassembly\n\n"])
def test_malformed_row_rejected(text):
    with pytest.raises(RegistryBuildError, match="expected 3"):
        parse(text)


@pytest.mark.parametrize("text,field", [
    ("\tchr1\tassembly\n", "alias"),
    ("1\t\tassembly\n", "chrom"),
    ("1\tchr1\t\n", "source"),
])
def test_empty_required_value_rejected(text, field):
    with pytest.raises(RegistryBuildError, match=f"empty {field}"):
        parse(text)


def test_surrounding_whitespace_rejected():
    with pytest.raises(RegistryBuildError, match="whitespace"):
        parse("1 \tchr1\tassembly\n")


def test_empty_and_non_gzip_input_rejected():
    with pytest.raises(RegistryBuildError, match="no rows"):
        parse("")
    with pytest.raises(RegistryBuildError, match="cannot read"):
        builder.parse_alias_table(b"not gzip")


def test_conflicting_alias_rejected():
    rows = parse("1\tchr1\tassembly\n1\tchr2\tassembly\n")
    with pytest.raises(RegistryBuildError, match="resolves to both"):
        builder.build_registry(rows, "GRCh38")


def test_alias_equal_to_other_sequence_ucsc_name_rejected():
    rows = parse("chr2\tchr1\tassembly\n2\tchr2\tassembly\n")
    with pytest.raises(RegistryBuildError, match="UCSC name"):
        builder.build_registry(rows, "GRCh38")


def test_two_aliases_for_one_authority_rejected_not_chosen():
    rows = parse("1\tchr1\tassembly\none\tchr1\tassembly\n")
    with pytest.raises(RegistryBuildError, match="more than one assembly"):
        builder.build_registry(rows, "GRCh38")


@pytest.mark.parametrize("text,match", [
    ("NC_000001.11\tchr1\tgenbank\n", "RefSeq-style accession"),
    ("CM000663.2\tchr1\trefseq\n", "not a RefSeq accession"),
    ("NT_187361.1\tchr1\tgenbank,ensembl\n", "RefSeq-style accession"),
    ("MT\tchrM\tgenbank\n", "not an INSDC accession"),
])
def test_accession_label_inconsistency_rejected(text, match):
    with pytest.raises(RegistryBuildError, match=match):
        builder.build_registry(parse(text), "GRCh38")


@pytest.mark.parametrize("label", ["ncbi", "assembly,bogus"])
def test_unsupported_source_label_rejected(label):
    with pytest.raises(RegistryBuildError, match="unsupported source label"):
        builder.build_registry(parse(f"1\tchr1\t{label}\n"), "GRCh38")


def test_repeated_label_rejected():
    with pytest.raises(RegistryBuildError, match="repeated label"):
        builder.build_registry(parse("1\tchr1\tassembly,assembly\n"), "GRCh38")


def test_explicit_label_correction_is_applied_and_must_match():
    rows = parse("NC_001807.4\tchrM\tgenbank\n")
    correction = {"alias": "NC_001807.4", "chrom": "chrM", "from": "genbank",
                  "to": "refseq", "rationale": "RefSeq accession mislabelled"}
    out = builder.build_registry(rows, "hg19", [correction])
    assert out.splitlines()[1].split("\t") == [
        "hg19:chrM", "chrM", "", "", "", "NC_001807.4"]
    stale = dict(correction, **{"from": "refseq"})
    with pytest.raises(RegistryBuildError, match="matched no upstream row"):
        builder.build_registry(rows, "hg19", [stale])
    with pytest.raises(RegistryBuildError, match="missing 'rationale'"):
        builder.build_registry(
            rows, "hg19", [{k: v for k, v in correction.items()
                            if k != "rationale"}])


def test_build_output_is_deterministic_and_order_independent():
    shuffled = "\n".join(reversed(GOOD.strip().split("\n"))) + "\n"
    a = builder.build_registry(parse(GOOD), "GRCh38")
    assert a == builder.build_registry(parse(shuffled), "GRCh38")
    assert a.splitlines()[1] == "GRCh38:chr1\tchr1\t1\t1\tCM000663.2\tNC_000001.11"


def test_missing_alias_stays_empty_not_inferred():
    out = builder.build_registry(parse("HSCHR10_1_CTG1\tchr10_alt\tassembly\n"),
                                 "GRCh38")
    assert out.splitlines()[1] == (
        "GRCh38:chr10_alt\tchr10_alt\tHSCHR10_1_CTG1\t\t\t")


# --- pinned upstream resource ----------------------------------------------

def test_raw_source_matches_pinned_sha256(entry):
    data = (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes()
    assert builder.sha256_hex(data) == entry["sha256"]
    builder.verify_checksum(data, entry)


def test_checksum_drift_is_hard_stop(entry):
    with pytest.raises(RegistryBuildError, match="does not match pinned"):
        builder.verify_checksum(b"changed", entry)


def test_source_provenance_recorded(entry):
    assert entry["assembly_id"] == "GRCh38"
    assert entry["ucsc_db"] == "hg38"
    assert entry["source_url"] == (
        "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/database/"
        "chromAlias.txt.gz")
    for key in ("sha256", "upstream_last_modified", "retrieved",
                "source_format"):
        assert entry[key]


def test_committed_registry_rebuilds_byte_identically(entry):
    first = builder.build_from_entry(entry)
    assert first == builder.build_from_entry(entry)
    committed = (builder.PACKAGE_DIR / entry["registry_file"]).read_bytes()
    assert committed == first.encode("utf-8")
    builder.check(entry)


def test_check_detects_hand_edited_registry(entry, tmp_path):
    for rel in (entry["upstream_file"], entry["registry_file"]):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((builder.PACKAGE_DIR / rel).read_bytes())
    builder.check(entry, tmp_path)
    reg = tmp_path / entry["registry_file"]
    reg.write_text(reg.read_text().replace("CM000663.2", "CM000663.9"))
    with pytest.raises(RegistryBuildError, match="differs from a rebuild"):
        builder.check(entry, tmp_path)


def test_registry_schema_and_opaque_ids(registry):
    assert list(registry[0]) == list(builder.HEADER)
    ids = [r["seq_id"] for r in registry]
    assert len(ids) == len(set(ids))
    assert all(r["seq_id"] == f"GRCh38:{r['ucsc']}" for r in registry)


# --- representative GRCh38 facts (from the pinned upstream table) -----------

def _record(registry, ucsc):
    return next(r for r in registry if r["ucsc"] == ucsc)


def _alias_index(registry):
    index = {}
    for r in registry:
        for authority in builder.AUTHORITIES:
            if r[authority]:
                index.setdefault(r[authority], set()).add(r["seq_id"])
    return index


def test_chromosome_1_aliases_share_one_record(registry):
    index = _alias_index(registry)
    ids = {next(iter(index[a])) for a in
           ("chr1", "1", "NC_000001.11", "CM000663.2")}
    assert ids == {"GRCh38:chr1"}
    rec = _record(registry, "chr1")
    assert (rec["assembly"], rec["ensembl"], rec["genbank"], rec["refseq"]) == (
        "1", "1", "CM000663.2", "NC_000001.11")


def test_mitochondrial_record_is_its_own_assembly_keyed_record(registry):
    rec = _record(registry, "chrM")
    assert (rec["assembly"], rec["ensembl"], rec["genbank"], rec["refseq"]) == (
        "MT", "MT", "J01415.2", "NC_012920.1")


def test_non_primary_sequences_keep_only_verified_aliases(registry):
    alt = _record(registry, "chr10_GL383545v1_alt")
    assert alt["assembly"] == "HSCHR10_1_CTG1"
    assert alt["ensembl"] == ""  # UCSC does not label it ensembl: not inferred
    assert (alt["genbank"], alt["refseq"]) == ("GL383545.1", "NW_003315934.1")
    unplaced = _record(registry, "chrUn_KI270752v1")
    assert unplaced["ensembl"] == "KI270752.1" == unplaced["genbank"]
    assert unplaced["refseq"] == ""  # absent upstream: stays empty


def test_no_syntactic_aliases_were_invented(registry):
    index = _alias_index(registry)
    assert "NC_000001" not in index  # unversioned accession is not an alias
    assert "chrMT" not in index and "M" not in index
    assert "chr23" not in index


def test_every_record_has_at_most_one_alias_per_authority(entry):
    # Wide schema is lossless for GRCh38: every upstream (alias, chrom,
    # label) pair is present in the registry, none dropped or chosen.
    rows = builder.parse_alias_table(
        (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes())
    text = builder.build_registry(rows, "GRCh38")
    cells = {}
    for line in text.splitlines()[1:]:
        f = line.split("\t")
        cells[f[1]] = dict(zip(builder.SOURCE_LABELS, f[2:]))
    for alias, chrom, source in rows:
        for label in source.split(","):
            assert cells[chrom][label] == alias


# --- CLI ---------------------------------------------------------------------

class _Args:
    assembly = None
    check = False
    write = False
    fetch = False
    accept_upstream_update = False


def test_cli_check_passes_on_committed_resources(capsys):
    assert update_chrom_aliases.main(["--check"]) == 0
    assert "GRCh38: OK" in capsys.readouterr().out


def test_cli_fetch_drift_is_hard_stop_without_accept(entry):
    args = _Args()
    args.fetch = True
    with pytest.raises(RegistryBuildError, match="upstream changed"):
        update_chrom_aliases.run(args, fetch=lambda url: (gz(GOOD), "x"))


def test_cli_fetch_unchanged_is_ok(capsys):
    entry = builder.get_assembly(builder.load_sources(), "GRCh38")
    data = (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes()
    args = _Args()
    args.fetch = True
    args.assembly = "GRCh38"
    assert update_chrom_aliases.run(
        args, fetch=lambda url: (data, "x")) == 0
    assert "upstream unchanged" in capsys.readouterr().out


def test_cli_fetch_hg19_changed_ensembl_tables_is_hard_stop():
    args = _Args()
    args.fetch = True
    args.assembly = "hg19"
    with pytest.raises(RegistryBuildError, match="Ensembl table"):
        update_chrom_aliases.run(args, fetch=lambda url: (gz(GOOD), "x"))


def test_accept_upstream_repins_in_isolation(entry, tmp_path):
    local = copy.deepcopy(entry)
    (tmp_path / "upstream").mkdir()
    new = gz(GOOD)
    builder.accept_upstream(local, new, "Mon, 01 Jan 2029 00:00:00 GMT",
                            "2029-01-02", tmp_path)
    assert local["sha256"] == builder.sha256_hex(new) != entry["sha256"]
    assert (tmp_path / local["upstream_file"]).read_bytes() == new
    with pytest.raises(RegistryBuildError):
        builder.accept_upstream(local, b"garbage", "x", "y", tmp_path)
    assert entry["sha256"] != local["sha256"]  # original config untouched


# --- every configured assembly ----------------------------------------------

ASSEMBLY_IDS = [e["assembly_id"] for e in builder.load_sources()["assemblies"]]


def _entry(assembly_id):
    return builder.get_assembly(builder.load_sources(), assembly_id)


def _raw_rows(entry):
    return builder.parse_alias_table(
        (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes())


def test_configured_assemblies():
    assert ASSEMBLY_IDS == ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "rn7"]


@pytest.mark.parametrize("assembly_id", ASSEMBLY_IDS)
def test_each_assembly_is_pinned_deterministic_and_checked(assembly_id):
    e = _entry(assembly_id)
    data = (builder.PACKAGE_DIR / e["upstream_file"]).read_bytes()
    assert builder.sha256_hex(data) == e["sha256"]
    assert e["source_url"].endswith(
        f"/goldenPath/{e['ucsc_db']}/database/chromAlias.txt.gz")
    assert e["registry_file"] == f"data/{assembly_id}.tsv"
    first = builder.build_from_entry(e)
    assert first == builder.build_from_entry(e)
    assert (builder.PACKAGE_DIR / e["registry_file"]).read_bytes() == \
        first.encode("utf-8")
    builder.check(e)


@pytest.mark.parametrize("assembly_id", ASSEMBLY_IDS)
def test_wide_schema_is_lossless_and_corrections_invent_nothing(assembly_id):
    e = _entry(assembly_id)
    rows = _raw_rows(e)
    text = builder.build_from_entry(e)
    out_pairs, cells = set(), {}
    for line in text.splitlines()[1:]:
        f = line.split("\t")
        record = dict(zip(builder.SOURCE_LABELS, f[2:]))
        cells[f[1]] = record
        out_pairs |= {(a, f[1]) for a in record.values() if a}
    # Every alias->sequence association comes from upstream, none added,
    # none dropped (a correction moves an alias between columns only).
    assert out_pairs == {(a, c) for a, c, _ in rows}
    assert len({c for _, c, _ in rows}) == len(cells)
    corrected = {(c["alias"], c["chrom"]): c["to"]
                 for c in e["label_corrections"]}
    for alias, chrom, source in rows:
        labels = [corrected.get((alias, chrom), source)] \
            if (alias, chrom) in corrected else source.split(",")
        for label in labels:
            assert cells[chrom][label] == alias


def test_input_row_order_does_not_change_hg19_output():
    e = _entry("hg19")
    rows = _raw_rows(e)
    from streamlit_app.core.chrom_registry import ensembl_evidence as ev
    cfg = e["ensembl_evidence"]
    evidence = ev.parse_evidence(
        (builder.PACKAGE_DIR / cfg["evidence_file"]).read_text())
    a = builder.build_registry(rows, "hg19", e["label_corrections"],
                               evidence, cfg)
    b = builder.build_registry(list(reversed(rows)), "hg19",
                               e["label_corrections"],
                               list(reversed(evidence)), cfg)
    assert a == b


# --- hg19: explicit, reviewed source-label correction -------------------------

def test_hg19_raw_upstream_row_has_inconsistent_label():
    rows = _raw_rows(_entry("hg19"))
    assert ("NC_001807.4", "chrM", "genbank") in rows


def test_hg19_correction_is_explicit_and_documented():
    (corr,) = _entry("hg19")["label_corrections"]
    assert (corr["alias"], corr["chrom"], corr["from"], corr["to"]) == (
        "NC_001807.4", "chrM", "genbank", "refseq")
    assert "RefSeq" in corr["rationale"] and "16571" in corr["rationale"]
    assert _entry("GRCh38")["label_corrections"] == []


def test_hg19_build_fails_without_the_correction():
    e = copy.deepcopy(_entry("hg19"))
    e["label_corrections"] = []
    with pytest.raises(RegistryBuildError, match="RefSeq-style accession"):
        builder.build_from_entry(e)


@pytest.mark.parametrize("field,value", [
    ("from", "refseq"), ("alias", "NC_001807.5"), ("chrom", "chrM2"),
])
def test_hg19_stale_or_mismatched_correction_fails(field, value):
    e = copy.deepcopy(_entry("hg19"))
    e["label_corrections"][0][field] = value
    with pytest.raises(RegistryBuildError, match="matched no upstream row"):
        builder.build_from_entry(e)


def test_hg19_normalized_registry_carries_corrected_authority():
    lines = builder.build_from_entry(_entry("hg19")).splitlines()
    (chrm,) = [line for line in lines if line.startswith("hg19:chrM\t")]
    # seq_id ucsc assembly ensembl genbank refseq
    assert chrm.split("\t") == [
        "hg19:chrM", "chrM", "", "", "", "NC_001807.4"]


def test_hg19_ensembl_is_evidence_backed_not_inferred_from_assembly_names():
    e = _entry("hg19")
    rows = _raw_rows(e)
    assert not any("ensembl" in source for _, _, source in rows)  # upstream
    text = builder.build_from_entry(e)
    with_ensembl = [line.split("\t") for line in text.splitlines()[1:]
                    if line.split("\t")[3]]
    assert len(with_ensembl) == 84  # derived from the pinned evidence
    # Without the pinned evidence no Ensembl alias exists at all.
    bare = copy.deepcopy(e)
    del bare["ensembl_evidence"]
    assert all(line.split("\t")[3] == ""
               for line in builder.build_from_entry(bare).splitlines()[1:])


# --- accession shapes ---------------------------------------------------------

@pytest.mark.parametrize("accession", [
    "CM000663.2", "AE014134.6", "J01415.2", "KI270752.1",
    "JACYVU010000238.1",   # WGS contig, 6-letter project prefix (rn7)
    "CP007071.1", "MU150194.1"])
def test_insdc_accession_shapes_are_accepted_as_genbank(accession):
    out = builder.build_registry(parse(f"{accession}\tchrX\tgenbank\n"), "T")
    assert out.splitlines()[1].split("\t")[4] == accession


@pytest.mark.parametrize("accession", ["MT", "chr1", "1", "NC_000001.11",
                                       "AB.1", "ABCDEFG01000001.1"])
def test_non_insdc_shapes_are_rejected_as_genbank(accession):
    with pytest.raises(RegistryBuildError):
        builder.build_registry(parse(f"{accession}\tchrX\tgenbank\n"), "T")
