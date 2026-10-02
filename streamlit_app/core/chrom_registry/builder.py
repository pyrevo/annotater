"""Build and validate a normalized chromosome-alias registry from a pinned
UCSC ``database/chromAlias.txt.gz`` table (offline, deterministic).

Input rows are ``alias<TAB>chrom<TAB>source``. ``chrom`` is used only as the
upstream row handle of a sequence record; it is not a claim that UCSC naming
is canonical. The output is a wide TSV with one row per sequence record and
at most one alias per rendered authority::

    seq_id  ucsc  assembly  ensembl  genbank  refseq

A comma-joined upstream ``source`` (e.g. ``assembly,ensembl``) places the
alias in each listed authority column. An empty cell means "no verified
alias"; nothing is inferred from identifier syntax.

Validation failures are hard errors (``RegistryBuildError``); upstream data
is never silently corrected. The only permitted correction is an explicit,
per-assembly ``label_corrections`` entry in ``sources.json``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = PACKAGE_DIR / "sources.json"

# Upstream ``source`` labels this builder understands. Anything else is a
# hard error rather than a silently dropped or guessed authority.
SOURCE_LABELS = ("assembly", "ensembl", "genbank", "refseq")
# Rendered authorities in registry column order (``ucsc`` is the row handle).
AUTHORITIES = ("ucsc",) + SOURCE_LABELS
HEADER = ("seq_id",) + AUTHORITIES

# Strong syntactic evidence about an accession's authority. RefSeq genomic
# accessions must carry the ``refseq`` label; INSDC-style accessions must
# not be labelled ``refseq``. Applied only to the ``refseq``/``genbank``
# labels; ``assembly``/``ensembl`` names are never syntax-checked.
_REFSEQ_RE = re.compile(r"^N[CTWZ]_\d+\.\d+$")
# INSDC: classic 1+5 / 2+6 accessions, and WGS/contig accessions (4-6 letter
# project prefix + version + digits, e.g. JACYVU010000238.1).
_GENBANK_RE = re.compile(r"^(?:[A-Z]{1,2}\d{5,6}|[A-Z]{4,6}\d{8,})\.\d+$")


class RegistryBuildError(ValueError):
    """The upstream table or configuration violates the registry contract."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_sources(path: Path = SOURCES_FILE) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise RegistryBuildError("unsupported sources.json schema_version")
    return config


def get_assembly(config: dict, assembly_id: str) -> dict:
    for entry in config["assemblies"]:
        if entry["assembly_id"] == assembly_id:
            return entry
    raise RegistryBuildError(f"assembly {assembly_id!r} not in sources.json")


def verify_checksum(data: bytes, entry: dict) -> None:
    actual = sha256_hex(data)
    if actual != entry["sha256"]:
        raise RegistryBuildError(
            f"{entry['assembly_id']}: upstream SHA-256 {actual} does not "
            f"match pinned {entry['sha256']}; refusing to build "
            "(use an explicit update to accept new upstream data)"
        )


def parse_alias_table(data: bytes) -> list[tuple[str, str, str]]:
    """Parse a gzip-compressed UCSC chromAlias table into rows."""
    try:
        text = gzip.decompress(data).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise RegistryBuildError(f"cannot read alias table: {exc}") from exc
    rows = []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # final newline
    for number, line in enumerate(lines, start=1):
        fields = line.split("\t")
        if len(fields) != 3:
            raise RegistryBuildError(
                f"line {number}: expected 3 tab-separated fields, "
                f"got {len(fields)}"
            )
        alias, chrom, source = fields
        for name, value in (("alias", alias), ("chrom", chrom),
                            ("source", source)):
            if value == "":
                raise RegistryBuildError(f"line {number}: empty {name}")
            if value != value.strip() or "\r" in value:
                raise RegistryBuildError(
                    f"line {number}: {name} has surrounding whitespace"
                )
        rows.append((alias, chrom, source))
    if not rows:
        raise RegistryBuildError("alias table has no rows")
    return rows


def _labels(source: str, number: int) -> tuple[str, ...]:
    labels = tuple(source.split(","))
    if len(set(labels)) != len(labels):
        raise RegistryBuildError(f"row {number}: repeated label in {source!r}")
    for label in labels:
        if label not in SOURCE_LABELS:
            raise RegistryBuildError(
                f"row {number}: unsupported source label {label!r}"
            )
    return labels


def _apply_corrections(rows, corrections):
    """Apply explicit, rationale-bearing label corrections (no others)."""
    pending = {}
    for corr in corrections:
        for key in ("alias", "chrom", "from", "to", "rationale"):
            if not corr.get(key):
                raise RegistryBuildError(
                    f"label correction missing {key!r}: {corr!r}"
                )
        pending[(corr["alias"], corr["chrom"], corr["from"])] = corr["to"]
    out = []
    for alias, chrom, source in rows:
        out.append((alias, chrom, pending.pop((alias, chrom, source), source)))
    if pending:
        raise RegistryBuildError(
            f"label corrections matched no upstream row: {sorted(pending)}"
        )
    return out


