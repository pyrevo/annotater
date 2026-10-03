"""Canonical assembly identity: one canonical id, derived aliases, no ambiguity.

Every bundled assembly has exactly one ``canonical_id`` (the identity a
loaded registry reports), its ``ucsc_db`` and the other accepted aliases.
The canonical id is the UCSC database id unless the reviewed policy names a
published assembly name that UCSC's own description contains verbatim.
Offline throughout.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import (
    UnsupportedAssemblyError,
    assembly_options,
    builder,
    canonical_assembly_id,
    find_assembly,
    load_catalog,
    load_registry,
)
from streamlit_app.core.chrom_registry.catalog import (
    AssemblyInfo,
    identity_problems,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = builder.PACKAGE_DIR


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load("update_chrom_catalog")
MANIFEST = json.loads((PACKAGE / "sources.json").read_text())
POLICY = MANIFEST["bundle_policy"]
CATALOG = load_catalog()

# Every id the previous release accepted: the six legacy ids and the UCSC db
# id of each newer assembly. All must still load.
PREVIOUS = [e["assembly_id"] for e in MANIFEST["assemblies"]]


def _info(canonical, *aliases, db=None):
    return AssemblyInfo(canonical, db or canonical, tuple(aliases),
                        f"Label {canonical}", None, None, None,
                        f"data/{canonical}.tsv")


# ---- the identity model --------------------------------------------------------

def test_every_assembly_has_one_canonical_id_and_it_is_unique():
    ids = [i.canonical_id for i in CATALOG]
    assert len(ids) == len(CATALOG) == 64 == len(set(ids))
    assert all(i.canonical_id and isinstance(i.canonical_id, str)
               for i in CATALOG)


def test_aliases_are_unique_across_the_catalog_and_never_a_canonical_id():
    seen = {}
    for info in CATALOG:
        assert info.canonical_id not in info.aliases
        for name in info.names:
            assert name not in seen, (name, seen.get(name), info.canonical_id)
            seen[name] = info.canonical_id
    assert identity_problems(CATALOG) == []


def test_no_two_names_differ_only_in_case():
    names = [n for i in CATALOG for n in i.names]
    assert len({n.casefold() for n in names}) == len(names)


def test_the_ucsc_db_id_is_always_an_accepted_name():
    for info in CATALOG:
        assert info.ucsc_db in info.names


def test_aliases_are_exactly_the_ucsc_db_and_the_previous_runtime_id():
    by_key = {e["assembly_id"]: e for e in MANIFEST["assemblies"]}
    for info in CATALOG:
        expected = {info.ucsc_db} - {info.canonical_id}
        for key, entry in by_key.items():
            if entry["canonical_id"] == info.canonical_id:
                expected |= {key} - {info.canonical_id}
        assert set(info.aliases) == expected
        assert list(info.aliases) == sorted(info.aliases)


def test_documented_examples():
    cases = {"GRCh38": "hg38", "GRCm38": "mm10", "GRCm39": "mm39",
             "GRCz11": "danRer11", "mRatBN7.2": "rn7", "hg19": "hg19"}
    for canonical, db in cases.items():
        info = find_assembly(canonical)
        assert info.canonical_id == canonical and info.ucsc_db == db


# ---- policy: where every canonical id comes from -------------------------------

def test_each_canonical_id_has_a_recorded_basis_that_holds():
    overrides = POLICY["canonical_id_overrides"]
    for entry in MANIFEST["assemblies"]:
        db = entry["ucsc_db"]
        if db in overrides:
            assert entry["canonical_id"] == overrides[db]
            assert entry["canonical_id_basis"] == "ucsc-description-token"
            assert f"({overrides[db]}/{db})" in entry["catalog"]["description"]
        else:
            assert entry["canonical_id"] == db
            assert entry["canonical_id_basis"] == "ucsc-db"


def test_overrides_name_only_bundled_assemblies():
    dbs = {e["ucsc_db"] for e in MANIFEST["assemblies"]}
    assert set(POLICY["canonical_id_overrides"]) <= dbs


def test_hg19_is_not_renamed_to_grch37():
    # UCSC's hg19 carries a different mitochondrial sequence than GRCh37, so
    # GRCh37 would claim the wrong sequence set.
    assert find_assembly("hg19").canonical_id == "hg19"
    assert find_assembly("GRCh37") is None


def test_an_override_must_be_the_verbatim_description_token():
    entry = copy.deepcopy(MANIFEST["assemblies"][0])
    assert tool.canonical_identity(entry, {}) == (entry["ucsc_db"], "ucsc-db")
    policy = {"canonical_id_overrides": {entry["ucsc_db"]: "NotInDescription"}}
    with pytest.raises(ValueError, match="not the"):
        tool.canonical_identity(entry, policy)


def test_names_are_not_invented_from_prose_prefixes():
    # "Broad CanFam3.1/canFam3" carries a prefix; it must not become CanFam3.1
    assert find_assembly("canFam3").canonical_id == "canFam3"
    assert find_assembly("CanFam3.1") is None
    assert find_assembly("dm6").canonical_id == "dm6"


# ---- backward compatibility ----------------------------------------------------

@pytest.mark.parametrize("name", PREVIOUS)
def test_every_previously_accepted_id_still_loads(name):
    registry = load_registry(name)
    assert registry.assembly_id == canonical_assembly_id(name)
    assert name in find_assembly(name).names


@pytest.mark.parametrize("info", CATALOG, ids=lambda i: i.canonical_id)
def test_canonical_id_and_every_alias_return_the_same_registry(info):
    canonical = load_registry(info.canonical_id)
    assert canonical.assembly_id == info.canonical_id
    for alias in info.aliases:
        loaded = load_registry(alias)
        assert loaded is canonical
        assert loaded.assembly_id == info.canonical_id != alias


def test_the_six_named_legacy_ids_remain_accepted():
    for name in ("GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "rn7"):
        assert load_registry(name).assembly_id == canonical_assembly_id(name)


def test_alias_resolves_to_the_canonical_identity():
    assert load_registry("mm10").assembly_id == "GRCm38"
    assert load_registry("GRCm38") is load_registry("mm10")
    assert load_registry("hg38").assembly_id == "GRCh38"
    assert load_registry("rn7").assembly_id == "mRatBN7.2"


@pytest.mark.parametrize("name", [
    "", " GRCh38", "GRCh38 ", "grch38", "GRCH38", "HG38", "Hg19", "mm9",
    "GRCh37", "human", "custom", "Custom chromosome mapping", "../GRCh38"])
def test_unknown_and_inexact_names_still_fail_clearly(name):
    with pytest.raises(UnsupportedAssemblyError, match="supported:"):
        load_registry(name)
    with pytest.raises(UnsupportedAssemblyError):
        canonical_assembly_id(name)


def test_non_string_names_are_unknown_not_a_crash():
    for value in (None, 7, ["GRCh38"]):
        assert find_assembly(value) is None


# ---- registry bytes and behavior unchanged -------------------------------------

def test_registry_files_are_named_after_the_registry_key_not_the_canonical_id():
    # Registry TSVs (and the seq-id namespace inside them) are untouched by
    # the identity change.
    for entry in MANIFEST["assemblies"]:
        assert entry["registry_file"] == f"data/{entry['assembly_id']}.tsv"
    info = find_assembly("mm10")
    assert info.registry_file == "data/mm10.tsv"
    registry = load_registry("GRCm38")
    assert all(seq.startswith("mm10:") for seq in registry)


# ---- ambiguity is rejected at generation and at load ---------------------------

def test_duplicate_canonical_ids_are_rejected():
    problems = identity_problems([_info("A1"), _info("A1", db="b")])
    assert any("used by several" in p for p in problems)


def test_an_alias_on_two_assemblies_is_rejected():
    problems = identity_problems([_info("A1", "x"), _info("B1", "x")])
    assert any("belongs to both" in p for p in problems)


def test_a_canonical_id_equal_to_another_assemblys_alias_is_rejected():
    problems = identity_problems([_info("A1", "B1"), _info("B1")])
    assert any("belongs to both" in p for p in problems)


def test_case_only_differences_are_rejected():
    problems = identity_problems([_info("Abc1"), _info("abc1")])
    assert any("differ only in case" in p for p in problems)


@pytest.mark.parametrize("bad", ["has space", "a/b", "-lead", "", "x;y"])
def test_names_must_be_command_line_safe(bad):
    assert any("invalid name" in p for p in identity_problems([_info(bad)]))


def test_the_generator_refuses_ambiguous_manifests():
    manifest = copy.deepcopy(MANIFEST)
    first, second = manifest["assemblies"][:2]
    second["canonical_id"] = first["canonical_id"]
    manifest["bundle_policy"]["canonical_id_overrides"] = {
        second["ucsc_db"]: first["canonical_id"]}
    second["catalog"]["description"] = (
        f"(({first['canonical_id']}/{second['ucsc_db']})")
    with pytest.raises(ValueError, match="identity errors"):
        tool.build_catalog(manifest)


def test_the_generator_refuses_a_case_collision_between_assemblies():
    manifest = copy.deepcopy(MANIFEST)
    entry = manifest["assemblies"][0]
    twin = copy.deepcopy(manifest["assemblies"][1])
    twin["ucsc_db"] = entry["ucsc_db"].swapcase()
    twin["assembly_id"] = twin["ucsc_db"]
    twin["catalog"]["description"] = twin["catalog"]["description"] + " x"
    manifest["assemblies"] = [entry, twin]
    with pytest.raises(ValueError, match="differ only in case"):
        tool.build_catalog(manifest)


# ---- determinism and GUI mapping -----------------------------------------------

def test_catalog_regeneration_is_deterministic_and_matches_the_committed_file():
    first = tool.dump(tool.build_catalog(MANIFEST))
    assert first == tool.dump(tool.build_catalog(copy.deepcopy(MANIFEST)))
    assert first == (PACKAGE / "catalog.json").read_text()


def test_the_selector_options_map_one_to_one_onto_canonical_assemblies():
    options = assembly_options()
    assert list(options.values()) == [i.canonical_id for i in CATALOG]
    assert len(set(options)) == len(set(options.values())) == 64
    for label, canonical in options.items():
        assert load_registry(canonical).assembly_id == canonical
        assert find_assembly(canonical).display_label == label


def test_display_labels_did_not_change_with_the_identity_policy():
    labels = {i.ucsc_db: i.display_label for i in CATALOG}
    assert labels["hg38"] == "Human — Dec. 2013 (GRCh38/hg38)"
    assert labels["mm10"] == "Mouse — Dec. 2011 (GRCm38/mm10)"
    assert labels["hg19"] == "Human — Feb. 2009 (GRCh37/hg19)"
    assert labels["dm6"].endswith("(BDGP Release 6 + ISO1 MT/dm6)")
