"""Offline chromosome-alias registry.

Runtime API: ``load_registry`` and the small result/record types. The
registry builder (``builder``) is build-time tooling and is not part of the
runtime API. Nothing here uses the network. See SPEC 5.1.
"""

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
    "ChromosomeRegistry",
    "RegistryDataError",
    "RegistryError",
    "RenderResult",
    "ResolveResult",
    "SequenceRecord",
    "UnsupportedAssemblyError",
    "UnsupportedAuthorityError",
    "load_registry",
]
