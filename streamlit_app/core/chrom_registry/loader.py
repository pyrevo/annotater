"""Runtime chromosome-alias registry (offline, read-only; SPEC 5.1).

Model::

    external alias -> resolve (within one explicit assembly) -> seq_id
    seq_id -> render (verified alias for a target authority)

``seq_id`` is an opaque key. Nothing here parses it; every name comes from
the loaded record. Empty registry cells mean "no verified alias" and are
never filled in. The registry is read from packaged resources only: no
network, no working-directory paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from types import MappingProxyType

# Rendered authorities, in registry column order. The TSV header is
# validated against these on load (the builder tests pin the same tuple).
AUTHORITIES = ("ucsc", "assembly", "ensembl", "genbank", "refseq")
_HEADER = ("seq_id",) + AUTHORITIES

UNKNOWN = "unknown"
NO_ALIAS_FOR_TARGET = "no_alias_for_target"


class RegistryError(ValueError):
    """Base class for programmer/configuration/data errors."""


class UnsupportedAssemblyError(RegistryError):
    """The assembly has no registry (no fallback is ever attempted)."""


class UnsupportedAuthorityError(RegistryError):
    """The requested target authority is not a registry authority."""


class RegistryDataError(RegistryError):
    """Packaged registry data violate the registry contract."""


@dataclass(frozen=True)
class SequenceRecord:
    """One sequence of one assembly with its verified aliases."""

    seq_id: str
    aliases: Mapping[str, str]  # authority -> alias; absent = no alias

    def alias(self, authority: str) -> str | None:
        return self.aliases.get(authority)


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving one identifier. ``seq_id`` is set iff resolved."""

    identifier: str
    seq_id: str | None = None
    reason: str | None = None  # UNKNOWN when unresolved

    @property
    def resolved(self) -> bool:
        return self.seq_id is not None


@dataclass(frozen=True)
class RenderResult:
    """Outcome of rendering a known sequence for a target authority."""

    seq_id: str
    authority: str
    alias: str | None = None
    reason: str | None = None  # NO_ALIAS_FOR_TARGET when alias is None

    @property
    def rendered(self) -> bool:
        return self.alias is not None


