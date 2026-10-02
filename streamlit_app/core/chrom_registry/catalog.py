"""Runtime catalog of the bundled genome assemblies.

``catalog.json`` is generated at build time (``scripts/update_chrom_catalog.py``)
from the build manifest ``sources.json``; it carries only what the runtime
needs: the assembly id, the packaged registry file and the UCSC-provided
display metadata. Reading it loads no registry. Nothing here uses the
network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

CATALOG_FILE = "catalog.json"


@dataclass(frozen=True)
class AssemblyInfo:
    """One bundled assembly. Text fields are UCSC catalog values verbatim."""

    assembly_id: str          # runtime id (``load_registry`` argument)
    ucsc_db: str
    label: str                # unique, user-facing option text
    organism: str | None
    scientific_name: str | None
    description: str | None
    registry_file: str


@cache
def load_catalog() -> tuple[AssemblyInfo, ...]:
    """The bundled assemblies in presentation order."""
    text = resources.files(__package__).joinpath(CATALOG_FILE).read_text(
        encoding="utf-8")
    config = json.loads(text)
    if config.get("schema_version") != 1:
        raise ValueError("unsupported catalog.json schema_version")
    return tuple(AssemblyInfo(**entry) for entry in config["assemblies"])


def assembly_options() -> dict[str, str]:
    """``{label: assembly_id}`` in presentation order; labels are unique."""
    return {info.label: info.assembly_id for info in load_catalog()}
