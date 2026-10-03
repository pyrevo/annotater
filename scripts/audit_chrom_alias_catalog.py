#!/usr/bin/env python3
"""Audit the UCSC genome catalog against the chromosome-alias registry model.

Diagnostic only: nothing here adds an assembly to the runtime catalog, the
GUI or the packaged registries. For every candidate genome database the
audit asks whether its UCSC ``database/chromAlias.txt.gz`` table could be
represented by the *current* generic registry contract (SPEC 5.1) without
new builder code, schema changes or biological heuristics.

    python scripts/audit_chrom_alias_catalog.py --cache-dir CACHE --fetch \\
        --out-json audits/chrom_alias_catalog/report.json \\
        --out-summary audits/chrom_alias_catalog/SUMMARY.md
    python scripts/audit_chrom_alias_catalog.py --cache-dir CACHE \\
        --out-json report.json --out-summary SUMMARY.md     # offline rerun

Only ``--fetch`` uses the network (the catalog JSON and one small file per
database, cached under ``--cache-dir``). Without it the audit reads the cache
only and is fully deterministic: the same cache yields a byte-identical
report. The application and the test suite never use the network.

Classification
--------------
``PASS``       representable as is: no label, shape, collision or
               multiplicity issue, and the builder's output equals an
               independently derived expectation.
``REVIEW``     looks supportable but needs a reviewed intervention (an
               explicit source-label correction, or an accession shape the
               generic validator does not know) or the audit and the builder
               disagree. Never auto-promoted.
``FAIL``       the current architecture cannot represent the table safely
               (several aliases for one sequence and authority, one alias for
               several sequences, an alias equal to another sequence's UCSC
               name, an unsupported source label, malformed rows).
``NO_SOURCE``  UCSC publishes no ``chromAlias`` table for this database
               (reported separately from model failures).
``ERROR``      the source could not be fetched (not a verdict; rerun).

Reason codes are stable machine-readable strings (``REASONS``). A missing
authority (no ``ensembl`` or ``assembly`` aliases, say) is *not* an issue:
``no_alias_for_target`` is valid runtime behavior.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import statistics
import sys
import urllib.error
import urllib.request
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.core.chrom_registry import builder
from streamlit_app.core.chrom_registry.loader import (
    ChromosomeRegistry,
    RegistryError,
)

SCHEMA_VERSION = 1
CATALOG_URL = "https://api.genome.ucsc.edu/list/ucscGenomes"
ALIAS_URL = ("https://hgdownload.soe.ucsc.edu/goldenPath/{db}/database/"
             "chromAlias.txt.gz")
DB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

LABELS = builder.SOURCE_LABELS
AUTHORITIES = builder.AUTHORITIES            # ucsc + the four labels
# Production assembly ids of the six assemblies that are already supported.
PRODUCTION = {"hg38": "GRCh38", "hg19": "hg19", "mm39": "GRCm39",
              "dm6": "dm6", "danRer11": "GRCz11", "rn7": "rn7"}

REASONS = {
    "PASS": "no issue",
    "NO_CHROM_ALIAS": "UCSC publishes no database/chromAlias.txt.gz",
    "FETCH_ERROR": "the source could not be fetched",
    "MALFORMED_ROWS": "rows are not alias<TAB>chrom<TAB>source with clean "
                      "values",
    "UNSUPPORTED_SOURCE_LABEL": "a source label other than "
                                "assembly/ensembl/genbank/refseq",
    "ALIAS_COLLISION": "one alias names several sequences, or equals "
                       "another sequence's UCSC name",
    "MULTIPLE_ALIAS_PER_AUTHORITY": "several aliases for one sequence and "
                                    "authority (wide schema is lossy)",
    "SOURCE_LABEL_MISMATCH": "source label contradicts the accession's "
                             "RefSeq/INSDC shape",
    "ACCESSION_SHAPE": "a refseq/genbank-labelled alias has a shape the "
                       "generic validator does not know",
    "NEEDS_REVIEW": "audit diagnostics and the production builder disagree",
}
FAIL_CODES = ("MALFORMED_ROWS", "UNSUPPORTED_SOURCE_LABEL", "ALIAS_COLLISION",
              "MULTIPLE_ALIAS_PER_AUTHORITY")
REVIEW_CODES = ("SOURCE_LABEL_MISMATCH", "ACCESSION_SHAPE", "NEEDS_REVIEW")

MITO_HANDLES = {"chrm", "chrmt", "mt", "m"}
MITO_ALIASES = {"MT", "M"}
EXAMPLE_LIMIT = 3


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

def parse_catalog(data: bytes):
    """Return ``(meta, candidates, excluded)`` from the UCSC genome list.

    Filtering rules (explicit, nothing else is dropped): the entry must be
    ``active`` and its database id must be a plain identifier usable in a
    URL path. Species labels are taken verbatim from the catalog; nothing is
    derived from database ids.
    """
    doc = json.loads(data)
    genomes = doc["ucscGenomes"]
    candidates, excluded = [], []
    for db in sorted(genomes):
        entry = genomes[db]
        if not DB_ID_RE.match(db):
            excluded.append({"db": db, "reason": "invalid database id"})
        elif entry.get("active") != 1:
            excluded.append({"db": db, "reason": "not active"})
        else:
            candidates.append({
                "db": db,
                "organism": entry.get("organism") or None,
                "common_name": entry.get("genome") or None,
                "scientific_name": entry.get("scientificName") or None,
                "tax_id": entry.get("taxId"),
                "assembly_name": entry.get("description") or None,
                "source_name": entry.get("sourceName") or None,
            })
    meta = {"catalog_data_time": doc.get("dataTime"),
            "catalog_download_time": doc.get("downloadTime"),
            "catalog_entries": len(genomes)}
    return meta, candidates, excluded


# --------------------------------------------------------------------------
# Row parsing (independent of the builder's parser)
# --------------------------------------------------------------------------

def parse_rows(data: bytes):
    """Return ``(rows, malformed)``; ``malformed`` lists ``(line, reason)``.

    Values are never trimmed or case-folded: whitespace is a defect.
    """
    try:
        text = gzip.decompress(data).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError, zlib.error) as exc:
        return [], [(0, f"unreadable: {exc}")]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rows, malformed = [], []
    for number, line in enumerate(lines, start=1):
        fields = line.split("\t")
        if len(fields) != 3:
            malformed.append((number, f"{len(fields)} fields"))
            continue
        if any(f == "" for f in fields):
            malformed.append((number, "empty field"))
        elif any(f != f.strip() or "\r" in f for f in fields):
            malformed.append((number, "surrounding whitespace"))
        else:
            rows.append(tuple(fields))
    if not lines:
        malformed.append((0, "no rows"))
    return rows, malformed


def shape_of(alias: str) -> str:
    """'refseq', 'insdc' or 'other' by the production validator's patterns."""
    if builder._REFSEQ_RE.match(alias):
        return "refseq"
    if builder._GENBANK_RE.match(alias):
        return "insdc"
    return "other"


