"""Independent alias oracle versus the generated registries and the runtime.

``tests/oracle/chrom_reference.py`` derives the expected alias facts of each
assembly from the pinned upstream inputs only (UCSC chromAlias rows, reviewed
label corrections, pinned Ensembl evidence). This module compares that
expectation with (1) the generated ``data/*.tsv`` registries and (2) the
runtime loader/resolver, for every bundled assembly. The builder's own parsing
helpers are not used, so a bug shared by builder and loader cannot hide here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import load_registry
from tests.oracle import chrom_reference as ref

ASSEMBLIES = list(ref.sources())
EVIDENCE_ASSEMBLIES = [a for a, e in ref.sources().items()
                       if "ensembl_evidence" in e]
ORACLES = {a: ref.build_oracle(a) for a in ASSEMBLIES}
VERSIONED = re.compile(r"^(?P<base>.+)\.(?P<version>\d+)$")


def _registry_rows(assembly):
    entry = ref.sources()[assembly]
    text = (ref.REGISTRY_DIR / entry["registry_file"]).read_text()
    return ref.parse_registry_tsv(text)


def test_every_bundled_assembly_is_covered_and_evidence_is_unchanged():
    """The oracle runs over the whole bundled catalog, not a hand list."""
    from streamlit_app.core.chrom_registry import load_catalog
    # the oracle is keyed by the registry key (the manifest's assembly_id)
    assert set(ASSEMBLIES) == {Path(i.registry_file).stem
                               for i in load_catalog()}
    assert ASSEMBLIES[:6] == ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11",
                              "rn7"]
    assert len(ASSEMBLIES) == 64
    assert EVIDENCE_ASSEMBLIES == ["hg19", "rn7"]


@pytest.mark.parametrize("assembly", ASSEMBLIES)
class TestOracleInputs:
    def test_pinned_inputs_have_no_conflicts(self, assembly):
        assert ORACLES[assembly].conflicts == []

    def test_every_correction_applied_exactly_once(self, assembly):
        entry = ref.sources()[assembly]
        wanted = [(c["alias"], c["chrom"], c["from"])
                  for c in entry.get("label_corrections", [])]
        assert sorted(ORACLES[assembly].corrections_applied) == sorted(wanted)

    def test_no_alias_names_two_records(self, assembly):
        assert all(len(chroms) == 1 for chroms
                   in ORACLES[assembly].alias_to_chroms().values())

    def test_at_most_one_alias_per_record_and_authority(self, assembly):
        for chrom, by_authority in ORACLES[assembly].records().items():
            for authority, aliases in by_authority.items():
                assert len(aliases) == 1, (chrom, authority, aliases)


@pytest.mark.parametrize("assembly", ASSEMBLIES)
class TestGeneratedRegistryMatchesOracle:
    def test_registry_is_exactly_the_supported_facts(self, assembly):
        """Nothing invented, nothing missing, no unknown records."""
        problems = ref.registry_discrepancies(
            ORACLES[assembly], _registry_rows(assembly))
        assert problems == []

    def test_registry_has_no_cross_record_alias_conflicts(self, assembly):
        owner = {}
        for row in _registry_rows(assembly):
            for authority in ref.AUTHORITIES:
                alias = row[authority]
                if alias:
                    assert owner.setdefault(alias, row["ucsc"]) == row["ucsc"]


@pytest.mark.parametrize("assembly", ASSEMBLIES)
class TestRuntimeAgreesWithOracle:
    def test_every_upstream_alias_resolves_to_its_record(self, assembly):
        registry, oracle = load_registry(assembly), ORACLES[assembly]
        for chrom, authority, alias in oracle.facts:
            result = registry.resolve(alias)
            assert result.resolved, (assembly, alias)
            assert registry.render(result.seq_id, "ucsc").alias == chrom, alias

    def test_every_supported_alias_renders_from_its_record(self, assembly):
        registry, oracle = load_registry(assembly), ORACLES[assembly]
        for chrom, authority, alias in oracle.facts:
            seq_id = registry.resolve(chrom).seq_id
            assert registry.render(seq_id, authority).alias == alias

    def test_unsupported_authority_cells_stay_empty(self, assembly):
        """Where the oracle has no alias, the runtime reports none."""
        registry, oracle = load_registry(assembly), ORACLES[assembly]
        for chrom, by_authority in oracle.records().items():
            seq_id = registry.resolve(chrom).seq_id
            for authority in ref.AUTHORITIES:
                if authority not in by_authority:
                    assert not registry.render(seq_id, authority).rendered

    def test_record_count_matches(self, assembly):
        assert len(load_registry(assembly)) == len(ORACLES[assembly].chroms)


@pytest.mark.parametrize("assembly", ASSEMBLIES)
def test_exact_versioned_accessions(assembly):
    """No version stripping or version guessing: only the exact accession
    resolves, never the bare accession or a neighbouring version."""
    registry, oracle = load_registry(assembly), ORACLES[assembly]
    known = set(oracle.alias_to_chroms())
    checked = 0
    for chrom, authority, alias in oracle.facts:
        match = VERSIONED.match(alias)
        if authority not in ("genbank", "refseq") or not match:
            continue
        base, version = match["base"], int(match["version"])
        assert registry.resolve(alias).resolved
        variants = {base, f"{base}.{version + 1}", f"{base}.{version - 1}",
                    f"{base}.0{version}"}
        for variant in variants - known:
            assert not registry.resolve(variant).resolved, (alias, variant)
        checked += 1
    if not checked:   # e.g. Ensembl-names-only tables carry no accessions
        assert not [f for f in oracle.facts
                    if f[1] in ("genbank", "refseq")
                    and VERSIONED.match(f[2])]


# ---- label corrections ------------------------------------------------------

def test_hg19_chrM_refseq_label_is_traceable_to_row_plus_correction():
    entry = ref.sources()["hg19"]
    raw = [r for r in ref.read_upstream_rows(entry)
           if r[0] == "NC_001807.4"]
    assert raw == [("NC_001807.4", "chrM", "genbank")]   # upstream label
    corr = entry["label_corrections"]
    assert [(c["alias"], c["chrom"], c["from"], c["to"]) for c in corr] == [
        ("NC_001807.4", "chrM", "genbank", "refseq")]
    assert all(c["rationale"] for c in corr)
    facts = ORACLES["hg19"].facts
    assert ("chrM", "refseq", "NC_001807.4") in facts
    assert ("chrM", "genbank", "NC_001807.4") not in facts
    assert facts[("chrM", "refseq", "NC_001807.4")] == (
        "upstream with reviewed label correction")
    registry = load_registry("hg19")
    seq_id = registry.resolve("NC_001807.4").seq_id
    assert registry.render(seq_id, "refseq").alias == "NC_001807.4"
    assert not registry.render(seq_id, "genbank").rendered


def test_only_hg19_needs_a_label_correction():
    assert {a for a, e in ref.sources().items()
            if e.get("label_corrections")} == {"hg19"}


# ---- Ensembl evidence -------------------------------------------------------

@pytest.mark.parametrize("assembly", EVIDENCE_ASSEMBLIES)
class TestEnsemblEvidence:
    def test_every_ensembl_alias_comes_from_pinned_evidence(self, assembly):
        entry = ref.sources()[assembly]
        oracle = ORACLES[assembly]
        assert not [r for r in ref.read_upstream_rows(entry)
                    if "ensembl" in r[2].split(",")]  # evidence-only source
        ensembl = {f: why for f, why in oracle.facts.items()
                   if f[1] == "ensembl"}
        assert ensembl
        assert set(ensembl.values()) == {
            "pinned Ensembl evidence (exact accession)"}

    def test_each_enriched_alias_matches_an_exact_versioned_accession(
            self, assembly):
        entry = ref.sources()[assembly]
        rows = ref.apply_corrections(
            ref.read_upstream_rows(entry), entry["label_corrections"])[0]
        accession_owner = {}
        for alias, chrom, source in rows:
            for label in source.split(","):
                if label in ("genbank", "refseq"):
                    accession_owner[(label, alias)] = chrom
        evidence = {r["ensembl_name"]: r for r in ref.read_evidence_rows(entry)
                    if r["toplevel"] == "1"}
        registry = load_registry(assembly)
        enriched = 0
        for chrom, authority, name in ORACLES[assembly].facts:
            if authority != "ensembl":
                continue
            region = evidence[name]
            owners = {accession_owner[(label, region[column])]
                      for column, label in (("insdc", "genbank"),
                                            ("refseq", "refseq"))
                      if region[column]
                      and (label, region[column]) in accession_owner}
            assert owners == {chrom}, (name, chrom, owners)
            assert registry.render(
                registry.resolve(chrom).seq_id, "ensembl").alias == name
            enriched += 1
        assert enriched == len(evidence)

    def test_non_toplevel_regions_add_nothing(self, assembly):
        entry = ref.sources()[assembly]
        added = {f[2] for f in ORACLES[assembly].facts if f[1] == "ensembl"}
        for region in ref.read_evidence_rows(entry):
            if region["toplevel"] != "1":
                assert region["ensembl_name"] not in added


def test_hg19_ensembl_mt_is_matched_by_accession_not_by_ucsc_name():
    """Ensembl's own UCSC synonym for MT says chrM; the accession says chrMT."""
    entry = ref.sources()["hg19"]
    mt = next(r for r in ref.read_evidence_rows(entry)
              if r["ensembl_name"] == "MT")
    assert mt["refseq"] == "NC_012920.1" and mt["ucsc"] == "chrM"
    facts = ORACLES["hg19"].facts
    assert ("chrMT", "ensembl", "MT") in facts
    assert not [f for f in facts if f[0] == "chrM" and f[1] == "ensembl"]
    assert ("NC_012920.1", "chrMT") in {(a, c) for a, c, _ in
                                         ref.read_upstream_rows(entry)}
    assert any(m["ensembl_name"] == "MT" and m["registry_ucsc"] == "chrMT"
               for m in entry["ensembl_evidence"]["ucsc_name_disagreements"])


