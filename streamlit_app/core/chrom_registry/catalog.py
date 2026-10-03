"""Runtime catalog of the bundled genome assemblies.

``catalog.json`` is generated at build time (``scripts/update_chrom_catalog.py``)
from the build manifest ``sources.json``; it carries only what the runtime
needs: each assembly's identity (one canonical id plus the other accepted
names), the packaged registry file and the UCSC-provided display metadata.
Reading it loads no registry. Nothing here uses the network.

Identity model: every assembly has exactly one ``canonical_id`` (the stable
identifier scripts and reports should use), its ``ucsc_db`` handle and a
tuple of further accepted ``aliases``. All names (canonical ids and aliases)
are globally unambiguous; matching is exact and case-sensitive.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

CATALOG_FILE = "catalog.json"
SCHEMA_VERSION = 2

# A name must be usable as a command-line value and a file-name stem.
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class AssemblyInfo:
    """One bundled assembly. Text fields are UCSC catalog values verbatim."""

    canonical_id: str         # the one stable identity (``registry.assembly_id``)
    ucsc_db: str
    aliases: tuple[str, ...]  # other accepted ids; never includes canonical_id
    display_label: str        # unique, user-facing option text
    organism: str | None
    scientific_name: str | None
    description: str | None
    registry_file: str

    @property
    def names(self) -> tuple[str, ...]:
        """Every accepted spelling, canonical id first."""
        return (self.canonical_id, *self.aliases)


def identity_problems(infos) -> list[str]:
    """Why these assemblies' names are not a valid identity namespace.

    Shared by the catalog generator (which refuses to write) and the loader
    (which refuses to serve). Empty means every name belongs to exactly one
    assembly, also when compared case-insensitively.
    """
    problems = []
    owner: dict[str, str] = {}
    folded: dict[str, str] = {}
    canonical = [info.canonical_id for info in infos]
    for cid in sorted({c for c in canonical if canonical.count(c) > 1}):
        problems.append(f"canonical id {cid!r} is used by several assemblies")
    for info in infos:
        if len(set(info.names)) != len(info.names):
            problems.append(f"{info.canonical_id}: repeated names {info.names}")
        for name in info.names:
            if not NAME_PATTERN.fullmatch(name):
                problems.append(f"{info.canonical_id}: invalid name {name!r}")
            previous = owner.setdefault(name, info.canonical_id)
            if previous != info.canonical_id:
                problems.append(
                    f"name {name!r} belongs to both {previous!r} and "
                    f"{info.canonical_id!r}")
            seen = folded.setdefault(name.casefold(), name)
            if seen != name:
                problems.append(
                    f"names {seen!r} and {name!r} differ only in case")
    return problems


@cache
def load_catalog() -> tuple[AssemblyInfo, ...]:
    """The bundled assemblies in presentation order."""
    text = resources.files(__package__).joinpath(CATALOG_FILE).read_text(
        encoding="utf-8")
    config = json.loads(text)
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported catalog.json schema_version")
    infos = tuple(
        AssemblyInfo(**{**entry, "aliases": tuple(entry["aliases"])})
        for entry in config["assemblies"])
    problems = identity_problems(infos)
    if problems:
        raise ValueError(f"catalog.json identity errors: {problems}")
    return infos


@cache
def _by_name() -> dict[str, AssemblyInfo]:
    return {name: info for info in load_catalog() for name in info.names}


def find_assembly(name: str) -> AssemblyInfo | None:
    """The assembly a canonical id or alias names (exact match), if any."""
    return _by_name().get(name) if isinstance(name, str) else None


def assembly_options() -> dict[str, str]:
    """``{display_label: canonical_id}`` in presentation order."""
    return {info.display_label: info.canonical_id for info in load_catalog()}