def signature(alias: str) -> str:
    """Letters/digits run signature: ``CM000663.2`` -> ``A2D6.D1``."""
    out = []
    for m in re.finditer(r"[A-Za-z]+|\d+|.", alias):
        t = m.group()
        out.append(f"A{len(t)}" if t.isalpha() else
                   f"D{len(t)}" if t.isdigit() else t)
    return "".join(out)


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

def diagnose(rows):
    """Collect every structural issue of the well-formed rows."""
    issues = {"unsupported_labels": [], "repeated_labels": [],
              "label_issues": [], "accession_issues": [],
              "alias_collisions": [], "multi_alias": [], "case_collisions": []}
    facts = defaultdict(set)                 # (chrom, label) -> {alias}
    owners = defaultdict(set)                # alias -> {chrom}
    chroms = set()
    for alias, chrom, source in rows:
        chroms.add(chrom)
        owners[alias].add(chrom)
        labels = source.split(",")
        if len(set(labels)) != len(labels):
            issues["repeated_labels"].append((alias, chrom, source))
        bad = [lab for lab in labels if lab not in LABELS]
        if bad:
            issues["unsupported_labels"].append((alias, chrom, source))
        for lab in labels:
            if lab in LABELS:
                facts[(chrom, lab)].add(alias)
        shape = shape_of(alias)
        kind = None
        if "refseq" in labels and shape != "refseq":
            kind = ("refseq_label_on_insdc_shape" if shape == "insdc"
                    else "refseq_label_on_unknown_shape")
        elif "genbank" in labels and shape != "insdc":
            kind = ("genbank_label_on_refseq_shape" if shape == "refseq"
                    else "genbank_label_on_unknown_shape")
        elif shape == "refseq" and "refseq" not in labels:
            kind = "refseq_shape_without_refseq_label"
        if kind:
            entry = {"alias": alias, "chrom": chrom, "source": source,
                     "kind": kind, "signature": signature(alias)}
            key = ("accession_issues" if kind.endswith("unknown_shape")
                   else "label_issues")
            issues[key].append(entry)
    for alias, who in sorted(owners.items()):
        if len(who) > 1:
            issues["alias_collisions"].append(
                {"alias": alias, "kind": "several_sequences",
                 "chroms": sorted(who)})
        if alias in chroms and who != {alias}:
            issues["alias_collisions"].append(
                {"alias": alias, "kind": "equals_other_ucsc_name",
                 "chroms": sorted(who)})
    for (chrom, lab), aliases in sorted(facts.items()):
        if len(aliases) > 1:
            issues["multi_alias"].append(
                {"chrom": chrom, "authority": lab,
                 "aliases": sorted(aliases)})
    folded = defaultdict(set)
    for name in set(owners) | chroms:
        folded[name.casefold()].add(name)
    for key, names in sorted(folded.items()):
        if len(names) > 1:
            records = set()
            for name in names:
                records |= owners.get(name, set()) | ({name} & chroms)
            issues["case_collisions"].append(
                {"names": sorted(names), "records": sorted(records),
                 "cross_record": len(records) > 1})
    return issues, facts, chroms


