"""Build-time Ensembl evidence for registry enrichment (offline).

An Ensembl alias is added to a registry record only when pinned Ensembl
release data identify the *same sequence* by an exact, versioned accession
(INSDC/GenBank or RefSeq). Names are never matched by resemblance, and the
registry's own ``assembly`` aliases are never copied into ``ensembl``.

Two steps:

* ``extract_evidence`` turns the pinned Ensembl core-database tables
  (``seq_region``, ``seq_region_synonym``, ``external_db``, ``coord_system``,
  ``seq_region_attrib``, ``attrib_type``) into a small evidence TSV.
* ``match_evidence`` joins that evidence to alias rows by exact accession and
  returns the ``(alias, chrom, "ensembl")`` rows to add, or fails.
"""

from __future__ import annotations

import gzip

from .builder import RegistryBuildError

EVIDENCE_HEADER = (
    "ensembl_name", "coord_system", "length", "toplevel",
    "insdc", "refseq", "ucsc",
)
TABLES = (
    "attrib_type.txt.gz", "coord_system.txt.gz", "external_db.txt.gz",
    "seq_region.txt.gz", "seq_region_attrib.txt.gz",
    "seq_region_synonym.txt.gz",
)
# Ensembl external_db names accepted as synonyms, and the evidence column
# each fills. A synonym with no external database (NULL) carries no
# authority and is ignored; any other source on a selected region is an
# error.
NULL = "\\N"  # MySQL dump NULL
_SYNONYM_COLUMNS = {"INSDC": "insdc", "RefSeq_genomic": "refseq",
                    "UCSC": "ucsc"}


def _table(tables, name):
    try:
        text = gzip.decompress(tables[name]).decode("utf-8")
    except (KeyError, OSError, EOFError, UnicodeDecodeError) as exc:
        raise RegistryBuildError(f"cannot read Ensembl table {name}: {exc}")
    return [line.split("\t") for line in text.split("\n") if line]


def extract_evidence(tables, coord_system_version: str) -> str:
    """Evidence TSV for regions of the given coordinate-system version that
    carry at least one synonym. Deterministic: sorted by Ensembl name."""
    external = {r[0]: r[1] for r in _table(tables, "external_db.txt.gz")}
    coord = {r[0]: (r[2], r[3])
             for r in _table(tables, "coord_system.txt.gz")}
    toplevel_id = [r[0] for r in _table(tables, "attrib_type.txt.gz")
                   if r[1] == "toplevel"]
    if len(toplevel_id) != 1:
        raise RegistryBuildError("no unique 'toplevel' attribute type")
    toplevel = {r[0] for r in _table(tables, "seq_region_attrib.txt.gz")
                if r[1] == toplevel_id[0]}
    regions = {}
    for sid, name, cs_id, length in (
            r[:4] for r in _table(tables, "seq_region.txt.gz")):
        if cs_id in coord and coord[cs_id][1] == coord_system_version:
            regions[sid] = (name, coord[cs_id][0], length)
    synonyms: dict[str, dict[str, str]] = {}
    for _, sid, synonym, db_id in _table(tables, "seq_region_synonym.txt.gz"):
        if sid not in regions:
            continue
        if db_id == NULL:
            continue
        column = _SYNONYM_COLUMNS.get(external.get(db_id))
        if column is None:
            raise RegistryBuildError(
                f"unexpected synonym source {external.get(db_id)!r} for "
                f"region {regions[sid][0]!r}")
        record = synonyms.setdefault(sid, {})
        if column in record:
            raise RegistryBuildError(
                f"region {regions[sid][0]!r} has several {column} synonyms")
        record[column] = synonym
    names = [regions[s][0] for s in synonyms]
    if len(names) != len(set(names)):
        raise RegistryBuildError("duplicate Ensembl region names in evidence")
    lines = ["\t".join(EVIDENCE_HEADER)]
    for sid in sorted(synonyms, key=lambda s: regions[s][0]):
        name, cs_name, length = regions[sid]
        syn = synonyms[sid]
        lines.append("\t".join([
            name, cs_name, length, "1" if sid in toplevel else "0",
            syn.get("insdc", ""), syn.get("refseq", ""),
            syn.get("ucsc", "")]))
    return "\n".join(lines) + "\n"


