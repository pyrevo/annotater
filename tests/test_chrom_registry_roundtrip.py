"""Round-trip and exact-version properties across all six registries.

These test runtime consistency (alias -> record -> other alias -> same
record); the independence of the data itself is checked by the upstream
oracle in ``tests/oracle/test_chromosome_alias_oracle.py``.
"""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

from streamlit_app.core import normalize_chromosomes
from streamlit_app.core.chrom_registry import AUTHORITIES, load_registry

ASSEMBLIES = ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "rn7"]


@pytest.mark.parametrize("assembly", ASSEMBLIES)
def test_every_alias_round_trips_through_every_available_authority(assembly):
    registry = load_registry(assembly)
    checked = 0
    for seq_id in registry:
        aliases = registry.record(seq_id).aliases
        for alias in aliases.values():
            assert registry.resolve(alias).seq_id == seq_id
            for other in AUTHORITIES:
                rendered = registry.render(seq_id, other)
                if other not in aliases:        # missing authority: not required
                    assert not rendered.rendered
                    continue
                assert rendered.alias == aliases[other]
                assert registry.resolve(rendered.alias).seq_id == seq_id
                checked += 1
    assert checked > len(registry)


@pytest.mark.parametrize("assembly", ASSEMBLIES)
def test_dataframe_normalization_round_trips_between_authority_pairs(assembly):
    registry = load_registry(assembly)
    records = [registry.record(s).aliases for s in registry]
    for source, target in itertools.permutations(AUTHORITIES, 2):
        both = [r for r in records if source in r and target in r]
        if not both:
            continue
        frame = pd.DataFrame({"chr": [r[source] for r in both],
                              "start": range(len(both)),
                              "end": [i + 10 for i in range(len(both))]})
        there = normalize_chromosomes(frame, assembly=assembly, target=target)
        assert there.report.complete
        assert there.dataframe["chr"].tolist() == [r[target] for r in both]
        back = normalize_chromosomes(there.dataframe, assembly=assembly,
                                     target=source)
        pd.testing.assert_frame_equal(back.dataframe, frame)


@pytest.mark.parametrize("assembly", ASSEMBLIES)
def test_normalization_is_idempotent_for_every_authority(assembly):
    registry = load_registry(assembly)
    names = [registry.record(s).aliases for s in registry][:200]
    for target in AUTHORITIES:
        pool = [a for r in names for a in r.values()]
        frame = pd.DataFrame({"chr": pool})
        once = normalize_chromosomes(frame, assembly=assembly, target=target)
        twice = normalize_chromosomes(once.dataframe, assembly=assembly,
                                      target=target)
        pd.testing.assert_frame_equal(once.dataframe, twice.dataframe)
        assert twice.report.renames == {}


# ---- exact versions: no stripping, guessing or neighbouring versions ---------

@pytest.mark.parametrize("assembly,exact,other_versions", [
    ("GRCh38", "NC_000001.11", ["NC_000001.10", "NC_000001.12", "NC_000001"]),
    ("hg19", "NC_000001.10", ["NC_000001.11", "NC_000001.9", "NC_000001"]),
    ("GRCh38", "CM000663.2", ["CM000663.1", "CM000663.3", "CM000663"]),
    ("hg19", "CM000663.1", ["CM000663.2", "CM000663"]),
])
def test_only_the_exact_versioned_accession_resolves(
        assembly, exact, other_versions):
    registry = load_registry(assembly)
    assert registry.resolve(exact).resolved
    for other in other_versions:
        assert not registry.resolve(other).resolved, other


def test_the_same_chromosome_has_different_accessions_in_different_assemblies():
    """NC_000001.10 (hg19) and NC_000001.11 (GRCh38) are different sequences
    of different assemblies; neither resolves in the other's registry."""
    assert load_registry("hg19").resolve("NC_000001.10").resolved
    assert not load_registry("GRCh38").resolve("NC_000001.10").resolved
    assert load_registry("GRCh38").resolve("NC_000001.11").resolved
    assert not load_registry("hg19").resolve("NC_000001.11").resolved


def test_normalization_does_not_strip_versions():
    frame = pd.DataFrame({"chr": ["NC_000001.11", "NC_000001.10", "NC_000001"]})
    result = normalize_chromosomes(frame, assembly="GRCh38", target="ucsc")
    assert result.dataframe["chr"].tolist() == [
        "chr1", "NC_000001.10", "NC_000001"]
    assert dict(result.report.unknown) == {"NC_000001.10": 1, "NC_000001": 1}