def expected_cells(rows):
    """Independent expectation: ``{(chrom, authority, alias)}`` from rows."""
    out = set()
    for alias, chrom, source in rows:
        out.add((chrom, "ucsc", chrom))
        for lab in source.split(","):
            if lab in LABELS:
                out.add((chrom, lab, alias))
    return out


def render_wide(db: str, facts) -> str:
    """Wide TSV text from expected facts (first alias if several; sorted)."""
    by_chrom = defaultdict(dict)
    for chrom, authority, alias in sorted(facts):
        by_chrom[chrom].setdefault(authority, alias)
    lines = ["\t".join(builder.HEADER)]
    for chrom in sorted(by_chrom):
        cells = by_chrom[chrom]
        lines.append("\t".join([f"{db}:{chrom}", chrom]
                               + [cells.get(a, "") for a in LABELS]))
    return "\n".join(lines) + "\n"


def oracle_compare(facts, tsv_text: str):
    """Differences between expected facts and a wide TSV's cells."""
    got = set()
    for row in csv.DictReader(io.StringIO(tsv_text), delimiter="\t"):
        for authority in AUTHORITIES:
            if row[authority]:
                got.add((row["ucsc"], authority, row[authority]))
    return sorted(facts ^ got)


def name_shape(chrom: str) -> str:
    """Descriptive class of a UCSC sequence name (statistics only)."""
    for label, pattern in (
            ("chr_numeric", r"chr\d+$"), ("chr_roman", r"chr[IVX]+$"),
            ("chr_letter", r"chr[A-Za-z]$"), ("chr_unplaced", r"chrUn"),
            ("alt", r".*_alt$"), ("fix", r".*_fix$"), ("random", r".*_random$"),
            ("haplotype", r".*_hap\d*$"), ("scaffold", r"(?i)scaffold"),
            ("linkage_group", r"(chr)?LG"), ("chr_other", r"chr")):
        if re.match(pattern, chrom):
            return label
    return "other"


