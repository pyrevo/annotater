"""Assembly-scoped identity across the GRCh38 and hg19 registries (SPEC 5.1).

The same-looking label must never be taken for the same sequence: identity
is (assembly, alias), not a global alias.
"""

from __future__ import annotations

import pytest

from streamlit_app.core.chrom_registry import (
    NO_ALIAS_FOR_TARGET,
    UNKNOWN,
    UnsupportedAssemblyError,
    load_registry,
)

# SHA-256 of data/GRCh38.tsv as built in Task 1; Task 4 must not change it.
GRCH38_TSV_SHA256 = "60a9ccb93254d274fa86a5b8a60d1c1c0b6b58fa6373d47f884d4b11bf8f3277"


@pytest.fixture(scope="module")
def grch38():
    return load_registry("GRCh38")


@pytest.fixture(scope="module")
def hg19():
    return load_registry("hg19")


def test_registries_load_independently_and_are_cached(grch38, hg19):
    assert grch38 is not hg19
    assert (grch38.assembly_id, hg19.assembly_id) == ("GRCh38", "hg19")
    assert len(grch38) == 711 and len(hg19) == 298
    assert load_registry("GRCh38") is grch38 and load_registry("hg19") is hg19


@pytest.mark.parametrize("name", ["GRCh37", "HG38", "grch37", "HG19", "mm9"])
def test_assemblies_are_not_aliased_and_unsupported_still_fail(name):
    with pytest.raises(UnsupportedAssemblyError):
        load_registry(name)


def test_loading_hg19_does_not_mutate_grch38(grch38, hg19):
    before = {s: dict(grch38.record(s).aliases) for s in grch38}
    hg19.resolve("chr1")
    load_registry("hg19")
    after = {s: dict(grch38.record(s).aliases) for s in grch38}
    assert before == after
    assert all(s.startswith("GRCh38:") for s in grch38)
    assert all(s.startswith("hg19:") for s in hg19)


def test_hg19_primary_chromosome(hg19):
    ids = {hg19.resolve(a).seq_id
           for a in ("chr1", "1", "NC_000001.10", "CM000663.1")}
    assert len(ids) == 1
    (seq_id,) = ids
    assert dict(hg19.record(seq_id).aliases) == {
        "ucsc": "chr1", "assembly": "1", "ensembl": "1",  # Ensembl: evidence
        "genbank": "CM000663.1", "refseq": "NC_000001.10",
    }
    # GRCh38 accessions are not hg19 sequences.
    assert not hg19.resolve("NC_000001.11").resolved
    assert not hg19.resolve("CM000663.2").resolved


def test_same_chromosome_has_distinct_scoped_records(grch38, hg19):
    a, b = grch38.resolve("chr1").seq_id, hg19.resolve("chr1").seq_id
    assert a != b
    assert grch38.render(a, "refseq").alias == "NC_000001.11"
    assert hg19.render(b, "refseq").alias == "NC_000001.10"
    # An alias valid in one assembly can be unknown in the other.
    assert grch38.resolve("NC_000001.10").reason == UNKNOWN
    assert hg19.resolve("NC_000001.11").reason == UNKNOWN


# --- mitochondrial sequence -------------------------------------------------

def test_hg19_chrM_resolves_with_its_own_refseq_accession(hg19):
    a, b = hg19.resolve("chrM"), hg19.resolve("NC_001807.4")
    assert a.resolved and a.seq_id == b.seq_id
    assert dict(hg19.record(a.seq_id).aliases) == {
        "ucsc": "chrM", "refseq": "NC_001807.4"}
    out = hg19.render(a.seq_id, "refseq")  # corrected authority label
    assert out.alias == "NC_001807.4"


def test_hg19_chrM_and_chrMT_are_distinct_records(hg19):
    # UCSC's hg19 table carries two mitochondrial sequences: chrM
    # (NC_001807.4) and chrMT (NC_012920.1, with the assembly name "MT").
    # They are separate records; the registry never merges them by name.
    chr_m = hg19.resolve("chrM").seq_id
    chr_mt = hg19.resolve("chrMT").seq_id
    assert chr_m != chr_mt
    assert {hg19.resolve(a).seq_id
            for a in ("MT", "NC_012920.1", "J01415.2")} == {chr_mt}
    assert dict(hg19.record(chr_mt).aliases) == {
        "ucsc": "chrMT", "assembly": "MT", "ensembl": "MT",
        "genbank": "J01415.2", "refseq": "NC_012920.1"}
    # Nothing of chrMT leaks onto chrM, and vice versa.
    assert set(hg19.record(chr_m).aliases.values()) == {"chrM", "NC_001807.4"}
    assert hg19.resolve("NC_001807.4").seq_id == chr_m


@pytest.mark.parametrize("alias", ["M", "chrmt", "MT.1", "NC_012920"])
def test_hg19_does_not_invent_mitochondrial_aliases(hg19, alias):
    result = hg19.resolve(alias)
    assert not result.resolved and result.reason == UNKNOWN


def test_grch38_mitochondrial_accession_is_not_hg19s(grch38):
    assert grch38.resolve("NC_012920.1").resolved
    assert grch38.resolve("MT").resolved
    result = grch38.resolve("NC_001807.4")
    assert not result.resolved and result.reason == UNKNOWN


