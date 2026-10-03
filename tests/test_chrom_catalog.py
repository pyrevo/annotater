"""Bundled assembly catalog: derivation, integrity and runtime smoke tests.

The bundle is derived mechanically from the committed UCSC audit snapshot
(PASS and at most 10,000 sequences, plus the reviewed production exception
hg19). Broad coverage here is structural; the six deeply validated assemblies
keep their semantic, parity and GUI tests elsewhere. Offline throughout.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import (
    AUTHORITIES,
    assembly_options,
    builder,
    load_catalog,
    load_registry,
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
REPORT = json.loads((ROOT / POLICY["audit_snapshot"]).read_text())
AUDIT = {a["db"]: a for a in REPORT["assemblies"]}
CATALOG = load_catalog()
SIX = ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "rn7"]

# SHA-256 of the six production registries before the catalog expansion.
SIX_SHA256 = {
    "GRCh38": "60a9ccb93254d274fa86a5b8a60d1c1c0b6b58fa6373d47f884d4b11bf8f3277",
    "hg19": "009528f868d63220fba9c9f40705783ed64e8fd9c201a434046e3d14d5220f72",
    "GRCm39": "727153fef045146d9fa04e100c7802cb772f0bfd33df13b865ea1a4f942e4024",
    "dm6": "6dfb77eb69a742aadad4a21e8b3ac30e42e66db13273d544d3d72f0569ea0d0d",
    "GRCz11": "cb1fe78feefee8d570b0c8caa6f32e736cbc4d0f6d63765d5eaebc331f3b41be",
    "rn7": "225d09bf933eb0bd0215eecddd47886c7b58084988801c3156268616133b98c9",
}


# ---- selection policy ---------------------------------------------------------

def _audit(db, status="PASS", seqs=10, organism="Org", sci="Org sp"):
    return {"db": db, "status": status, "sequence_records": seqs,
            "organism": organism, "scientific_name": sci}


def test_policy_selects_pass_up_to_the_cap_plus_reviewed_exceptions():
    report = {"assemblies": [
        _audit("a1"), _audit("a2", seqs=10_000), _audit("a3", seqs=10_001),
        _audit("r1", "REVIEW"), _audit("f1", "FAIL"),
        _audit("n1", "NO_SOURCE", seqs=None) | {"sequence_records": None},
        _audit("h1", "REVIEW")]}
    policy = {"include_status": ["PASS"], "max_sequence_records": 10_000,
              "reviewed_exceptions": ["h1"]}
    assert [a["db"] for a in tool.select_bundle(report, policy)] == [
        "a1", "a2", "h1"]


def test_unknown_reviewed_exception_is_an_error():
    with pytest.raises(ValueError, match="not in the audit"):
        tool.select_bundle({"assemblies": []},
                           {"include_status": ["PASS"],
                            "max_sequence_records": 1,
                            "reviewed_exceptions": ["nope"]})


def test_committed_bundle_is_exactly_what_the_policy_derives():
    derived = {a["db"] for a in tool.select_bundle(REPORT, POLICY)}
    assert derived == {e["ucsc_db"] for e in MANIFEST["assemblies"]}
    assert derived == {i.ucsc_db for i in CATALOG}
    assert len(derived) == 64
    assert tool.check() == []


def test_policy_values_match_the_task_decision():
    assert POLICY["include_status"] == ["PASS"]
    assert POLICY["max_sequence_records"] == 10_000
    assert POLICY["reviewed_exceptions"] == ["hg19"]


def test_every_bundled_assembly_is_pass_under_the_cap_or_the_hg19_exception():
    for info in CATALOG:
        a = AUDIT[info.ucsc_db]
        if info.ucsc_db == "hg19":
            assert a["status"] == "REVIEW"      # reviewed correction, kept
        else:
            assert a["status"] == "PASS", info.ucsc_db
            assert a["sequence_records"] <= 10_000, info.ucsc_db


def test_all_clean_small_pass_assemblies_are_bundled():
    small = {a["db"] for a in REPORT["assemblies"]
             if a["status"] == "PASS" and a["sequence_records"] <= 10_000}
    assert len(small) == 63
    assert small <= {i.ucsc_db for i in CATALOG}


def test_review_fail_and_missing_source_assemblies_are_not_bundled():
    bundled = {i.ucsc_db for i in CATALOG}
    for db in ("panTro6", "bosTau8", "thaSir1", "manPen1"):     # REVIEW
        assert db not in bundled
    for db in ("anoGam3", "gorGor4", "rn6", "panPan3", "xenTro9"):    # FAIL
        assert db not in bundled
    for db in ("hs1", "mm9", "hg18", "dm3", "ce10"):            # NO_SOURCE
        assert db not in bundled
    others = {a["db"] for a in REPORT["assemblies"]
              if a["status"] in ("REVIEW", "FAIL", "NO_SOURCE")}
    assert (others - {"hg19"}).isdisjoint(bundled)
    assert not [a for a in REPORT["assemblies"]
                if a["status"] == "PASS" and a["sequence_records"] > 10_000
                and a["db"] in bundled]


def test_species_and_assembly_counts():
    assert len(CATALOG) == 64
    assert len({i.scientific_name for i in CATALOG}) == 46


def test_existing_assemblies_keep_ids_and_registry_bytes():
    names = {n for i in CATALOG for n in i.names}
    assert all(a in names for a in SIX)
    assert [e["assembly_id"] for e in MANIFEST["assemblies"][:6]] == SIX
    for assembly, sha in SIX_SHA256.items():
        data = (PACKAGE / f"data/{assembly}.tsv").read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, assembly


def test_registry_keys_are_the_six_legacy_ids_or_the_ucsc_db_id():
    # ``assembly_id`` in the manifest is the registry's build key (and the
    # namespace of its internal seq ids), not the public identity.
    for entry in MANIFEST["assemblies"]:
        if entry["assembly_id"] not in SIX:
            assert entry["assembly_id"] == entry["ucsc_db"]


# ---- metadata -----------------------------------------------------------------

def test_catalog_metadata_is_the_audited_ucsc_metadata_verbatim():
    for entry in MANIFEST["assemblies"]:
        a, block = AUDIT[entry["ucsc_db"]], entry["catalog"]
        assert block["organism"] == a["organism"]
        assert block["scientific_name"] == a["scientific_name"]
        assert block["description"] == a["assembly_name"]
        assert block["tax_id"] == a["tax_id"]
        assert entry["audit"]["sequence_records"] == a["sequence_records"]
        assert entry["sha256"] == a["source_sha256"]


def test_runtime_catalog_is_derived_from_the_manifest_and_deterministic():
    generated = tool.dump(tool.build_catalog(MANIFEST))
    assert generated == tool.dump(tool.build_catalog(copy.deepcopy(MANIFEST)))
    assert (PACKAGE / "catalog.json").read_text() == generated


def test_catalog_json_carries_only_runtime_fields():
    first = json.loads((PACKAGE / "catalog.json").read_text())["assemblies"][0]
    assert set(first) == {"canonical_id", "ucsc_db", "aliases",
                          "display_label", "organism", "scientific_name",
                          "description", "registry_file"}


def test_catalog_is_in_presentation_order():
    keys = [tool.sort_key({"organism": i.organism,
                           "scientific_name": i.scientific_name,
                           "ucsc_db": i.ucsc_db}) for i in CATALOG]
    assert keys == sorted(keys)


def test_labels_are_unique_clean_and_searchable_by_db_id():
    labels = [i.display_label for i in CATALOG]
    assert len(labels) == len(set(labels))
    for info in CATALOG:
        assert info.display_label == " ".join(info.display_label.split())     # no stray spaces
        assert " — " in info.display_label
        assert info.ucsc_db in info.display_label                     # searchable
        assert info.organism.strip() in info.display_label


def test_duplicate_labels_are_rejected():
    manifest = copy.deepcopy(MANIFEST)
    manifest["assemblies"] = manifest["assemblies"][:1] * 2
    with pytest.raises(ValueError, match="duplicate display labels"):
        tool.build_catalog(manifest)


def test_label_construction():
    assert tool.make_label("Dog ", "Sep. 2011 (Broad CanFam3.1/canFam3)",
                           "canFam3") == \
        "Dog — Sep. 2011 (Broad CanFam3.1/canFam3)"
    assert tool.make_label("Virus", "Jan. 2020 (NC_045512.2)", "wuhCor1") == \
        "Virus — Jan. 2020 (NC_045512.2) [wuhCor1]"
    assert tool.make_label(None, None, "xyz1") == "xyz1 — xyz1"


def test_option_labels_map_back_to_exactly_one_assembly():
    options = assembly_options()
    assert len(options) == len(CATALOG) == len(set(options.values()))
    assert list(options.values()) == [i.canonical_id for i in CATALOG]


# ---- generation (drift gate, determinism) -------------------------------------

def _tiny_environment(tmp_path, sha_override=None, rows=None):
    root = tmp_path / "repo"
    package = root / "pkg"
    (package / "upstream").mkdir(parents=True)
    (package / "data").mkdir()
    data = gzip.compress("\n".join(rows or [
        "1\tchr1\tassembly", "CM000001.1\tchr1\tgenbank",
        "NC_000001.1\tchr1\trefseq"]).encode() + b"\n")
    audit = _load("audit_chrom_alias_catalog")
    meta = {"db": "tstDb1", "organism": "Tst", "common_name": "Tst",
            "scientific_name": "Tst tst", "tax_id": 1,
            "assembly_name": "Jan. 2020 (T/tstDb1)", "source_name": "Lab"}
    audited = audit.audit_source(meta, data, 200)
    audited["alias_url"] = "https://example.invalid/tstDb1"
    if sha_override:
        audited["source_sha256"] = sha_override
    report = {"audit": {"audit_date": "2026-01-01", "catalog_sha256": "c" * 64,
                        "catalog_url": "u"},
              "summary": {"candidates": 1, "with_chrom_alias": 1,
                          "status_counts": {"PASS": 1}},
              "assemblies": [audited]}
    (root / "audits").mkdir()
    (root / "audits" / "report.json").write_text(json.dumps(report))
    policy = {"audit_snapshot": "audits/report.json",
              "include_status": ["PASS"], "max_sequence_records": 10,
              "reviewed_exceptions": [], "facts_file": "audits/facts.json"}
    (package / "sources.json").write_text(json.dumps(
        {"schema_version": 1, "bundle_policy": policy, "assemblies": []}))
    cache = audit.Cache(tmp_path / "cache")
    cache.store_source("tstDb1", 200, data, "Mon, 01 Jan 2026")
    return root, package, tmp_path / "cache"


def test_generation_imports_builds_and_is_idempotent(tmp_path, capsys):
    root, package, cache = _tiny_environment(tmp_path)
    assert tool.write(cache, root=root, package=package) == 0
    manifest = json.loads((package / "sources.json").read_text())
    (entry,) = manifest["assemblies"]
    assert entry["assembly_id"] == "tstDb1" == entry["ucsc_db"]
    assert entry["catalog"]["scientific_name"] == "Tst tst"
    assert entry["audit"]["status"] == "PASS"
    assert (package / "data" / "tstDb1.tsv").read_text().startswith("seq_id\t")
    assert tool.check(root, package) == []
    def snapshot():
        return {str(p.relative_to(root)): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}
    before = snapshot()
    assert tool.write(cache, root=root, package=package) == 0     # idempotent
    assert snapshot() == before


def test_a_source_that_drifted_from_the_audit_is_not_imported(tmp_path, capsys):
    root, package, cache = _tiny_environment(tmp_path, sha_override="0" * 64)
    assert tool.write(cache, root=root, package=package) == 1
    assert "DRIFT tstDb1: checksum" in capsys.readouterr().out
    assert json.loads((package / "sources.json").read_text())[
        "assemblies"] == []
    assert not (package / "data" / "tstDb1.tsv").exists()
    assert not (package / "upstream" / "tstDb1.chromAlias.txt.gz").exists()


def test_a_missing_cached_source_is_reported_not_fetched(tmp_path, capsys):
    root, package, cache = _tiny_environment(tmp_path)
    (cache / "sources" / "tstDb1.meta.json").unlink()
    assert tool.write(cache, root=root, package=package) == 1
    assert "source not in the cache" in capsys.readouterr().out


def test_drift_is_detected_when_the_classification_changed():
    audit = _load("audit_chrom_alias_catalog")
    data = gzip.compress(b"1\tchr1\tassembly\n1\tchr2\tassembly\n")   # collision
    entry = {"db": "x", "source_sha256": hashlib.sha256(data).hexdigest(),
             "status": "PASS", "alias_rows": 2, "sequence_records": 2}
    problems = tool.drift(audit, entry, data)
    assert any(p.startswith("status 'FAIL'") for p in problems)


def test_check_reports_a_tampered_registry(tmp_path):
    root, package, cache = _tiny_environment(tmp_path)
    tool.write(cache, root=root, package=package)
    tsv = package / "data" / "tstDb1.tsv"
    tsv.write_text(tsv.read_text().replace("chr1", "chr9", 1))
    assert any("tstDb1" in p for p in tool.check(root, package))


def test_release_facts_are_recorded_for_the_documentation():
    facts = json.loads((ROOT / POLICY["facts_file"]).read_text())
    assert facts["audit"]["candidates"] == 238
    assert facts["audit"]["with_chrom_alias"] == 132
    assert facts["audit"]["status_counts"] == {
        "FAIL": 5, "NO_SOURCE": 106, "PASS": 122, "REVIEW": 5}
    assert facts["bundled"]["assemblies"] == 64
    assert facts["bundled"]["species"] == 46
    assert facts["bundled"]["reviewed_exceptions"] == ["hg19"]
    assert facts["excluded"]["no_source"] == 106
    assert len(facts["excluded"]["pass_over_size_cap"]) == 122 - 63
    assert any("offline" in s for s in facts["statements"])
    assert any("partial by design" in s for s in facts["statements"])


# ---- runtime smoke over the whole bundle ---------------------------------------

@pytest.mark.parametrize("info", CATALOG, ids=lambda i: i.canonical_id)
def test_bundled_registry_loads_and_resolves_a_representative_alias(info):
    registry = load_registry(info.canonical_id)
    expected = AUDIT[info.ucsc_db]["sequence_records"]
    assert len(registry) == expected > 0
    assert registry.assembly_id == info.canonical_id
    # deterministic representative taken from the registry itself
    seq_id = min(registry)
    record = registry.record(seq_id)
    for authority, alias in sorted(record.aliases.items()):
        assert registry.resolve(alias).seq_id == seq_id
        assert registry.render(seq_id, authority).alias == alias
    assert set(record.aliases) <= set(AUTHORITIES)
    assert registry.render(seq_id, "ucsc").alias == record.aliases["ucsc"]


def test_registries_are_isolated_between_assemblies():
    a, b = load_registry("mm10"), load_registry("canFam3")
    assert a is not b and a.assembly_id == "GRCm38" != b.assembly_id
    # the same string means different sequences (or nothing) per assembly
    assert not b.resolve("CM000994.2").resolved       # mouse chr1 GenBank
    assert a.resolve("CM000994.2").resolved


def test_catalog_read_loads_no_registry():
    load_registry.cache_clear()
    assembly_options()
    load_catalog()
    assert load_registry.cache_info().currsize == 0
    load_registry("ce11")
    assert load_registry.cache_info().currsize == 1


def test_package_size_accounting():
    data = sorted((PACKAGE / "data").glob("*.tsv"))
    assert len(data) == 64
    total = sum(p.stat().st_size for p in data)
    estimate = json.loads((ROOT / POLICY["facts_file"]).read_text())[
        "bundled"]["tsv_bytes_estimate"]
    assert abs(total - estimate) / estimate < 0.02          # audit estimate
    assert total < 16_000_000
    assert max(p.stat().st_size for p in data) < 5_000_000   # 10k-record cap
    assert (PACKAGE / "catalog.json").stat().st_size < 50_000