def test_rn7_uses_release_111_evidence_never_a_later_assembly():
    config = ref.sources()["rn7"]["ensembl_evidence"]
    assert config["ensembl_release"] == 111
    assert config["ensembl_assembly"] == "mRatBN7.2"
    assert "GRCr8" not in config["source_url"]


def test_assemblies_without_evidence_use_only_stated_ensembl_labels():
    for assembly in set(ASSEMBLIES) - set(EVIDENCE_ASSEMBLIES):
        rows = ref.read_upstream_rows(ref.sources()[assembly])
        stated = {(chrom, "ensembl", alias) for alias, chrom, source in rows
                  if "ensembl" in source.split(",")}
        found = {f for f in ORACLES[assembly].facts if f[1] == "ensembl"}
        assert found == stated


# ---- the oracle has teeth ---------------------------------------------------

def _mutated_rows(assembly, mutate):
    rows = _registry_rows(assembly)
    mutate(rows)
    return rows


def test_oracle_flags_an_invented_alias():
    def mutate(rows):
        next(r for r in rows if r["ucsc"] == "chr1")["ensembl"] = "chr1"
    problems = ref.registry_discrepancies(
        ORACLES["GRCh38"], _mutated_rows("GRCh38", mutate))
    assert any(p.startswith("unsupported alias ('chr1', 'ensembl', 'chr1')")
               for p in problems)


