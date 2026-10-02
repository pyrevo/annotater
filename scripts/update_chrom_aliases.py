#!/usr/bin/env python3
"""Build or verify the offline chromosome-alias registry (build-time only).

    python scripts/update_chrom_aliases.py --check     verify checksum and that
                                                       the committed registry
                                                       equals a rebuild (default)
    python scripts/update_chrom_aliases.py --write     rebuild the registry from
                                                       the committed upstream file
    python scripts/update_chrom_aliases.py --fetch     download upstream and
                                                       compare with the pin; a
                                                       difference is a hard stop
    python scripts/update_chrom_aliases.py --fetch --accept-upstream-update
                                                       re-pin new upstream data
                                                       (then --write and review)

Only --fetch uses the network. The application never does.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date

from streamlit_app.core.chrom_registry import builder, ensembl_evidence


def _fetch(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read(), response.headers.get("Last-Modified", "")


def _fetch_ensembl(entry, args, fetch) -> bool:
    """Compare live pinned Ensembl tables and the derived evidence file.
    Returns True when the configuration was re-pinned."""
    config = entry["ensembl_evidence"]
    tables = {name: fetch(config["source_url"] + name)[0]
              for name in ensembl_evidence.TABLES}
    try:
        ensembl_evidence.verify_tables(tables, config)
    except builder.RegistryBuildError:
        if not args.accept_upstream_update:
            raise
        config["tables"] = {n: builder.sha256_hex(b)
                            for n, b in tables.items()}
        config["retrieved"] = date.today().isoformat()
        text = ensembl_evidence.extract_evidence(
            tables, config["coord_system_version"])
        (builder.PACKAGE_DIR / config["evidence_file"]).write_bytes(
            text.encode("utf-8"))
        config["evidence_sha256"] = builder.sha256_hex(text.encode("utf-8"))
        return True
    text = ensembl_evidence.extract_evidence(
        tables, config["coord_system_version"])
    committed = (builder.PACKAGE_DIR / config["evidence_file"]).read_bytes()
    if committed != text.encode("utf-8"):
        raise builder.RegistryBuildError(
            f"{entry['assembly_id']}: committed Ensembl evidence differs "
            "from extraction of the pinned tables")
    return False


def run(args, fetch=_fetch) -> int:
    config = builder.load_sources()
    entries = [e for e in config["assemblies"]
               if args.assembly in (None, e["assembly_id"])]
    if not entries:
        raise builder.RegistryBuildError(f"unknown assembly {args.assembly!r}")
    for entry in entries:
        name = entry["assembly_id"]
        if args.fetch:
            data, last_modified = fetch(entry["source_url"])
            repinned = False
            if entry.get("ensembl_evidence"):
                repinned = _fetch_ensembl(entry, args, fetch)
                if repinned:
                    builder.SOURCES_FILE.write_text(
                        json.dumps(config, indent=2) + "\n",
                        encoding="utf-8")
                    print(f"{name}: Ensembl evidence re-pinned")
                else:
                    print(f"{name}: Ensembl evidence unchanged")
            if builder.sha256_hex(data) == entry["sha256"]:
                print(f"{name}: upstream unchanged")
            elif not args.accept_upstream_update:
                raise builder.RegistryBuildError(
                    f"{name}: upstream changed (SHA-256 "
                    f"{builder.sha256_hex(data)} != pinned {entry['sha256']}); "
                    "rerun with --accept-upstream-update to re-pin"
                )
            else:
                builder.accept_upstream(
                    entry, data, last_modified, date.today().isoformat())
                builder.SOURCES_FILE.write_text(
                    json.dumps(config, indent=2) + "\n", encoding="utf-8")
                print(f"{name}: re-pinned; run --write and review the diff")
        elif args.write:
            builder.write(entry)
            print(f"{name}: wrote {entry['registry_file']}")
        else:
            builder.check(entry)
            print(f"{name}: OK")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--assembly", help="assembly_id (default: all)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--fetch", action="store_true")
    parser.add_argument("--accept-upstream-update", action="store_true")
    args = parser.parse_args(argv)
    if args.accept_upstream_update and not args.fetch:
        parser.error("--accept-upstream-update requires --fetch")
    try:
        return run(args)
    except builder.RegistryBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
