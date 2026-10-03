"""Independent chromosome-alias oracle (test code only).

Derives the expected alias relationships of every configured assembly
directly from the pinned upstream inputs:

* the UCSC ``chromAlias`` table (``alias<TAB>chrom<TAB>source``),
* the explicit, reviewed ``label_corrections`` of ``sources.json``,
* the pinned Ensembl evidence TSV, joined by exact versioned accession.

It reads those files by path with the standard library only. It does not
import the production package, the registry builder/loader/resolver, or the
generated ``data/*.tsv`` registries as a source of expectations (those are
the *subject* under test, compared against this oracle). Everything here is
deliberately small and linear so it can be audited at a glance.

An authority is one of ``ucsc assembly ensembl genbank refseq``. ``chrom``
(the UCSC row handle) names a sequence record within one assembly.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_DIR = (Path(__file__).resolve().parents[2]
                / "streamlit_app" / "core" / "chrom_registry")
SOURCES = REGISTRY_DIR / "sources.json"
LABELS = ("assembly", "ensembl", "genbank", "refseq")
AUTHORITIES = ("ucsc",) + LABELS


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sources() -> dict[str, dict]:
    """``{assembly_id: sources.json entry}`` (pins, corrections, evidence)."""
    config = json.loads(SOURCES.read_text(encoding="utf-8"))
    return {a["assembly_id"]: a for a in config["assemblies"]}


def read_upstream_rows(entry: dict) -> list[tuple[str, str, str]]:
    """Pinned raw alias rows ``(alias, chrom, source)``; SHA-256 enforced."""
    data = (REGISTRY_DIR / entry["upstream_file"]).read_bytes()
    assert _sha256(data) == entry["sha256"], (
        f"{entry['assembly_id']}: upstream bytes differ from the pinned file")
    rows = []
    for line in gzip.decompress(data).decode("utf-8").splitlines():
        alias, chrom, source = line.split("\t")
        rows.append((alias, chrom, source))
    return rows


def apply_corrections(rows, corrections):
    """Replace a row's source label only where an explicit correction names
    that exact ``(alias, chrom, from)`` row. Returns ``(rows, applied)``."""
    wanted = {(c["alias"], c["chrom"], c["from"]): c["to"]
              for c in corrections}
    out, applied = [], []
    for alias, chrom, source in rows:
        key = (alias, chrom, source)
        if key in wanted:
            applied.append(key)
            source = wanted[key]
        out.append((alias, chrom, source))
    return out, applied


def read_evidence_rows(entry: dict) -> list[dict[str, str]]:
    """Pinned Ensembl evidence rows as dicts; SHA-256 enforced."""
    config = entry["ensembl_evidence"]
    raw = (REGISTRY_DIR / config["evidence_file"]).read_bytes()
    assert _sha256(raw) == config["evidence_sha256"], (
        f"{entry['assembly_id']}: evidence bytes differ from the pinned file")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t")
    return list(reader)


@dataclass
class AssemblyOracle:
    assembly: str
    # (chrom, authority, alias) -> why this alias is supported
    facts: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # problems in the inputs themselves (conflicts, unacknowledged mismatch)
    conflicts: list[str] = field(default_factory=list)
    corrections_applied: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def chroms(self) -> set[str]:
        return {chrom for chrom, _, _ in self.facts}

    def records(self) -> dict[str, dict[str, list[str]]]:
        """``{chrom: {authority: [aliases]}}`` (a list so duplicates show)."""
        out: dict[str, dict[str, list[str]]] = {}
        for chrom, authority, alias in self.facts:
            out.setdefault(chrom, {}).setdefault(authority, []).append(alias)
        return out

    def alias_to_chroms(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for chrom, _, alias in self.facts:
            out.setdefault(alias, set()).add(chrom)
        return out

    def resolve(self, identifier: str) -> str | None:
        """The sequence record (UCSC handle) ``identifier`` names, if any."""
        chroms = self.alias_to_chroms().get(identifier, set())
        return next(iter(chroms)) if len(chroms) == 1 else None

    def render(self, chrom: str, authority: str) -> str | None:
        aliases = self.records().get(chrom, {}).get(authority, [])
        return aliases[0] if len(aliases) == 1 else None


def build_oracle(assembly: str, *, rows=None, evidence=None,
                 corrections=None) -> AssemblyOracle:
    """Expected alias facts of ``assembly`` from pinned upstream evidence.

    ``rows`` / ``evidence`` / ``corrections`` may be overridden by tests that
    prove the oracle detects bad inputs; by default the pinned files are read.
    """
    entry = sources()[assembly]
    if rows is None:
        rows = read_upstream_rows(entry)
    if corrections is None:
        corrections = entry.get("label_corrections", [])
    rows, applied = apply_corrections(rows, corrections)
    oracle = AssemblyOracle(assembly, corrections_applied=applied)

    def add(chrom, authority, alias, why):
        oracle.facts.setdefault((chrom, authority, alias), why)

    corrected = {(alias, chrom) for alias, chrom, _ in applied}
    for alias, chrom, source in rows:
        add(chrom, "ucsc", chrom, "ucsc row handle")
        why = ("upstream with reviewed label correction"
               if (alias, chrom) in corrected else "upstream")
        for label in source.split(","):
            add(chrom, label, alias, why)

    config = entry.get("ensembl_evidence")
    if config is not None:
        if evidence is None:
            evidence = read_evidence_rows(entry)
        _add_evidence(oracle, rows, evidence,
                      config.get("ucsc_name_disagreements", []))

    for alias, chroms in oracle.alias_to_chroms().items():
        if len(chroms) > 1:
            oracle.conflicts.append(
                f"alias {alias!r} names several records {sorted(chroms)}")
    for chrom, by_authority in oracle.records().items():
        for authority, aliases in by_authority.items():
            if len(aliases) > 1:
                oracle.conflicts.append(
                    f"{chrom!r} has several {authority} aliases {aliases}")
    return oracle


def _add_evidence(oracle, rows, evidence, acknowledged):
    """Ensembl alias = the name of the top-level region whose INSDC or
    RefSeq accession equals, exactly and including version, the record's
    GenBank or RefSeq accession. No name, prefix or assembly-column use."""
    explicit = [r for r in rows if "ensembl" in r[2].split(",")]
    if explicit:
        oracle.conflicts.append(
            "upstream already carries ensembl aliases; evidence must not "
            f"overwrite them: {explicit[:2]}")
    ack = {(m["ensembl_name"], m["evidence_ucsc"], m["registry_ucsc"])
           for m in acknowledged}
    used = set()
    for region in evidence:
        if region["toplevel"] != "1":
            continue
        name = region["ensembl_name"]
        hits = set()
        for alias, chrom, source in rows:
            labels = source.split(",")
            if (region["insdc"] and "genbank" in labels
                    and alias == region["insdc"]):
                hits.add(chrom)
            if (region["refseq"] and "refseq" in labels
                    and alias == region["refseq"]):
                hits.add(chrom)
        if len(hits) != 1:
            oracle.conflicts.append(
                f"Ensembl region {name!r} matches {len(hits)} records")
            continue
        (chrom,) = hits
        if region["ucsc"] and region["ucsc"] != chrom:
            key = (name, region["ucsc"], chrom)
            if key not in ack:
                oracle.conflicts.append(
                    f"Ensembl region {name!r} says UCSC {region['ucsc']!r} "
                    f"but its accession identifies {chrom!r}; unacknowledged")
            used.add(key)
        oracle.facts.setdefault(
            (chrom, "ensembl", name),
            "pinned Ensembl evidence (exact accession)")
    for stale in ack - used:
        oracle.conflicts.append(f"stale UCSC-mismatch acknowledgement {stale}")


def parse_registry_tsv(text: str) -> list[dict[str, str]]:
    """Rows of a generated wide registry TSV (the subject under test)."""
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def registry_discrepancies(oracle: AssemblyOracle,
                           rows: list[dict[str, str]]) -> list[str]:
    """Differences between a generated registry's cells and the oracle.

    Reports invented aliases (a cell with no supporting fact), missing
    aliases (a supported fact absent from the registry) and records the
    oracle does not know. An empty list means the registry is exactly the
    set of supported facts.
    """
    problems = []
    seen = set()
    for row in rows:
        chrom = row["ucsc"]
        for authority in AUTHORITIES:
            alias = row[authority]
            if not alias:
                continue
            fact = (chrom, authority, alias)
            seen.add(fact)
            if fact not in oracle.facts:
                problems.append(f"unsupported alias {fact}")
    for fact in oracle.facts:
        if fact not in seen:
            problems.append(f"missing alias {fact}")
    return problems