def build_registry(rows, assembly_id: str, corrections=(),
                   ensembl_evidence=None, ensembl_config=None) -> str:
    """Validate rows and return the normalized TSV text.

    ``ensembl_evidence`` (parsed evidence rows) optionally adds Ensembl
    aliases verified by exact accession; see ``ensembl_evidence.py``.
    """
    rows = _apply_corrections(rows, corrections)
    if ensembl_evidence is not None:
        from .ensembl_evidence import match_evidence
        rows = rows + match_evidence(
            rows, ensembl_evidence,
            (ensembl_config or {}).get("ucsc_name_disagreements", ()))
    alias_owner: dict[str, str] = {}
    cells: dict[str, dict[str, str]] = {}
    for number, (alias, chrom, source) in enumerate(rows, start=1):
        previous = alias_owner.setdefault(alias, chrom)
        if previous != chrom:
            raise RegistryBuildError(
                f"alias {alias!r} resolves to both {previous!r} and {chrom!r}"
            )
        labels = _labels(source, number)
        is_refseq, is_genbank = (bool(_REFSEQ_RE.match(alias)),
                                 bool(_GENBANK_RE.match(alias)))
        if is_refseq and "refseq" not in labels:
            raise RegistryBuildError(
                f"RefSeq-style accession {alias!r} labelled {source!r}"
            )
        if "refseq" in labels and not is_refseq:
            raise RegistryBuildError(
                f"alias {alias!r} labelled refseq is not a RefSeq accession"
            )
        if "genbank" in labels and not is_genbank:
            raise RegistryBuildError(
                f"alias {alias!r} labelled genbank is not an INSDC accession"
            )
        record = cells.setdefault(chrom, {})
        for label in labels:
            if label in record and record[label] != alias:
                raise RegistryBuildError(
                    f"{chrom!r} has more than one {label} alias "
                    f"({record[label]!r}, {alias!r}); wide registry cannot "
                    "represent this without an arbitrary choice"
                )
            record[label] = alias
    for alias, owner in alias_owner.items():
        if alias in cells and alias != owner:
            raise RegistryBuildError(
                f"alias {alias!r} of {owner!r} equals the UCSC name of "
                "another sequence"
            )
    lines = ["\t".join(HEADER)]
    for chrom in sorted(cells):
        record = cells[chrom]
        fields = [f"{assembly_id}:{chrom}", chrom]
        fields += [record.get(label, "") for label in SOURCE_LABELS]
        lines.append("\t".join(fields))
    return "\n".join(lines) + "\n"


def build_from_entry(entry: dict, base: Path = PACKAGE_DIR) -> str:
    data = (base / entry["upstream_file"]).read_bytes()
    verify_checksum(data, entry)
    rows = parse_alias_table(data)
    evidence = None
    config = entry.get("ensembl_evidence")
    if config is not None:
        from .ensembl_evidence import parse_evidence
        raw = (base / config["evidence_file"]).read_bytes()
        if sha256_hex(raw) != config["evidence_sha256"]:
            raise RegistryBuildError(
                f"{entry['assembly_id']}: Ensembl evidence SHA-256 "
                f"{sha256_hex(raw)} does not match pinned "
                f"{config['evidence_sha256']}")
        evidence = parse_evidence(raw.decode("utf-8"))
    return build_registry(rows, entry["assembly_id"],
                          entry.get("label_corrections", []),
                          evidence, config)


def check(entry: dict, base: Path = PACKAGE_DIR) -> None:
    """Raise unless the committed registry equals a fresh rebuild."""
    expected = build_from_entry(entry, base)
    actual = (base / entry["registry_file"]).read_bytes()
    if actual != expected.encode("utf-8"):
        raise RegistryBuildError(
            f"{entry['registry_file']} differs from a rebuild of "
            f"{entry['upstream_file']}"
        )


def write(entry: dict, base: Path = PACKAGE_DIR) -> None:
    text = build_from_entry(entry, base)
    (base / entry["registry_file"]).write_bytes(text.encode("utf-8"))


def accept_upstream(entry: dict, data: bytes, last_modified: str,
                    retrieved: str, base: Path = PACKAGE_DIR) -> None:
    """Explicit update: store new upstream bytes and re-pin them.

    The caller still has to review the resulting diff of the registry.
    """
    parse_alias_table(data)  # refuse to pin something unparseable
    (base / entry["upstream_file"]).write_bytes(data)
    entry["sha256"] = sha256_hex(data)
    entry["upstream_last_modified"] = last_modified
    entry["retrieved"] = retrieved