class ChromosomeRegistry:
    """Immutable alias registry for one set of sequences.

    A bundled registry belongs to one genome assembly (``assembly_id``). A
    user-supplied (custom) registry has no assembly identity: its
    ``assembly_id`` is ``None`` and ``name`` says what it is. ``name`` is
    only a display/source label; it is never a scientific claim.

    Instances are immutable: bundled registries are cached and shared by
    every caller (and every GUI session), so no attribute can be assigned
    or deleted after construction.
    """

    __slots__ = ("_index", "_records", "assembly_id", "name")

    def __init__(
        self,
        assembly_id: str | None,
        records: Mapping[str, SequenceRecord],
        *,
        name: str | None = None,
    ):
        if assembly_id is None and not name:
            raise RegistryDataError(
                "a registry without an assembly id needs a display name"
            )
        records = MappingProxyType(dict(records))
        index: dict[str, str] = {}
        for seq_id, record in records.items():
            for alias in record.aliases.values():
                owner = index.setdefault(alias, seq_id)
                if owner != seq_id:
                    raise RegistryDataError(
                        f"{name or assembly_id}: alias {alias!r} belongs to "
                        f"both {owner!r} and {seq_id!r}"
                    )
        for attribute, value in (("assembly_id", assembly_id),
                                 ("name", name or assembly_id),
                                 ("_records", records),
                                 ("_index", MappingProxyType(index))):
            object.__setattr__(self, attribute, value)

    def __setattr__(self, attribute, value):
        raise AttributeError(
            f"ChromosomeRegistry is immutable (cannot set {attribute!r})")

    def __delattr__(self, attribute):
        raise AttributeError(
            f"ChromosomeRegistry is immutable (cannot delete {attribute!r})")

    @classmethod
    def from_tsv(cls, assembly_id: str, text: str) -> ChromosomeRegistry:
        lines = text.split("\n")
        if lines.pop() != "":
            raise RegistryDataError(f"{assembly_id}: missing final newline")
        if not lines or tuple(lines[0].split("\t")) != _HEADER:
            raise RegistryDataError(f"{assembly_id}: unexpected header")
        records: dict[str, SequenceRecord] = {}
        for number, line in enumerate(lines[1:], start=2):
            fields = line.split("\t")
            if len(fields) != len(_HEADER):
                raise RegistryDataError(
                    f"{assembly_id} line {number}: expected "
                    f"{len(_HEADER)} fields, got {len(fields)}"
                )
            seq_id, *cells = fields
            if not seq_id or not cells[0]:
                raise RegistryDataError(
                    f"{assembly_id} line {number}: empty seq_id or ucsc"
                )
            if seq_id in records:
                raise RegistryDataError(
                    f"{assembly_id}: duplicate seq_id {seq_id!r}"
                )
            aliases = {a: c for a, c in zip(AUTHORITIES, cells) if c}
            records[seq_id] = SequenceRecord(seq_id, MappingProxyType(aliases))
        if not records:
            raise RegistryDataError(f"{assembly_id}: registry has no records")
        return cls(assembly_id, records)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        """Iterate ``seq_id`` keys in registry order."""
        return iter(self._records)

    def __contains__(self, seq_id: object) -> bool:
        return seq_id in self._records

    def record(self, seq_id: str) -> SequenceRecord:
        """The record for a ``seq_id`` previously obtained from this
        registry. An unknown key is a programmer error (``KeyError``)."""
        return self._records[seq_id]

    def resolve(self, identifier: str) -> ResolveResult:
        """Exact, case-sensitive alias lookup within this assembly."""
        if not isinstance(identifier, str):
            raise TypeError(
                f"identifier must be str, got {type(identifier).__name__}"
            )
        seq_id = self._index.get(identifier)
        if seq_id is None:
            return ResolveResult(identifier, reason=UNKNOWN)
        return ResolveResult(identifier, seq_id=seq_id)

    def render(self, seq_id: str, authority: str) -> RenderResult:
        """The verified alias of a known sequence for ``authority``.

        An unknown ``authority`` raises ``UnsupportedAuthorityError``; a
        known sequence without an alias for it yields a
        ``NO_ALIAS_FOR_TARGET`` result. Nothing is substituted or inferred.
        """
        if authority not in AUTHORITIES:
            raise UnsupportedAuthorityError(
                f"unsupported authority {authority!r}; "
                f"expected one of {AUTHORITIES}"
            )
        alias = self._records[seq_id].aliases.get(authority)
        if alias is None:
            return RenderResult(seq_id, authority, reason=NO_ALIAS_FOR_TARGET)
        return RenderResult(seq_id, authority, alias=alias)


def _read_resource(name: str) -> str:
    return resources.files(__package__).joinpath(name).read_text(
        encoding="utf-8"
    )


def canonical_assembly_id(assembly: str) -> str:
    """The canonical bundled id for a canonical id or any accepted alias.

    Matching is exact and case-sensitive; an unknown name is an error (no
    fallback, no guessing).
    """
    from .catalog import find_assembly, load_catalog

    info = find_assembly(assembly)
    if info is None:
        raise UnsupportedAssemblyError(
            f"no chromosome registry for assembly {assembly!r}; supported: "
            f"{sorted((i.canonical_id for i in load_catalog()), key=str.casefold)}"
        )
    return info.canonical_id


def load_registry(assembly: str) -> ChromosomeRegistry:
    """Load the packaged registry for a canonical id or accepted alias.

    The result always carries the canonical id, whatever spelling was used,
    and is the same object for every spelling.
    """
    return _load_bundled(canonical_assembly_id(assembly))


@cache
def _load_bundled(canonical_id: str) -> ChromosomeRegistry:
    from .catalog import find_assembly

    info = find_assembly(canonical_id)
    return ChromosomeRegistry.from_tsv(
        canonical_id, _read_resource(info.registry_file))


# ``load_registry`` keeps the cache-control interface of the cache that backs
# it (one entry per canonical id, whatever spelling was requested).
load_registry.cache_clear = _load_bundled.cache_clear
load_registry.cache_info = _load_bundled.cache_info
