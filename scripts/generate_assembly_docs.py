#!/usr/bin/env python3
"""Render the catalog-derived facts in the user documentation.

The bundled-assembly reference and the catalog-audit figures are generated
from the runtime catalog (``catalog.json``) and the committed audit
(``audits/chrom_alias_catalog/``), never typed by hand, so the docs cannot
drift from what the release ships.

    python scripts/generate_assembly_docs.py          regenerate the blocks
    python scripts/generate_assembly_docs.py --check  fail if docs are stale

Only text between these marker lines is ever replaced:

    <!-- BEGIN CATALOG: <block> -->
    <!-- END CATALOG: <block> -->
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "streamlit_app" / "core" / "chrom_registry" / "catalog.json"
AUDIT_DIR = ROOT / "audits" / "chrom_alias_catalog"
DOCS = ROOT / "docs"

# block name -> page that must contain exactly one marker pair for it
PAGES = {
    "bundled_assemblies": DOCS / "preparing-your-data" / "bundled-assemblies.md",
    "catalog_audit": DOCS / "technical" / "chromosome-registry.md",
    "authority_coverage": DOCS / "technical" / "chromosome-registry.md",
}

NAMING_LABELS = {
    "ucsc": "UCSC names",
    "assembly": "Assembly names",
    "ensembl": "Ensembl names",
    "refseq": "NCBI RefSeq accessions",
    "genbank": "GenBank accessions",
}

BEGIN_RE = re.compile(r"^<!-- BEGIN CATALOG: ([a-z_]+) -->$", re.MULTILINE)


class DocsError(ValueError):
    pass


def _cell(text) -> str:
    return "—" if text in (None, "") else str(text).replace("|", "\\|")


def _megabytes(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


def _facts() -> tuple[dict, dict]:
    facts = json.loads((AUDIT_DIR / "bundle_facts.json").read_text("utf-8"))
    report = json.loads((AUDIT_DIR / "report.json").read_text("utf-8"))
    return facts, report


def render_bundled_assemblies() -> str:
    catalog = json.loads(CATALOG.read_text("utf-8"))["assemblies"]
    species = {a["scientific_name"] for a in catalog}
    lines = [
        (f"{len(catalog)} genome assemblies of {len(species)} species are "
         "bundled in this release, listed here in the order of the "
         "**Genome assembly** selector. The selector label is what you "
         "choose in the application; the AnnotateR id and the UCSC "
         "database id are the names used for the same assembly elsewhere, "
         "and both are accepted wherever an assembly id is accepted."),
        "",
        ("| Organism | Scientific name | Selector label | AnnotateR id "
         "| UCSC database |"),
        "|---|---|---|---|---|",
    ]
    for a in catalog:
        lines.append("| " + " | ".join(_cell(x) for x in (
            a["organism"], a["scientific_name"], a["display_label"],
            a["canonical_id"], a["ucsc_db"])) + " |")
    return "\n".join(lines)


def render_catalog_audit() -> str:
    facts, report = _facts()
    audit, bundled = facts["audit"], facts["bundled"]
    counts = audit["status_counts"]
    rule = facts["selection_rule"]
    total_bytes = report["summary"]["pass_size"]["tsv_bytes_total"]
    gz_bytes = report["summary"]["pass_size"]["tsv_gzip_bytes_total"]
    rows = [
        ("UCSC genome databases audited", audit["candidates"]),
        ("…with a database `chromAlias` source", audit["with_chrom_alias"]),
        ("…representable cleanly by the current architecture",
         counts["PASS"]),
        ("…requiring review", counts["REVIEW"]),
        ("…failing the current representation", counts["FAIL"]),
        ("…with no database `chromAlias` source", counts["NO_SOURCE"]),
        ("**Bundled in this release**",
         (f"**{bundled['assemblies']} assemblies, {bundled['species']} "
          "species**")),
        ("…selected by the bundling policy", bundled["imported_by_rule"]),
        ("…reviewed exception (`" + "`, `".join(bundled["reviewed_exceptions"])
         + "`, one of the databases requiring review)",
         len(bundled["reviewed_exceptions"])),
        ("Clean assemblies not bundled (above the size limit)",
         len(facts["excluded"]["pass_over_size_cap"])),
    ]
    lines = [
        f"Audit of {audit['date']} against the UCSC genome catalog.",
        "",
        "| | Count |",
        "|---|---|",
        *(f"| {label} | {value} |" for label, value in rows),
        "",
        ("The bundling policy selects every cleanly representable assembly "
         f"with at most {rule['max_sequence_records']:,} sequence records, "
         "plus the reviewed exception. Registries for all "
         f"{counts['PASS']} clean assemblies would total about "
         f"{_megabytes(total_bytes)} of registry text "
         f"({_megabytes(gz_bytes)} compressed); the bundled registries "
         f"total about {_megabytes(bundled['tsv_bytes_estimate'])}."),
    ]
    return "\n".join(lines)


def render_authority_coverage() -> str:
    facts, _ = _facts()
    total = facts["bundled"]["assemblies"]
    coverage = facts["authority_coverage_bundled_assemblies"]
    lines = [
        "| Naming system | Bundled registries with at least one name |",
        "|---|---|",
    ]
    for authority, label in NAMING_LABELS.items():
        lines.append(f"| {label} | {coverage[authority]} of {total} |")
    return "\n".join(lines)


RENDERERS = {
    "bundled_assemblies": render_bundled_assemblies,
    "catalog_audit": render_catalog_audit,
    "authority_coverage": render_authority_coverage,
}


def replace_block(text: str, name: str, body: str, source: str) -> str:
    begin = f"<!-- BEGIN CATALOG: {name} -->"
    end = f"<!-- END CATALOG: {name} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise DocsError(f"{source}: needs exactly one {begin} / {end} pair")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{begin}\n{body}\n{end}{tail}"


def run(*, check: bool = False, out=sys.stdout) -> int:
    names = set(RENDERERS)
    for page in set(PAGES.values()):
        found = set(BEGIN_RE.findall(page.read_text("utf-8")))
        expected = {n for n, p in PAGES.items() if p == page}
        if found != expected:
            raise DocsError(
                f"{page}: catalog blocks {sorted(found)} != {sorted(expected)}")
    stale = []
    for page in sorted(set(PAGES.values())):
        old = page.read_text("utf-8")
        new = old
        for name, target in PAGES.items():
            if target == page:
                new = replace_block(new, name, RENDERERS[name](), str(page))
        if new != old:
            stale.append(page)
            if not check:
                page.write_text(new, "utf-8")
    assert names == set(PAGES)
    for page in stale:
        print(f"{'stale' if check else 'updated'}: {page.relative_to(ROOT)}",
              file=out)
    if check and stale:
        print("Generated catalog blocks are out of date; run "
              "`python scripts/generate_assembly_docs.py`.", file=out)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if docs differ; write nothing")
    args = parser.parse_args(argv)
    try:
        return run(check=args.check)
    except DocsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