def test_oracle_flags_an_alias_moved_to_the_wrong_record():
    def mutate(rows):
        a = next(r for r in rows if r["ucsc"] == "chr1")
        b = next(r for r in rows if r["ucsc"] == "chr2")
        a["refseq"], b["refseq"] = b["refseq"], a["refseq"]
    problems = ref.registry_discrepancies(
        ORACLES["GRCh38"], _mutated_rows("GRCh38", mutate))
    assert any("unsupported alias" in p for p in problems)
    assert any("missing alias" in p for p in problems)


def test_oracle_flags_a_name_inferred_ensembl_alias_for_hg19_chrM():
    def mutate(rows):
        next(r for r in rows if r["ucsc"] == "chrM")["ensembl"] = "MT"
    problems = ref.registry_discrepancies(
        ORACLES["hg19"], _mutated_rows("hg19", mutate))
    assert problems == ["unsupported alias ('chrM', 'ensembl', 'MT')"]


def test_oracle_flags_a_missing_alias_and_an_unlabelled_correction():
    def mutate(rows):
        next(r for r in rows if r["ucsc"] == "chrM")["refseq"] = ""
        next(r for r in rows if r["ucsc"] == "chrM")["genbank"] = "NC_001807.4"
    problems = ref.registry_discrepancies(
        ORACLES["hg19"], _mutated_rows("hg19", mutate))
    assert "missing alias ('chrM', 'refseq', 'NC_001807.4')" in problems
    assert "unsupported alias ('chrM', 'genbank', 'NC_001807.4')" in problems


def test_oracle_detects_conflicting_inputs():
    rows = [("a", "chr1", "assembly"), ("a", "chr2", "assembly")]
    oracle = ref.build_oracle("GRCh38", rows=rows, corrections=[])
    assert any("several records" in c for c in oracle.conflicts)
    rows = [("a", "chr1", "assembly"), ("b", "chr1", "assembly")]
    oracle = ref.build_oracle("GRCh38", rows=rows, corrections=[])
    assert any("several assembly aliases" in c for c in oracle.conflicts)


def test_oracle_rejects_ensembl_evidence_without_an_exact_accession_match():
    entry = ref.sources()["hg19"]
    rows = ref.apply_corrections(ref.read_upstream_rows(entry),
                                 entry["label_corrections"])[0]
    bogus = [{"ensembl_name": "99", "coord_system": "chromosome",
              "length": "1", "toplevel": "1", "insdc": "CM000663",   # no version
              "refseq": "", "ucsc": ""}]
    oracle = ref.build_oracle("hg19", rows=rows, evidence=bogus)
    assert any("matches 0 records" in c for c in oracle.conflicts)
    assert not [f for f in oracle.facts if f[2] == "99"]
