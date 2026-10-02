"""Offline chromosome-alias registry.

Runtime API: ``load_registry`` and the small result/record types. The
registry builder (``builder``) is build-time tooling and is not part of the
runtime API. Nothing here uses the network. See SPEC 5.1.
"""

from .catalog import AssemblyInfo, assembly_options, load_catalog
from .loader import (
    AUTHORITIES,
    NO_ALIAS_FOR_TARGET,
    UNKNOWN,
    ChromosomeRegistry,
    RegistryDataError,
    RegistryError,
    RenderResult,
    ResolveResult,
    SequenceRecord,
    UnsupportedAssemblyError,
    UnsupportedAuthorityError,
    load_registry,
)

__all__ = [
    "AUTHORITIES",
    "NO_ALIAS_FOR_TARGET",
    "UNKNOWN",
    "AssemblyInfo",
    "ChromosomeRegistry",
    "RegistryDataError",
    "RegistryError",
    "RenderResult",
    "ResolveResult",
    "SequenceRecord",
    "UnsupportedAssemblyError",
    "UnsupportedAuthorityError",
    "assembly_options",
    "load_catalog",
    "load_registry",
]
