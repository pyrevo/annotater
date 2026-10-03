#!/usr/bin/env python3
"""Derive the bundled assembly catalog from the committed UCSC audit.

The bundle is selected mechanically from the audit snapshot named in
``sources.json`` (``bundle_policy``): every database whose audit status is
``PASS`` with at most ``max_sequence_records`` sequences, plus the reviewed
exceptions already in production (hg19: PASS-except-for-one-reviewed-label-
correction). REVIEW, FAIL and NO_SOURCE assemblies are never imported
automatically.

    python scripts/update_chrom_catalog.py --check
        offline: the manifest equals the policy, every pin matches its
        committed file, every registry equals a rebuild, catalog.json is
        current (default)
    python scripts/update_chrom_catalog.py --write --cache-dir DIR [--fetch]
        import missing assemblies from the audit cache (``--fetch`` downloads
        missing sources first); each source must still match the audit
        snapshot, otherwise that assembly is reported as drift and skipped

Only ``--fetch`` uses the network. The application never does.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.core.chrom_registry import builder
from streamlit_app.core.chrom_registry.catalog import (
    SCHEMA_VERSION,
    AssemblyInfo,
    identity_problems,
)

PACKAGE = builder.PACKAGE_DIR
SOURCE_FORMAT = "ucsc-chromAlias-table: alias<TAB>chrom<TAB>source"


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_chrom_alias_catalog",
        ROOT / "scripts" / "audit_chrom_alias_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_report(policy: dict, root: Path = ROOT) -> dict:
    return json.loads((root / policy["audit_snapshot"]).read_text())


# --------------------------------------------------------------------------
# Selection policy
# --------------------------------------------------------------------------

def select_bundle(report: dict, policy: dict) -> list[dict]:
    """Audit entries to bundle, ordered by UCSC database id.

    ``PASS`` and ``sequence_records <= max_sequence_records``, plus the
    named ``reviewed_exceptions`` (which must exist in the audit).
    """
    by_db = {a["db"]: a for a in report["assemblies"]}
    missing = [db for db in policy["reviewed_exceptions"] if db not in by_db]
    if missing:
        raise ValueError(f"reviewed exceptions not in the audit: {missing}")
    chosen = {
        a["db"]: a for a in report["assemblies"]
        if a["status"] in policy["include_status"]
        and a["sequence_records"] <= policy["max_sequence_records"]
    }
    for db in policy["reviewed_exceptions"]:
        chosen[db] = by_db[db]
    return [chosen[db] for db in sorted(chosen)]


def make_label(organism: str | None, description: str | None, db: str) -> str:
    """User-facing option text from UCSC metadata, verbatim.

    ``<organism> — <description>`` (surrounding whitespace in UCSC's values
    is trimmed for display only); the database id is appended only when
    the description does not already contain it, so searching for a db id
    (for example ``canFam3``) always finds the assembly.
    """
    organism = (organism or "").strip() or db
    description = (description or "").strip() or db
    label = f"{organism} — {description}"
    return label if db in label else f"{label} [{db}]"


def sort_key(info: dict):
    return ((info["organism"] or "").casefold(),
            info["scientific_name"] or "", info["ucsc_db"])


BASIS_DB = "ucsc-db"
BASIS_TOKEN = "ucsc-description-token"


def canonical_identity(entry: dict, policy: dict) -> tuple[str, str]:
    """``(canonical_id, basis)`` of a manifest entry under the policy.

    The canonical id is the UCSC database id unless the reviewed
    ``canonical_id_overrides`` names a published assembly name for it. An
    override is accepted only when UCSC's own description contains it
    verbatim as the ``(<name>/<db>)`` token, so a name is never invented
    and no prose is parsed.
    """
    db = entry["ucsc_db"]
    name = policy.get("canonical_id_overrides", {}).get(db)
    if name is None:
        return db, BASIS_DB
    description = entry["catalog"]["description"] or ""
    if f"({name}/{db})" not in description:
        raise ValueError(
            f"{db}: canonical id {name!r} is not the '({name}/{db})' token "
            f"of the UCSC description {description!r}")
    return name, BASIS_TOKEN


def accepted_aliases(entry: dict, canonical_id: str) -> list[str]:
    """Other accepted names: the UCSC db and the previous runtime id."""
    return sorted({entry["ucsc_db"], entry["assembly_id"]} - {canonical_id})


def build_catalog(manifest: dict) -> dict:
    """``catalog.json`` content derived from the manifest (deterministic)."""
    policy = manifest["bundle_policy"]
    infos = []
    for entry in manifest["assemblies"]:
        meta = entry["catalog"]
        canonical_id, _ = canonical_identity(entry, policy)
        infos.append({
            "canonical_id": canonical_id,
            "ucsc_db": entry["ucsc_db"],
            "aliases": accepted_aliases(entry, canonical_id),
            "display_label": make_label(meta["organism"], meta["description"],
                                        entry["ucsc_db"]),
            "organism": meta["organism"],
            "scientific_name": meta["scientific_name"],
            "description": meta["description"],
            "registry_file": entry["registry_file"],
        })
    infos.sort(key=sort_key)
    labels = [i["display_label"] for i in infos]
    duplicated = sorted({label for label in labels if labels.count(label) > 1})
    if duplicated:
        raise ValueError(f"duplicate display labels: {duplicated}")
    problems = identity_problems(
        [AssemblyInfo(**{**i, "aliases": tuple(i["aliases"])}) for i in infos])
    if problems:
        raise ValueError(f"assembly identity errors: {problems}")
    return {"schema_version": SCHEMA_VERSION, "assemblies": infos}


def dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# Manifest entries
# --------------------------------------------------------------------------

def catalog_block(audit_entry: dict) -> dict:
    return {
        "organism": audit_entry["organism"],
        "common_name": audit_entry["common_name"],
        "scientific_name": audit_entry["scientific_name"],
        "tax_id": audit_entry["tax_id"],
        "description": audit_entry["assembly_name"],
        "source_name": audit_entry["source_name"],
    }


def audit_block(audit_entry: dict, report: dict) -> dict:
    return {
        "audit_date": report["audit"]["audit_date"],
        "audit_catalog_sha256": report["audit"]["catalog_sha256"],
        "status": audit_entry["status"],
        "reason_codes": audit_entry["reason_codes"],
        "sequence_records": audit_entry["sequence_records"],
        "alias_rows": audit_entry["alias_rows"],
    }


def new_entry(audit_entry: dict, report: dict, last_modified: str,
              policy: dict | None = None) -> dict:
    db = audit_entry["db"]
    entry = {
        "assembly_id": db,
        "ucsc_db": db,
        "source_url": audit_entry["alias_url"],
        "source_format": SOURCE_FORMAT,
        "upstream_file": f"upstream/{db}.chromAlias.txt.gz",
        "sha256": audit_entry["source_sha256"],
        "upstream_last_modified": last_modified,
        "retrieved": report["audit"]["audit_date"],
        "registry_file": f"data/{db}.tsv",
        "label_corrections": [],
        "catalog": catalog_block(audit_entry),
        "audit": audit_block(audit_entry, report),
    }
    return with_identity(entry, policy or {})


def with_identity(entry: dict, policy: dict) -> dict:
    """``entry`` with its canonical id and the basis it rests on."""
    entry = dict(entry)
    entry["canonical_id"], entry["canonical_id_basis"] = canonical_identity(
        entry, policy)
    return entry


def annotate_existing(entry: dict, audit_entry: dict, report: dict,
                      policy: dict | None = None) -> dict:
    """Existing reviewed entries keep every field; metadata blocks are added."""
    entry = dict(entry)
    entry["catalog"] = catalog_block(audit_entry)
    entry["audit"] = audit_block(audit_entry, report)
    return with_identity(entry, policy or {})


def bundle_facts(manifest: dict, report: dict) -> dict:
    """Release facts about the bundle (recorded for the documentation)."""
    policy = manifest["bundle_policy"]
    audited = {a["db"]: a for a in report["assemblies"]}
    bundled = [audited[e["ucsc_db"]] for e in manifest["assemblies"]]
    by_status = {}
    for a in report["assemblies"]:
        by_status.setdefault(a["status"], []).append(a["db"])
    dbs = {a["db"] for a in bundled}
    return {
        "audit": {
            "date": report["audit"]["audit_date"],
            "catalog_url": report["audit"]["catalog_url"],
            "catalog_sha256": report["audit"]["catalog_sha256"],
            "candidates": report["summary"]["candidates"],
            "with_chrom_alias": report["summary"]["with_chrom_alias"],
            "status_counts": report["summary"]["status_counts"],
        },
        "selection_rule": {k: policy[k] for k in (
            "include_status", "max_sequence_records", "reviewed_exceptions")},
        "bundled": {
            "assemblies": len(bundled),
            "species": len({a["scientific_name"] for a in bundled}),
            "imported_by_rule": len([a for a in bundled if a["status"]
                                     == "PASS"]),
            "reviewed_exceptions": sorted(
                a["db"] for a in bundled if a["status"] != "PASS"),
            "ucsc_dbs": sorted(dbs),
            "canonical_ids": [e["canonical_id"] for e in manifest["assemblies"]],
            "tsv_bytes_estimate": sum(a["estimated_tsv_bytes"]
                                      for a in bundled),
        },
        "excluded": {
            "review": sorted(set(by_status.get("REVIEW", [])) - dbs),
            "fail": sorted(by_status.get("FAIL", [])),
            "no_source": len(by_status.get("NO_SOURCE", [])),
            "pass_over_size_cap": sorted(
                a["db"] for a in report["assemblies"]
                if a["status"] == "PASS" and a["db"] not in dbs),
        },
        "authority_coverage_bundled_assemblies": {
            authority: sum(1 for a in bundled
                           if authority in a["authorities_present"])
            for authority in ("ucsc", "assembly", "ensembl", "genbank",
                              "refseq")},
        "statements": [
            ("Runtime use is fully offline: every bundled registry ships "
             "with the application and nothing is fetched."),
            ("Authority coverage is partial by design: a recognized sequence "
             "without a verified alias for the requested naming is reported "
             "as unavailable, never guessed."),
            ("REVIEW, FAIL and NO_SOURCE assemblies are not imported "
             "automatically."),
        ],
    }


# --------------------------------------------------------------------------
# Drift gate
# --------------------------------------------------------------------------

def drift(audit_module, audit_entry: dict, data: bytes) -> list[str]:
    """Reasons this source no longer matches the audit snapshot (or [])."""
    sha = hashlib.sha256(data).hexdigest()
    if sha != audit_entry["source_sha256"]:
        return [f"checksum {sha} != audited {audit_entry['source_sha256']}"]
    fresh = audit_module.audit_source({"db": audit_entry["db"]}, data, 200)
    return [f"{key} {fresh[key]!r} != audited {audit_entry[key]!r}"
            for key in ("status", "alias_rows", "sequence_records")
            if fresh[key] != audit_entry[key]]


# --------------------------------------------------------------------------
# Check / write
# --------------------------------------------------------------------------

def check(root: Path = ROOT, package: Path = PACKAGE) -> list[str]:
    """Offline consistency problems of the committed catalog (empty = ok)."""
    manifest = json.loads((package / "sources.json").read_text())
    policy = manifest["bundle_policy"]
    report = load_report(policy, root)
    problems = []
    expected = {a["db"]: a for a in select_bundle(report, policy)}
    actual = {e["ucsc_db"]: e for e in manifest["assemblies"]}
    if set(expected) != set(actual):
        problems.append(
            f"bundle differs from policy: missing "
            f"{sorted(set(expected) - set(actual))}, unexpected "
            f"{sorted(set(actual) - set(expected))}")
    for db, entry in sorted(actual.items()):
        audit_entry = expected.get(db)
        if audit_entry is None:
            continue
        if entry.get("catalog") != catalog_block(audit_entry):
            problems.append(f"{db}: catalog metadata differs from the audit")
        if entry.get("audit") != audit_block(audit_entry, report):
            problems.append(f"{db}: audit provenance differs from the snapshot")
        try:
            identity = canonical_identity(entry, policy)
        except ValueError as exc:
            problems.append(str(exc))
        else:
            if (entry.get("canonical_id"),
                    entry.get("canonical_id_basis")) != identity:
                problems.append(
                    f"{db}: canonical id {entry.get('canonical_id')!r} "
                    f"differs from the policy ({identity[0]!r})")
        if entry["sha256"] != audit_entry["source_sha256"]:
            problems.append(f"{db}: pinned checksum differs from the audit")
        try:
            builder.check(entry, package)
        except (builder.RegistryBuildError, OSError) as exc:
            problems.append(f"{db}: {exc}")
    facts = root / policy["facts_file"]
    if not facts.exists() or facts.read_text() != dump(
            bundle_facts(manifest, report)):
        problems.append(f"{policy['facts_file']} differs from the manifest")
    try:
        if (package / "catalog.json").read_text() != dump(
                build_catalog(manifest)):
            problems.append("catalog.json differs from the manifest")
    except (ValueError, OSError) as exc:
        problems.append(f"catalog.json: {exc}")
    return problems


def write(cache_dir: Path, fetch=None, root: Path = ROOT,
          package: Path = PACKAGE, out=None) -> int:
    """Import missing assemblies from the audit cache; refuse on drift."""
    out = out or sys.stdout
    audit = _audit_module()
    manifest = json.loads((package / "sources.json").read_text())
    policy = manifest["bundle_policy"]
    report = load_report(policy, root)
    cache = audit.Cache(cache_dir)
    existing = {e["ucsc_db"]: e for e in manifest["assemblies"]}
    drifted, imported = [], []
    for audit_entry in select_bundle(report, policy):
        db = audit_entry["db"]
        if db in existing:
            continue
        cached = cache.load_source(db)
        if cached is None and fetch is not None:
            status, data, modified = fetch(audit_entry["alias_url"])
            if status == 200:
                cache.store_source(db, status, data, modified)
            cached = cache.load_source(db)
        if cached is None or cached[1] is None:
            drifted.append((db, ["source not in the cache"]))
            continue
        problems = drift(audit, audit_entry, cached[1])
        if problems:
            drifted.append((db, problems))
            continue
        modified = json.loads(cache.meta_path(db).read_text()).get(
            "last_modified", "")
        entry = new_entry(audit_entry, report, modified, policy)
        (package / entry["upstream_file"]).write_bytes(cached[1])
        imported.append(entry)
    for db, problems in drifted:
        print(f"DRIFT {db}: {'; '.join(problems)}", file=out)
    audited = {a["db"]: a for a in select_bundle(report, policy)}
    # Existing entries keep their position and fields; new ones follow by db.
    entries = [annotate_existing(e, audited[e["ucsc_db"]], report, policy)
               for e in manifest["assemblies"] if e["ucsc_db"] in audited]
    entries += sorted(imported, key=lambda e: e["ucsc_db"])
    manifest["assemblies"] = entries
    (package / "sources.json").write_text(dump(manifest))
    for entry in entries:
        builder.write(entry, package)
    (package / "catalog.json").write_text(dump(build_catalog(manifest)))
    facts = root / policy["facts_file"]
    facts.parent.mkdir(parents=True, exist_ok=True)
    facts.write_text(dump(bundle_facts(manifest, report)))
    print(f"bundled assemblies: {len(entries)} "
          f"({len(imported)} imported, {len(drifted)} drifted)", file=out)
    return 1 if drifted else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        if args.cache_dir is None:
            parser.error("--write needs --cache-dir")
        fetch = _audit_module().http_fetch if args.fetch else None
        return write(args.cache_dir, fetch)
    problems = check()
    for problem in problems:
        print(problem)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