def test_chrM_is_assembly_scoped_and_differs_between_assemblies(grch38, hg19):
    g, h = grch38.resolve("chrM"), hg19.resolve("chrM")
    assert g.resolved and h.resolved
    assert g.seq_id != h.seq_id
    g_aliases = dict(grch38.record(g.seq_id).aliases)
    h_aliases = dict(hg19.record(h.seq_id).aliases)
    assert g_aliases != h_aliases
    assert g_aliases["refseq"] == "NC_012920.1"
    assert h_aliases["refseq"] == "NC_001807.4"
    assert set(g_aliases.values()) & set(h_aliases.values()) == {"chrM"}
    # GRCh38's chrM carries the same accession as hg19's chrMT, but the
    # registries are not linked: no cross-assembly equivalence is claimed.
    h_mt = hg19.record(hg19.resolve("NC_012920.1").seq_id)
    assert h_mt.aliases["refseq"] == g_aliases["refseq"]
    assert h_mt.seq_id != g.seq_id


def test_hg19_chrM_has_no_ensembl_alias_and_nothing_is_substituted(hg19):
    seq_id = hg19.resolve("chrM").seq_id
    out = hg19.render(seq_id, "ensembl")
    assert not out.rendered
    assert out.alias is None and out.reason == NO_ALIAS_FOR_TARGET
    # Not the UCSC name, not the RefSeq accession, no 'MT'.
    assert out.alias not in ("chrM", "MT", "NC_001807.4")
    for authority in ("assembly", "genbank"):
        assert hg19.render(seq_id, authority).reason == NO_ALIAS_FOR_TARGET


# --- Ensembl aliases are evidence-backed only --------------------------------

def test_hg19_ensembl_aliases_exist_only_where_verified(hg19):
    have = [s for s in hg19 if hg19.render(s, "ensembl").rendered]
    assert len(have) == 84
    chr1 = hg19.resolve("chr1").seq_id
    assert hg19.render(chr1, "ensembl").alias == "1"
    # An assembly alias without Ensembl evidence stays unrendered.
    hap = hg19.resolve("chr17_ctg5_hap1").seq_id
    assert hg19.render(hap, "assembly").alias == "HSCHR17_1_CTG5"
    assert hg19.render(hap, "ensembl").reason == NO_ALIAS_FOR_TARGET


def test_ensembl_name_is_not_the_assembly_alias_in_general(hg19):
    # Evidence says GL000211.1 is the Ensembl name; the assembly alias differs.
    seq_id = hg19.resolve("chrUn_gl000211").seq_id
    assert hg19.render(seq_id, "ensembl").alias == "GL000211.1"
    assert hg19.render(seq_id, "assembly").alias == "HSCHRUN_RANDOM_CTG1"


def test_hg19_chrMT_gains_ensembl_MT_from_evidence_but_chrM_does_not(
        grch38, hg19):
    chr_mt = hg19.resolve("chrMT").seq_id
    assert hg19.render(chr_mt, "ensembl").alias == "MT"
    assert hg19.resolve("MT").seq_id == chr_mt  # still the chrMT record
    chr_m = hg19.resolve("chrM").seq_id
    assert chr_m != chr_mt
    out = hg19.render(chr_m, "ensembl")
    assert out.alias is None and out.reason == NO_ALIAS_FOR_TARGET
    # Shared alias strings do not create cross-assembly identity.
    g = grch38.resolve("chrM").seq_id
    assert grch38.render(g, "ensembl").alias == "MT"
    assert g not in (chr_m, chr_mt) and chr_mt != g
    assert grch38.resolve("MT").seq_id != hg19.resolve("MT").seq_id


def test_grch38_registry_is_byte_identical_and_unchanged(grch38):
    import hashlib

    from streamlit_app.core.chrom_registry import builder
    data = (builder.PACKAGE_DIR / "data" / "GRCh38.tsv").read_bytes()
    assert hashlib.sha256(data).hexdigest() == GRCH38_TSV_SHA256
    assert "ensembl_evidence" not in builder.get_assembly(
        builder.load_sources(), "GRCh38")
    assert sum(grch38.render(s, "ensembl").rendered for s in grch38) == 194


# --- no global alias index ---------------------------------------------------

def test_lookup_is_per_registry_not_global(grch38, hg19):
    shared = [a for a in ("chr1", "chrM", "1", "X", "chrX")
              if grch38.resolve(a).resolved and hg19.resolve(a).resolved]
    assert {"chr1", "chrM", "chrX"} <= set(shared)
    for alias in shared:
        assert grch38.resolve(alias).seq_id != hg19.resolve(alias).seq_id
    assert not hasattr(grch38, "resolve_any")
    only_hg19 = [a for a in ("NC_001807.4", "NC_000001.10")
                 if hg19.resolve(a).resolved]
    assert only_hg19 == ["NC_001807.4", "NC_000001.10"]
    assert not any(grch38.resolve(a).resolved for a in only_hg19)


def test_records_remain_immutable(hg19):
    record = hg19.record(hg19.resolve("chrM").seq_id)
    with pytest.raises(TypeError):
        record.aliases["ensembl"] = "MT"
    assert hg19.resolve("MT").seq_id != record.seq_id


def test_no_mitochondrial_special_casing_in_runtime_source():
    from pathlib import Path

    from streamlit_app.core.chrom_registry import loader
    source = Path(loader.__file__).read_text()
    for needle in ("hg19", "GRCh38", "chrM", "NC_0", "mitochond", "\"MT\""):
        assert needle not in source, needle