def mito_report(rows, chroms):
    handles = sorted(c for c in chroms if c.casefold() in MITO_HANDLES)
    by_alias = sorted({chrom for alias, chrom, _ in rows
                       if alias in MITO_ALIASES})
    records = sorted(set(handles) | set(by_alias))
    aliases = {c: sorted(a for a, ch, _ in rows if ch == c) for c in records}
    return {"records": records, "multiple": len(records) > 1,
            "aliases": aliases}


# --------------------------------------------------------------------------
# Per-assembly audit
# --------------------------------------------------------------------------

def audit_source(meta: dict, data: bytes | None, status_code: int | None,
                 error: str | None = None) -> dict:
    """Audit one candidate; ``meta`` is the catalog entry."""
    db = meta["db"]
    result = {
        **meta, "production_assembly": PRODUCTION.get(db),
        "alias_url": ALIAS_URL.format(db=db), "source_http_status": status_code,
        "source_sha256": None, "source_bytes": None,
        "status": None, "reason_codes": [],
        "alias_rows": None, "sequence_records": None,
        "authorities_present": None, "authority_counts": None,
        "authority_missing": None, "source_label_sets": None,
        "wide_schema_lossless": None, "collision_count": None,
        "label_issue_count": None, "accession_issue_count": None,
        "multi_alias_count": None, "malformed_rows": None,
        "case_collision_count": None, "case_collision_cross_record": None,
        "insdc_shaped_without_genbank_label": None,
        "builder_ok": None, "loader_ok": None,
        "builder_error": None, "oracle_ok": None,
        "estimated_tsv_bytes": None, "estimated_tsv_gzip_bytes": None,
        "estimated_tsv_exact": None, "name_shapes": None, "mito": None,
        "examples": None,
    }
    if error is not None:
        result.update(status="ERROR", reason_codes=["FETCH_ERROR"],
                      builder_error=error)
        return result
    if status_code == 404 or data is None:
        result.update(status="NO_SOURCE", reason_codes=["NO_CHROM_ALIAS"])
        return result

    result["source_sha256"] = hashlib.sha256(data).hexdigest()
    result["source_bytes"] = len(data)
    rows, malformed = parse_rows(data)
    issues, _facts, chroms = diagnose(rows)
    expected = expected_cells(rows)
    codes = []
    if malformed:
        codes.append("MALFORMED_ROWS")
    if issues["unsupported_labels"] or issues["repeated_labels"]:
        codes.append("UNSUPPORTED_SOURCE_LABEL")
    if issues["alias_collisions"]:
        codes.append("ALIAS_COLLISION")
    if issues["multi_alias"]:
        codes.append("MULTIPLE_ALIAS_PER_AUTHORITY")
    if issues["label_issues"]:
        codes.append("SOURCE_LABEL_MISMATCH")
    if issues["accession_issues"]:
        codes.append("ACCESSION_SHAPE")

    # Cross-check against the production builder (current validations).
    builder_text = None
    if malformed:
        result["builder_ok"] = False
        result["builder_error"] = "malformed rows"
    else:
        try:
            builder_text = builder.build_registry(rows, db)
            result["builder_ok"] = True
        except builder.RegistryBuildError as exc:
            result["builder_ok"], result["builder_error"] = False, str(exc)
    if bool(codes) == bool(result["builder_ok"]):
        codes.append("NEEDS_REVIEW")      # audit and builder disagree
    if builder_text is not None:
        result["oracle_ok"] = not oracle_compare(expected, builder_text)
        if not result["oracle_ok"]:
            codes.append("NEEDS_REVIEW")
        try:                              # the runtime must accept it too
            ChromosomeRegistry.from_tsv(db, builder_text)
            result["loader_ok"] = True
        except RegistryError:
            result["loader_ok"] = False
            codes.append("NEEDS_REVIEW")

    if not codes:
        codes = ["PASS"]
    status = ("FAIL" if any(c in FAIL_CODES for c in codes)
              else "REVIEW" if any(c in REVIEW_CODES for c in codes)
              else "PASS")
    tsv = render_wide(db, expected)
    counts = {a: sum(1 for c, au, _ in expected if au == a)
              for a in AUTHORITIES}
    label_sets = Counter(src for _, _, src in rows)
    n = len(chroms)
    lossless = not issues["multi_alias"] and not issues["alias_collisions"]
    result.update(
        status=status, reason_codes=sorted(set(codes)),
        alias_rows=len(rows), sequence_records=n,
        authorities_present=[a for a in AUTHORITIES if counts[a]],
        authority_counts=counts,
        authority_missing={a: n - counts[a] for a in AUTHORITIES},
        source_label_sets=dict(sorted(label_sets.items())),
        wide_schema_lossless=lossless,
        collision_count=len(issues["alias_collisions"]),
        label_issue_count=len(issues["label_issues"]),
        accession_issue_count=len(issues["accession_issues"]),
        multi_alias_count=len(issues["multi_alias"]),
        malformed_rows=len(malformed),
        case_collision_count=len(issues["case_collisions"]),
        insdc_shaped_without_genbank_label=sum(
            1 for alias, _, source in rows
            if shape_of(alias) == "insdc" and "genbank" not in source.split(",")),
        case_collision_cross_record=sum(
            1 for c in issues["case_collisions"] if c["cross_record"]),
        estimated_tsv_bytes=len(tsv.encode()),
        estimated_tsv_gzip_bytes=len(zlib.compress(tsv.encode(), 9)),
        estimated_tsv_exact=bool(builder_text is not None
                                 and builder_text == tsv),
        name_shapes=dict(sorted(Counter(map(name_shape, chroms)).items())),
        mito=mito_report(rows, chroms),
        examples={
            "malformed": [{"line": ln, "reason": why}
                          for ln, why in malformed[:EXAMPLE_LIMIT]],
            "unsupported_labels": [list(r) for r in
                                   (issues["unsupported_labels"]
                                    + issues["repeated_labels"])[:EXAMPLE_LIMIT]],
            "collisions": issues["alias_collisions"][:EXAMPLE_LIMIT],
            "multi_alias": issues["multi_alias"][:EXAMPLE_LIMIT],
            "label_issues": issues["label_issues"][:EXAMPLE_LIMIT],
            "accession_issues": issues["accession_issues"][:EXAMPLE_LIMIT],
            "case_collisions": issues["case_collisions"][:EXAMPLE_LIMIT],
        },
    )
    result["_shapes"] = [(e["signature"], e["alias"], e["kind"], e["source"])
                         for e in issues["label_issues"]
                         + issues["accession_issues"]]
    return result


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def build_report(meta, candidates, excluded, audited, catalog_sha256):
    audited = sorted(audited, key=lambda r: r["db"])
    shapes = defaultdict(lambda: {"count": 0, "dbs": set(), "example": None,
                                  "kinds": set(), "sources": set()})
    for r in audited:
        for sig, alias, kind, source in r.pop("_shapes", []):
            s = shapes[sig]
            s["count"] += 1
            s["dbs"].add(r["db"])
            s["example"] = s["example"] or alias
            s["kinds"].add(kind)
            s["sources"].add(source)
    shape_rows = [{"signature": sig, "count": s["count"],
                   "assemblies": sorted(s["dbs"]), "example": s["example"],
                   "kinds": sorted(s["kinds"]), "source_labels":
                   sorted(s["sources"])}
                  for sig, s in sorted(shapes.items(),
                                       key=lambda kv: (-kv[1]["count"], kv[0]))]
    status = Counter(r["status"] for r in audited)
    reasons = Counter(c for r in audited for c in r["reason_codes"])
    passing = [r for r in audited if r["status"] == "PASS"]
    sizes = sorted(r["estimated_tsv_bytes"] for r in passing)
    gz = sum(r["estimated_tsv_gzip_bytes"] for r in passing)
    usable = [r for r in audited if r["alias_rows"] is not None]
    summary = {
        "candidates": len(audited), "excluded": len(excluded),
        "with_chrom_alias": sum(1 for r in audited
                                if r["status"] not in ("NO_SOURCE", "ERROR")),
        "status_counts": dict(sorted(status.items())),
        "reason_code_counts": dict(sorted(reasons.items())),
        "wide_schema_lossless": sum(1 for r in usable
                                    if r["wide_schema_lossless"]),
        "wide_schema_lossy": sum(1 for r in usable
                                 if not r["wide_schema_lossless"]),
        "builder_audit_disagreements": sum(
            1 for r in usable if "NEEDS_REVIEW" in r["reason_codes"]),
        "pass_size": {
            "assemblies": len(passing),
            "tsv_bytes_total": sum(sizes),
            "tsv_gzip_bytes_total": gz,
            "tsv_bytes_median": int(statistics.median(sizes)) if sizes else 0,
            "tsv_bytes_largest": [
                {"db": r["db"], "bytes": r["estimated_tsv_bytes"]}
                for r in sorted(passing, key=lambda r:
                                (-r["estimated_tsv_bytes"], r["db"]))[:5]],
            "upstream_gz_bytes_total": sum(r["source_bytes"] for r in passing),
        },
    }
    return {
        "audit": {
            "schema_version": SCHEMA_VERSION,
            "audit_date": ((meta["catalog_download_time"] or "")[:10]
                           .replace(":", "-") or None),
            "catalog_url": CATALOG_URL, "catalog_sha256": catalog_sha256,
            "catalog_data_time": meta["catalog_data_time"],
            "catalog_entries": meta["catalog_entries"],
            "candidate_count": len(candidates),
            "alias_url_template": ALIAS_URL,
            "filter_rules": [
                "every entry of the UCSC ucscGenomes list is a candidate",
                ("excluded only if not active or the database id is not a "
                 "plain identifier"),
            ],
            "excluded": excluded,
            "classification_rules": {
                "PASS": "no reason code other than PASS",
                "REVIEW": list(REVIEW_CODES),
                "FAIL": list(FAIL_CODES),
                "NO_SOURCE": ["NO_CHROM_ALIAS"],
                "ERROR": ["FETCH_ERROR"],
                "precedence": "FAIL > REVIEW > PASS",
            },
            "reason_codes": REASONS,
            "validations": "current production builder rules (labels, "
                           "RefSeq/INSDC shapes, alias uniqueness, one alias "
                           "per sequence and authority), reimplemented "
                           "independently for diagnosis and cross-checked "
                           "against builder.build_registry",
        },
        "summary": summary,
        "accession_shape_findings": shape_rows,
        "assemblies": audited,
    }


