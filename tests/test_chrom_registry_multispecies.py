"""Non-human registries: GRCm39, dm6, GRCz11, rn7 (SPEC 5.1).

Every fact below comes from the pinned authoritative data; none is derived
from human naming conventions.
"""

from __future__ import annotations

import pytest

from streamlit_app.core.chrom_registry import (
    NO_ALIAS_FOR_TARGET,
    UNKNOWN,
    UnsupportedAssemblyError,
    builder,
    load_registry,
)

ALL = ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "rn7"]
# assembly -> (UCSC db, sequence records)
COUNTS = {"GRCm39": 61, "dm6": 1870, "GRCz11": 1923, "rn7": 176}


@pytest.fixture(scope="module", params=sorted(COUNTS))
def reg(request):
    return load_registry(request.param)


def regs():
    return {a: load_registry(a) for a in ALL}


def sid(reg, alias):
    result = reg.resolve(alias)
    assert result.resolved, (reg.assembly_id, alias)
    return result.seq_id


def aliases(reg, alias):
    return dict(reg.record(sid(reg, alias)).aliases)


# --- per-assembly configuration ----------------------------------------------

def test_configured_assemblies_and_ids_are_explicit():
    ids = [e["assembly_id"] for e in builder.load_sources()["assemblies"]]
    assert ids[:6] == ALL
    for name in ("grcm39", "GRCM39", "Mouse", "Drosophila", "Danrer11",
                 "mratbn7.2", "GRCr8", "BDGP6", "dm3", "mm9", "rn6"):
        with pytest.raises(UnsupportedAssemblyError):
            load_registry(name)


@pytest.mark.parametrize("aid,db", [("GRCm39", "mm39"), ("dm6", "dm6"),
                                    ("GRCz11", "danRer11"), ("rn7", "rn7")])
