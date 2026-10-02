"""One place that turns a chosen chromosome source into a registry.

A chromosome source is either a bundled genome assembly (canonical id or
accepted alias) or the bytes of a user-supplied custom mapping. Callers
(the GUI, a future CLI) resolve it here exactly once; everything downstream
works on the resulting ``ChromosomeRegistry`` and never branches on where it
came from.
"""

from __future__ import annotations

from .custom import DEFAULT_MAX_BYTES, DEFAULT_MAX_ROWS, load_custom_registry
from .loader import ChromosomeRegistry, RegistryError, load_registry


def resolve_registry_source(
    *,
    assembly: str | None = None,
    mapping: bytes | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> ChromosomeRegistry:
    """The registry for exactly one of ``assembly`` or ``mapping``.

    ``assembly`` raises ``UnsupportedAssemblyError`` for an unknown name;
    ``mapping`` (custom TSV bytes) raises ``CustomRegistryError`` when the
    file is structurally invalid. Nothing is guessed or defaulted.
    """
    if (assembly is None) == (mapping is None):
        raise RegistryError(
            "give exactly one chromosome source: assembly= or mapping=")
    if assembly is not None:
        return load_registry(assembly)
    return load_custom_registry(
        mapping, max_bytes=max_bytes, max_rows=max_rows)