def summary_text(report) -> str:
    s, a = report["summary"], report["audit"]
    lines = [
        f"# UCSC chromAlias catalog audit ({a['audit_date']})", "",
        (f"Catalog: {a['catalog_url']} (data time {a['catalog_data_time']}, "
         f"sha256 {a['catalog_sha256'][:16]}…)"),
        (f"Candidates: {s['candidates']}; with chromAlias: "
         f"{s['with_chrom_alias']}"), "",
        "| status | count |", "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in s["status_counts"].items()]
    lines += ["", "| reason code | assemblies |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s["reason_code_counts"].items()]
    p = s["pass_size"]
    lines += ["", (f"Wide schema lossless: {s['wide_schema_lossless']}; "
                   f"lossy: {s['wide_schema_lossy']}"),
              (f"PASS assemblies: {p['assemblies']}; TSV "
               f"{p['tsv_bytes_total']:,} bytes "
               f"({p['tsv_gzip_bytes_total']:,} deflated)"), "",
              "| db | status | reasons | sequences | alias rows |",
              "|---|---|---|---|---|"]
    for r in report["assemblies"]:
        lines.append(f"| {r['db']} | {r['status']} | "
                     f"{', '.join(r['reason_codes'])} | "
                     f"{r['sequence_records'] or ''} | "
                     f"{r['alias_rows'] or ''} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Fetching and cache (network only with --fetch)
# --------------------------------------------------------------------------

def http_fetch(url: str, timeout: int = 60):
    """``(status, bytes|None, last_modified)``; raises on non-HTTP errors."""
    request = urllib.request.Request(url, headers={"User-Agent": "annotater-audit"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Last-Modified", "")
    except urllib.error.HTTPError as exc:
        return exc.code, None, ""


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def catalog_path(self):
        return self.root / "ucscGenomes.json"

    def source_path(self, db):
        return self.root / "sources" / f"{db}.chromAlias.txt.gz"

    def meta_path(self, db):
        return self.root / "sources" / f"{db}.meta.json"

    def store_source(self, db, status, data, last_modified):
        self.source_path(db).parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            self.source_path(db).write_bytes(data)
        self.meta_path(db).write_text(json.dumps(
            {"status": status, "last_modified": last_modified}, sort_keys=True))

    def load_source(self, db):
        meta = self.meta_path(db)
        if not meta.exists():
            return None
        info = json.loads(meta.read_text())
        path = self.source_path(db)
        return info["status"], (path.read_bytes() if path.exists() else None)


def fetch_all(candidates, cache: Cache, fetch=http_fetch, workers=8):
    """Download every missing source into the cache (idempotent)."""
    def one(c):
        db = c["db"]
        if cache.load_source(db) is not None:
            return
        try:
            status, data, modified = fetch(ALIAS_URL.format(db=db))
        except Exception:  # noqa: BLE001 - any failure leaves it uncached
            return
        if status == 200 or status == 404:
            cache.store_source(db, status, data, modified)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, candidates))


def run_audit(cache: Cache, fetch=None, only=None):
    """Audit every candidate from the cache (fetching first if ``fetch``)."""
    if fetch is not None and not cache.catalog_path().exists():
        status, data, _ = fetch(CATALOG_URL)
        if status != 200:
            raise RuntimeError(f"catalog fetch failed: HTTP {status}")
        cache.root.mkdir(parents=True, exist_ok=True)
        cache.catalog_path().write_bytes(data)
    catalog = cache.catalog_path().read_bytes()
    meta, candidates, excluded = parse_catalog(catalog)
    if only:
        candidates = [c for c in candidates if c["db"] in only]
    if fetch is not None:
        fetch_all(candidates, cache, fetch)
    audited = []
    for c in candidates:
        cached = cache.load_source(c["db"])
        if cached is None:
            audited.append(audit_source(c, None, None, error="not cached"))
        else:
            status, data = cached
            audited.append(audit_source(c, data, status))
    return build_report(meta, candidates, excluded, audited,
                        hashlib.sha256(catalog).hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--fetch", action="store_true",
                        help="download missing sources (the only networked "
                             "mode)")
    parser.add_argument("--only", help="comma-separated database ids")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-summary", type=Path)
    args = parser.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    report = run_audit(Cache(args.cache_dir),
                       fetch=http_fetch if args.fetch else None, only=only)
    text = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text)
    summary = summary_text(report)
    if args.out_summary:
        args.out_summary.write_text(summary)
    print(summary.split("| db |")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