def parse_evidence(text: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    if lines.pop() != "":
        raise RegistryBuildError("evidence: missing final newline")
    if not lines or tuple(lines[0].split("\t")) != EVIDENCE_HEADER:
        raise RegistryBuildError("evidence: unexpected header")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(EVIDENCE_HEADER):
            raise RegistryBuildError(f"evidence line {number}: bad field count")
        row = dict(zip(EVIDENCE_HEADER, fields))
        if not row["ensembl_name"] or row["toplevel"] not in ("0", "1"):
            raise RegistryBuildError(f"evidence line {number}: invalid row")
        if not (row["insdc"] or row["refseq"]):
            raise RegistryBuildError(
                f"evidence line {number}: no accession to match on")
        rows.append(row)
    names = [r["ensembl_name"] for r in rows]
    if len(names) != len(set(names)):
        raise RegistryBuildError("evidence: duplicate Ensembl names")
    return rows


def match_evidence(rows, evidence, allowed_ucsc_mismatches=()):
    """Rows ``(ensembl_name, chrom, "ensembl")`` for top-level evidence
    regions identified with a registry record by exact accession.

    ``rows`` are alias rows after label corrections. Hard errors: an
    upstream ``ensembl`` alias already present, no/ambiguous record for a
    top-level region, an accession that contradicts the matched record,
    two regions for one record, an unacknowledged UCSC-name disagreement,
    or a stale acknowledgement.
    """
    by_accession = {"genbank": {}, "refseq": {}}
    record: dict[str, dict[str, str]] = {}
    for alias, chrom, source in rows:
        labels = source.split(",")
        if "ensembl" in labels:
            raise RegistryBuildError(
                f"{chrom!r} already has an explicit upstream ensembl alias; "
                "Ensembl evidence must not overwrite it")
        for label in labels:
            if label in by_accession:
                by_accession[label].setdefault(alias, set()).add(chrom)
            record.setdefault(chrom, {})[label] = alias
    pending = {(m["ensembl_name"], m["evidence_ucsc"], m["registry_ucsc"]): m
               for m in allowed_ucsc_mismatches}
    for key, m in pending.items():
        if not all(m.get(k) for k in ("ensembl_name", "evidence_ucsc",
                                      "registry_ucsc", "rationale")):
            raise RegistryBuildError(f"incomplete UCSC acknowledgement {m!r}")
    added: dict[str, str] = {}
    for ev in evidence:
        if ev["toplevel"] != "1":
            continue
        cands = set()
        for column, label in (("insdc", "genbank"), ("refseq", "refseq")):
            if ev[column]:
                cands |= by_accession[label].get(ev[column], set())
        name = ev["ensembl_name"]
        if len(cands) != 1:
            raise RegistryBuildError(
                f"Ensembl region {name!r} matches {len(cands)} registry "
                "records by exact accession (need exactly 1)")
        (chrom,) = cands
        for column, label in (("insdc", "genbank"), ("refseq", "refseq")):
            known = record[chrom].get(label)
            if ev[column] and known and known != ev[column]:
                raise RegistryBuildError(
                    f"Ensembl region {name!r} {column} {ev[column]!r} "
                    f"contradicts {chrom!r} {label} {known!r}")
        if ev["ucsc"] and ev["ucsc"] != chrom:
            key = (name, ev["ucsc"], chrom)
            if pending.pop(key, None) is None:
                raise RegistryBuildError(
                    f"Ensembl region {name!r} calls itself UCSC "
                    f"{ev['ucsc']!r} but its accession identifies "
                    f"{chrom!r}; acknowledge explicitly or fix the data")
        if chrom in added:
            raise RegistryBuildError(
                f"{chrom!r} is matched by Ensembl regions {added[chrom]!r} "
                f"and {name!r}")
        added[chrom] = name
    if pending:
        raise RegistryBuildError(
            f"stale UCSC-mismatch acknowledgements: {sorted(pending)}")
    return [(name, chrom, "ensembl") for chrom, name in sorted(added.items())]


def verify_tables(tables, config) -> None:
    """Raw Ensembl tables must match the pinned SHA-256 values."""
    from .builder import sha256_hex
    for name in TABLES:
        if name not in tables:
            raise RegistryBuildError(f"missing Ensembl table {name}")
        actual = sha256_hex(tables[name])
        if actual != config["tables"][name]:
            raise RegistryBuildError(
                f"Ensembl table {name}: SHA-256 {actual} does not match "
                f"pinned {config['tables'][name]}")