def test_sources_are_pinned_database_tables(aid, db):
    entry = builder.get_assembly(builder.load_sources(), aid)
    assert entry["ucsc_db"] == db
    assert entry["source_url"] == (
        f"https://hgdownload.soe.ucsc.edu/goldenPath/{db}/database/"
        "chromAlias.txt.gz")
    assert "bigZips" not in entry["source_url"]
    assert entry["label_corrections"] == []  # no corrections were needed
    data = (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes()
    assert builder.sha256_hex(data) == entry["sha256"]


def test_only_rn7_among_new_assemblies_uses_ensembl_evidence():
    config = builder.load_sources()
    have = {e["assembly_id"] for e in config["assemblies"]
            if "ensembl_evidence" in e}
    assert have == {"hg19", "rn7"}
    rat = builder.get_assembly(config, "rn7")["ensembl_evidence"]
    assert rat["ensembl_release"] == 111
    assert rat["ensembl_assembly"] == "mRatBN7.2"
    assert rat["assembly_accession"] == "GCA_015227675.2"
    assert "GRCr8" in rat["match_rule"]  # the different current assembly


def test_record_counts_and_wide_schema_lossless(reg):
    key = {"mRatBN7.2": "rn7"}.get(reg.assembly_id, reg.assembly_id)
    assert len(reg) == COUNTS[key]
    entry = builder.get_assembly(builder.load_sources(), key)
    rows = builder.parse_alias_table(
        (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes())
    # Every upstream (alias, sequence) pair is resolvable; none dropped.
    chrom_to_seq = {reg.record(s).aliases["ucsc"]: s for s in reg}
    for alias, chrom, _ in rows:
        assert reg.resolve(alias).seq_id == chrom_to_seq[chrom]


def test_every_alias_round_trips(reg):
    for seq_id in reg:
        for authority, alias in reg.record(seq_id).aliases.items():
            assert reg.resolve(alias).seq_id == seq_id
            assert reg.render(seq_id, authority).alias == alias


# --- GRCm39 --------------------------------------------------------------------

def test_grcm39_primary_chromosomes():
    mouse = load_registry("GRCm39")
    assert aliases(mouse, "NC_000067.7") == {
        "ucsc": "chr1", "assembly": "1", "ensembl": "1",
        "genbank": "CM000994.3", "refseq": "NC_000067.7"}
    assert sid(mouse, "chr1") == sid(mouse, "1") == sid(mouse, "CM000994.3")
    assert aliases(mouse, "chr19")["refseq"] == "NC_000085.7"
    assert aliases(mouse, "X")["genbank"] == "CM001013.3"
    assert aliases(mouse, "chrY")["refseq"] == "NC_000087.8"
    assert not mouse.resolve("chr20").resolved  # mouse has 19 autosomes
    assert not mouse.resolve("NC_000067.6").resolved  # GRCm38 version


def test_grcm39_mitochondrial_and_non_primary():
    mouse = load_registry("GRCm39")
    assert aliases(mouse, "MT") == {
        "ucsc": "chrM", "assembly": "MT", "ensembl": "MT",
        "genbank": "AY172335.1", "refseq": "NC_005089.1"}
    random = aliases(mouse, "chr1_GL456210v1_random")
    assert random["assembly"] == "MMCHR1_RANDOM_CTG1"
    assert random["ensembl"] == "GL456210.1" == random["genbank"]
    un = aliases(mouse, "MSCHRUN_CTG13")
    assert un["ucsc"] == "chrUn_GL456359v1"


def test_grcm39_ensembl_aliases_are_explicit_upstream_labels():
    mouse = load_registry("GRCm39")
    entry = builder.get_assembly(builder.load_sources(), "GRCm39")
    assert "ensembl_evidence" not in entry
    rows = builder.parse_alias_table(
        (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes())
    explicit = {alias for alias, _, source in rows if "ensembl" in source}
    ens = {mouse.render(s, "ensembl").alias for s in mouse} - {None}
    assert ens == explicit and len(ens) == 61


# --- dm6: non-numeric, non-human naming ---------------------------------------

@pytest.mark.parametrize("name,genbank,refseq", [
    ("2L", "AE014134.6", "NT_033779.5"),
    ("2R", "AE013599.5", "NT_033778.4"),
    ("3L", "AE014296.5", "NT_037436.4"),
    ("3R", "AE014297.3", "NT_033777.3"),
    ("4", "AE014135.4", "NC_004353.4"),
    ("X", "AE014298.5", "NC_004354.4"),
    ("Y", "CP007106.1", "NC_024512.1"),
])
def test_dm6_chromosomes_resolve_through_registry_aliases(name, genbank,
                                                         refseq):
    fly = load_registry("dm6")
    assert aliases(fly, name) == {"ucsc": f"chr{name}", "ensembl": name,
                                  "genbank": genbank, "refseq": refseq}
    assert sid(fly, name) == sid(fly, f"chr{name}") == sid(fly, genbank)
    assert fly.render(sid(fly, refseq), "ensembl").alias == name


def test_dm6_has_no_assembly_native_aliases_and_no_human_names():
    fly = load_registry("dm6")
    assert not any(fly.render(s, "assembly").rendered for s in fly)
    for human in ("1", "chr1", "22", "chr22", "MT", "M", "chrMT"):
        assert not fly.resolve(human).resolved, human
    # Ensembl names are bare ("2L"), UCSC names carry the prefix.
    assert fly.render(sid(fly, "chr2L"), "ucsc").alias == "chr2L"


def test_dm6_mitochondrial_has_no_ensembl_alias():
    fly = load_registry("dm6")
    assert aliases(fly, "chrM") == {"ucsc": "chrM", "genbank": "KJ947872.2",
                                    "refseq": "NC_024511.2"}
    assert sid(fly, "NC_024511.2") == sid(fly, "KJ947872.2") == sid(fly, "chrM")
    out = fly.render(sid(fly, "chrM"), "ensembl")
    assert not out.rendered and out.reason == NO_ALIAS_FOR_TARGET
    for guess in ("MT", "M", "mitochondrion_genome"):
        assert fly.resolve(guess).reason == UNKNOWN  # nothing is inferred


def test_dm6_scaffold_record():
    fly = load_registry("dm6")
    assert aliases(fly, "2Cen_mapped_Scaffold_10") == {
        "ucsc": "chrUn_CP007071v1", "ensembl": "2Cen_mapped_Scaffold_10",
        "genbank": "CP007071.1", "refseq": "NW_007931073.1"}
    assert sum(not fly.render(s, "ensembl").rendered for s in fly) == 1


# --- GRCz11: chromosomes beyond 22 --------------------------------------------

def test_grcz11_chromosomes_above_22():
    fish = load_registry("GRCz11")
    for n, refseq in (("23", "NC_007134.7"), ("24", "NC_007135.7"),
                      ("25", "NC_007136.7")):
        rec = aliases(fish, f"chr{n}")
        assert rec["ensembl"] == n and rec["refseq"] == refseq
        assert sid(fish, n) == sid(fish, f"chr{n}")
    assert not fish.resolve("chr26").resolved
    assert aliases(fish, "chrM")["ensembl"] == "MT"


def test_grcz11_alts_have_no_ensembl_alias_and_unplaced_do():
    fish = load_registry("GRCz11")
    have = [s for s in fish if fish.render(s, "ensembl").rendered]
    assert len(have) == 993  # 25 chromosomes + chrM + 967 unplaced
    alt = fish.resolve("chr10_KZ114911v1_alt").seq_id
    out = fish.render(alt, "ensembl")
    assert not out.rendered and out.reason == NO_ALIAS_FOR_TARGET
    assert fish.render(alt, "genbank").alias == "KZ114911.1"
    assert not any(fish.render(s, "assembly").rendered for s in fish)


# --- rn7: Ensembl via pinned mRatBN7.2 release evidence -----------------------

def test_rn7_chromosomes_and_mitochondrion():
    rat = load_registry("rn7")
    assert aliases(rat, "chr1") == {
        "ucsc": "chr1", "assembly": "1", "ensembl": "1",
        "genbank": "CM026974.1", "refseq": "NC_051336.1"}
    assert aliases(rat, "20")["refseq"] == "NC_051355.1"
    assert aliases(rat, "MT") == {
        "ucsc": "chrM", "assembly": "MT", "ensembl": "MT",
        "genbank": "AY172581.1", "refseq": "NC_001665.2"}
    assert not rat.resolve("chr21").resolved


def test_rn7_ensembl_alias_is_evidence_not_assembly_name():
    rat = load_registry("rn7")
    seq = aliases(rat, "scaffold_23")
    assert seq["ensembl"] == "MU150194.1" != seq["assembly"]
    assert all(rat.render(s, "ensembl").rendered for s in rat)
    entry = builder.get_assembly(builder.load_sources(), "rn7")
    rows = builder.parse_alias_table(
        (builder.PACKAGE_DIR / entry["upstream_file"]).read_bytes())
    assert not any("ensembl" in source for _, _, source in rows)


# --- facts a human-shaped rewrite would get wrong --------------------------------

def test_registry_results_that_string_rewriting_cannot_produce():
    fly, fish = load_registry("dm6"), load_registry("GRCz11")
    # dm6: "2L" has no numeric/chr-prefix relationship to rely on.
    assert fly.render(sid(fly, "chr2L"), "ensembl").alias == "2L"
    assert fly.render(sid(fly, "2R"), "ucsc").alias == "chr2R"
    # zebrafish chromosomes above 22.
    assert fish.render(sid(fish, "chr25"), "ensembl").alias == "25"
    # dm6 chrM has no Ensembl alias; a chrM -> MT rewrite would invent one.
    assert not fly.render(sid(fly, "chrM"), "ensembl").rendered
    assert not fly.resolve("MT").resolved


# --- cross-assembly isolation ---------------------------------------------------

def test_shared_alias_strings_resolve_to_distinct_scoped_records():
    r = regs()
    for alias in ("chr1", "1", "X", "4", "chrX", "chrM", "MT", "chr19"):
        found = {a: reg.resolve(alias).seq_id for a, reg in r.items()
                 if reg.resolve(alias).resolved}
        assert len(set(found.values())) == len(found), (alias, found)
        for assembly, seq_id in found.items():
            assert seq_id in r[assembly]
            assert all(seq_id not in r[o] for o in r if o != assembly)
    # "MT" names a mitochondrion in five registries, never in dm6.
    assert [a for a in r if r[a].resolve("MT").resolved] == [
        "GRCh38", "hg19", "GRCm39", "GRCz11", "rn7"]


def test_accessions_are_isolated_per_assembly():
    r = regs()
    owners = {}
    for assembly, reg in r.items():
        for seq_id in reg:
            for alias in reg.record(seq_id).aliases.values():
                if alias.startswith(("NC_", "NT_", "NW_", "CM")):
                    owners.setdefault(alias, set()).add(assembly)
    shared = {a: o for a, o in owners.items() if len(o) > 1}
    # Where an accession is shared, each registry still has its own record.
    for alias, assemblies in shared.items():
        ids = {r[a].resolve(alias).seq_id for a in assemblies}
        assert len(ids) == len(assemblies)


def test_registries_remain_read_only_and_cached():
    fly = load_registry("dm6")
    assert load_registry("dm6") is fly
    with pytest.raises(TypeError):
        fly.record(sid(fly, "2L")).aliases["ensembl"] = "x"
