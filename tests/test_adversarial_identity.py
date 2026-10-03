"""Adversarial review (Task 10): identity, opacity, isolation, catalog.

Each test tries to break the central contract

    identifier -> resolve within one explicit registry -> opaque record
               -> render a verified alias of that record

Expectations are derived independently of the resolver under test: from the
pinned upstream alias tables, from a plain CSV read of the generated
registry text, or from a brute-force model written here.
"""

from __future__ import annotations

import ast
import csv
import gzip
import json
import random
import re
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import (
    AUTHORITIES,
    ChromosomeRegistry,
    SequenceRecord,
    builder,
    find_assembly,
    load_catalog,
    load_registry,
)
from streamlit_app.core.chromosome_normalization import (
    normalize_chromosomes_with_registry,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = builder.PACKAGE_DIR
CATALOG = load_catalog()
CANONICAL = [i.canonical_id for i in CATALOG]
SIX = ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11", "mRatBN7.2"]


def _tsv_aliases(info) -> dict[str, set[str]]:
    """``{alias: {record handles}}`` read straight from the registry text."""
    text = (PACKAGE / info.registry_file).read_text(encoding="utf-8")
    table: dict[str, set[str]] = {}
    for row in csv.DictReader(text.splitlines(), delimiter="\t"):
        for authority in AUTHORITIES:
            if row[authority]:
                table.setdefault(row[authority], set()).add(row["seq_id"])
    return table


# ---- 2. scientific identity attack ---------------------------------------------

# Strings that look like valid GRCh38 names but are not. None may resolve.
LOOKALIKES = [
    " chr1", "chr1 ", "chr1\t", "chr1\n", "\tchr1", "chr1\r", "chr1\x00",
    "CHR1", "Chr1", "cHr1", "chr01", "chr001", "01", "001", "1.0", "+1",
    "chr1.", "chr1_", "chr_1", "chr-1", "chr 1", "chr1chr1", "chr11 ",
    "﻿chr1", "\u200bchr1", "chr\u200b1", "chr1\u200b", "chr1‍",
    "chr 1", "chr1 ", "chr1 ", "chr1 ",
    "ｃｈｒ１", "chr１", "chr١", "chr1́",
    "chг1", "chrI",                      # Cyrillic g, Latin I
    "NC_000001.11 ", " NC_000001.11", "nc_000001.11", "NC_000001.11.1",
    "NC_000001.12", "NC_000001.10", "NC_000001.1", "NC_000001", "NC_00000111",
    "NC-000001.11", "NC_000001,11", "NC_0000001.11", "CM000663", "CM000663.1",
    "CM000663.3", "cm000663.2", "GL000008.2 ", "chrUn_gl000195", "",
    "chrM1", "chrMT", "M", "mt", "Mt", "chrmt", "*", ".", "1;2", "1,2",
    "x" * 10_000, "chr1" * 3000, "NC_000001.11" * 4,
]


@pytest.mark.parametrize("name", LOOKALIKES)
def test_no_lookalike_resolves_in_grch38(name):
    registry = load_registry("GRCh38")
    assert not registry.resolve(name).resolved, repr(name)
    out = normalize_chromosomes_with_registry(
        _frame([name]), registry=registry, target="ucsc")
    assert out.dataframe["chr"].tolist() == [name]       # kept verbatim
    assert dict(out.report.unknown) == {name: 1}


def test_grch38_valid_names_remain_exact():
    registry = load_registry("GRCh38")
    assert {registry.resolve(n).seq_id for n in
            ("1", "chr1", "NC_000001.11", "CM000663.2")} != {None}
    assert len({registry.resolve(n).seq_id for n in
                ("1", "chr1", "NC_000001.11", "CM000663.2")}) == 1


def test_adjacent_accession_versions_are_different_assemblies_not_aliases():
    grch38, hg19 = load_registry("GRCh38"), load_registry("hg19")
    assert grch38.resolve("NC_000001.11").resolved
    assert not grch38.resolve("NC_000001.10").resolved
    assert hg19.resolve("NC_000001.10").resolved
    assert not hg19.resolve("NC_000001.11").resolved


def _frame(names):
    import pandas as pd
    return pd.DataFrame({"chr": names, "start": range(len(names)),
                         "end": range(1, len(names) + 1)})


def _mutations(alias: str):
    """Edits that must not preserve identity (except by coincidence)."""
    yield alias + " "
    yield " " + alias
    yield alias + "\u200b"
    yield alias[:-1]
    yield alias[1:]
    yield alias + "0"
    yield "0" + alias
    yield alias + "."
    if alias.swapcase() != alias:
        yield alias.swapcase()
    if alias.lower() != alias:
        yield alias.lower()
    if alias.upper() != alias:
        yield alias.upper()


@pytest.mark.parametrize("info", CATALOG, ids=lambda i: i.canonical_id)
def test_resolution_is_exactly_the_alias_table_for_every_bundled_assembly(info):
    """Property: resolve(s) succeeds iff s is exactly a registry alias, for
    every alias and for edits of it, checked against a plain CSV read."""
    table = _tsv_aliases(info)
    registry = load_registry(info.canonical_id)
    assert len(table) > 0
    aliases = sorted(table)
    rng = random.Random(info.canonical_id)
    sample = aliases if len(aliases) <= 300 else rng.sample(aliases, 300)
    for alias in sample:
        got = registry.resolve(alias)
        assert got.resolved and {got.seq_id} == table[alias], alias
        for mutated in _mutations(alias):
            expected = table.get(mutated)
            got = registry.resolve(mutated)
            assert got.resolved == (expected is not None), (alias, mutated)
            if expected is not None:
                assert {got.seq_id} == expected


# ---- 3. seq_id opacity ---------------------------------------------------------

def _scrambled(registry: ChromosomeRegistry, namer) -> ChromosomeRegistry:
    """The same sequences and aliases under different opaque ids."""
    records = {}
    for index, seq_id in enumerate(registry):
        new = namer(index, registry.record(seq_id))
        records[new] = SequenceRecord(new, registry.record(seq_id).aliases)
    return ChromosomeRegistry(registry.assembly_id, records)


NAMERS = {
    "numeric": lambda i, r: str(i),
    "reversed-order-looking": lambda i, r: f"z{10**6 - i}",
    # ids that *lie*: another assembly, a chromosome, mitochondria, a naming
    "lying": lambda i, r: f"GRCm39:chrM#{i}:ensembl",
    "custom-like": lambda i, r: f"custom:{i:06d}",
}


@pytest.mark.parametrize("assembly", ["GRCh38", "hg19", "dm6"])
@pytest.mark.parametrize("namer", sorted(NAMERS))
def test_behavior_does_not_depend_on_the_text_of_seq_ids(assembly, namer):
    original = load_registry(assembly)
    scrambled = _scrambled(original, NAMERS[namer])
    names = [alias for s in original
             for alias in original.record(s).aliases.values()]
    names += ["unknown-name", "chrMT", "MT", "M", "1", "X"]
    for target in AUTHORITIES:
        a = normalize_chromosomes_with_registry(
            _frame(names), registry=original, target=target)
        b = normalize_chromosomes_with_registry(
            _frame(names), registry=scrambled, target=target)
        assert a.dataframe["chr"].tolist() == b.dataframe["chr"].tolist()
        assert a.report == b.report


_PARSING_METHODS = {"split", "rsplit", "partition", "rpartition", "startswith",
                    "endswith", "removeprefix", "removesuffix", "lstrip",
                    "rstrip", "strip", "lower", "upper", "casefold", "find",
                    "index", "count", "replace", "isdigit", "isnumeric"}


def _production_modules():
    base = ROOT / "streamlit_app"
    return [p for p in base.rglob("*.py")
            if "chrom_registry/builder.py" not in p.as_posix()]


def test_no_production_code_parses_or_slices_a_seq_id():
    """Static: a name containing ``seq_id`` is never the receiver of a string
    method or subscripted/sliced (the builder, which *creates* ids at build
    time, is excluded and checked separately below)."""
    offenders = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if (isinstance(node, ast.Attribute)
                    and node.attr in _PARSING_METHODS) or isinstance(node, ast.Subscript):
                target = node.value
            elif isinstance(node, ast.Compare) and any(
                    isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                    for op in node.ops):
                # ordering comparisons on ids would be a semantic dependency
                names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                names |= {n.attr for n in ast.walk(node)
                          if isinstance(n, ast.Attribute)}
                if any("seq_id" in n for n in names):
                    offenders.append((path.name, node.lineno, "ordering"))
            if target is not None:
                text = ast.unparse(target)
                if "seq_id" in text:
                    offenders.append((path.name, node.lineno, text))
    assert offenders == []


def test_seq_ids_are_only_dict_keys_and_equality_in_the_runtime():
    # sorting/min/max over ids would impose an order: not in runtime modules
    for name in ("loader.py", "custom.py", "source.py"):
        text = (PACKAGE / name).read_text(encoding="utf-8")
        assert not re.search(r"sorted\([^)]*seq_id|min\([^)]*seq_id|"
                             r"max\([^)]*seq_id", text), name


def test_builder_ids_are_made_at_build_time_and_never_read_back():
    text = (PACKAGE / "builder.py").read_text(encoding="utf-8")
    assert text.count('f"{assembly_id}:{chrom}"') == 1
    assert ".split(\":\")" not in text


# ---- 4. assembly isolation ---------------------------------------------------------

SHARED = ["1", "2", "X", "Y", "MT", "chr1", "chrX", "chrY", "chrM", "I", "IV",
          "2L", "chr2L"]


def test_shared_strings_resolve_only_within_the_selected_assembly():
    tables = {i.canonical_id: _tsv_aliases(i) for i in CATALOG}
    rng = random.Random(7)
    order = [(i.canonical_id, spelling) for i in CATALOG
             for spelling in i.names]
    for _ in range(3):
        rng.shuffle(order)
        for canonical, spelling in order:           # alternate, aliases too
            registry = load_registry(spelling)
            assert registry.assembly_id == canonical
            table = tables[canonical]
            for name in SHARED:
                got = registry.resolve(name)
                assert got.resolved == (name in table), (canonical, name)
                if got.resolved:
                    assert {got.seq_id} == table[name]
                    assert registry.record(got.seq_id).aliases["ucsc"]


def test_same_string_means_different_sequences_across_assemblies():
    chr1 = {}
    for info in CATALOG:
        registry = load_registry(info.canonical_id)
        got = registry.resolve("chr1")
        if got.resolved:
            chr1[info.canonical_id] = dict(registry.record(got.seq_id).aliases)
    assert len(chr1) > 20
    refseqs = {a: v.get("refseq") for a, v in chr1.items()}
    assert refseqs["GRCh38"] == "NC_000001.11" and refseqs["hg19"] == "NC_000001.10"
    assert refseqs["GRCm38"] != refseqs["GRCm39"]
    # a record never carries another assembly's alias
    for aliases in chr1.values():
        assert aliases["ucsc"] == "chr1"


def test_registry_objects_are_shared_per_canonical_id_and_never_mixed():
    seen = {}
    for info in CATALOG:
        reg = load_registry(info.canonical_id)
        assert seen.setdefault(id(reg), info.canonical_id) == info.canonical_id
        for alias in info.aliases:
            assert load_registry(alias) is reg
    assert len(seen) == 64


def test_bundled_registries_are_immutable_so_sharing_them_is_safe():
    reg = load_registry("GRCh38")
    seq = next(iter(reg))
    with pytest.raises(TypeError):
        reg.record(seq).aliases["ucsc"] = "x"
    with pytest.raises(AttributeError):
        reg.record(seq).seq_id = "x"
    with pytest.raises(TypeError):
        reg._records["x"] = None
    with pytest.raises(TypeError):
        reg._index["x"] = seq


# ---- 5. canonical-id overrides, independently -------------------------------------

AUDIT = {a["db"]: a for a in json.loads(
    (ROOT / "audits/chrom_alias_catalog/report.json").read_text())["assemblies"]}
MANIFEST = json.loads((PACKAGE / "sources.json").read_text())
OVERRIDES = MANIFEST["bundle_policy"]["canonical_id_overrides"]


@pytest.mark.parametrize("db,name", sorted(OVERRIDES.items()))
def test_each_override_is_the_verbatim_ucsc_description_token(db, name):
    """Checked against the UCSC catalog snapshot (the audit), not against
    sources.json, which the generator derived the override from."""
    description = AUDIT[db]["assembly_name"]
    assert description.count(f"({name}/{db})") == 1
    # a whole-token name: no institution, version prefix or spaces
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
    assert find_assembly(name).ucsc_db == db
    assert find_assembly(db).canonical_id == name


def test_canfam3_keeps_its_db_id_because_the_token_has_a_prefix():
    description = AUDIT["canFam3"]["assembly_name"]
    assert "(Broad CanFam3.1/canFam3)" in description
    assert find_assembly("canFam3").canonical_id == "canFam3"
    assert "canFam3" not in OVERRIDES
    assert find_assembly("CanFam3.1") is None


def test_hg19_is_not_grch37_the_mitochondrial_sequences_differ():
    """Independent of the registry: read the pinned UCSC table and the pinned
    Ensembl evidence. hg19 chrM is NC_001807.4 (16,571 bp); GRCh37's MT is
    NC_012920.1 (16,569 bp), which UCSC's hg19 table calls chrMT."""
    entry = next(a for a in MANIFEST["assemblies"] if a["assembly_id"] == "hg19")
    rows = [line.split("\t") for line in gzip.decompress(
        (PACKAGE / entry["upstream_file"]).read_bytes()
    ).decode().splitlines()]
    chrom_of = {alias: chrom for alias, chrom, _ in rows}
    assert chrom_of["NC_001807.4"] == "chrM"
    assert chrom_of["NC_012920.1"] == chrom_of["MT"] == "chrMT"
    assert chrom_of["NC_001807.4"] != chrom_of["NC_012920.1"]
    evidence = (PACKAGE / entry["ensembl_evidence"]["evidence_file"]
                ).read_text().splitlines()
    header = evidence[0].split("\t")
    mt = [dict(zip(header, line.split("\t"))) for line in evidence[1:]
          if line.split("\t")[0] == "MT"]
    assert len(mt) == 1 and mt[0]["length"] == "16569"
    assert mt[0]["refseq"] == "NC_012920.1"      # the GRCh37 MT, not NC_001807
    assert entry["canonical_id"] == "hg19"
    assert find_assembly("GRCh37") is None


# ---- 7. catalog integrity ---------------------------------------------------------------

def test_catalog_and_packaged_files_correspond_exactly():
    data_files = {f"data/{p.name}" for p in (PACKAGE / "data").glob("*.tsv")}
    assert data_files == {i.registry_file for i in CATALOG}
    manifest_files = {e["registry_file"] for e in MANIFEST["assemblies"]}
    assert manifest_files == data_files
    upstream = {p.name for p in (PACKAGE / "upstream").glob("*.chromAlias.txt.gz")}
    assert upstream == {Path(e["upstream_file"]).name
                        for e in MANIFEST["assemblies"]}
    assert not [p for p in (PACKAGE / "data").iterdir()
                if p.suffix != ".tsv"]


def test_every_entry_is_reachable_nonempty_and_matches_the_audit():
    labels = [i.display_label for i in CATALOG]
    assert len(labels) == len(set(labels)) == 64
    for info in CATALOG:
        registry = load_registry(info.canonical_id)
        assert len(registry) == AUDIT[info.ucsc_db]["sequence_records"] > 0
        for name in info.names:
            assert load_registry(name) is registry


def test_every_aliases_unique_even_across_authorities_inside_each_registry():
    for info in CATALOG:
        text = (PACKAGE / info.registry_file).read_text()
        seen = {}
        for row in csv.DictReader(text.splitlines(), delimiter="\t"):
            for authority in AUTHORITIES:
                cell = row[authority]
                if cell:
                    assert seen.setdefault(cell, row["seq_id"]) == row["seq_id"]


# ---- 8. the six deep assemblies: probes of human-centric assumptions -------------

def _upstream(assembly_key: str):
    entry = next(a for a in MANIFEST["assemblies"]
                 if a["assembly_id"] == assembly_key)
    lines = gzip.decompress((PACKAGE / entry["upstream_file"]).read_bytes()
                            ).decode().splitlines()
    return [tuple(line.split("\t")) for line in lines]


def test_dm6_arm_names_and_missing_names_are_not_guessed():
    reg = load_registry("dm6")
    for arm in ("2L", "2R", "3L", "3R", "X", "Y", "4"):
        assert reg.record(reg.resolve(arm).seq_id).aliases["ucsc"] == f"chr{arm}"
        assert reg.resolve(f"chr{arm}").seq_id == reg.resolve(arm).seq_id
    chrm = reg.record(reg.resolve("chrM").seq_id).aliases
    assert "ensembl" not in chrm                 # never invented from 'MT'
    assert not reg.resolve("MT").resolved and not reg.resolve("M").resolved
    assert not reg.resolve("chr1").resolved       # no chromosome 1 in flies
    assert not reg.resolve("chr2").resolved       # 2L/2R are not 'chr2'


def test_grcz11_high_numbered_chromosomes_and_scaffolds():
    reg = load_registry("GRCz11")
    for n in range(1, 26):
        assert reg.resolve(f"chr{n}").resolved and reg.resolve(str(n)).resolved
    assert not reg.resolve("chr26").resolved
    assert not reg.resolve("chrX").resolved       # zebrafish has no X
    mt = reg.record(reg.resolve("MT").seq_id).aliases
    assert mt["ucsc"] == "chrM" and mt["ensembl"] == "MT"
    scaffold = reg.record(reg.resolve("KN150246.1").seq_id).aliases
    assert scaffold["ucsc"] == "chrUn_KN150246v1"


@pytest.mark.parametrize("key", ["GRCh38", "hg19", "GRCm39", "dm6", "GRCz11",
                                 "rn7"])
def test_six_assemblies_record_set_equals_the_upstream_chromosomes(key):
    chroms = {chrom for _, chrom, _ in _upstream(key)}
    reg = load_registry(key)
    assert {reg.record(s).aliases["ucsc"] for s in reg} == chroms
    for alias, chrom, _ in _upstream(key):
        assert reg.record(reg.resolve(alias).seq_id).aliases["ucsc"] == chrom


# ---- 9. thin assemblies ---------------------------------------------------------------

def test_thin_assemblies_are_narrow_but_never_misleading():
    fr2, wuhan = load_registry("fr2"), load_registry("wuhCor1")
    assert len(fr2) == len(wuhan) == 1
    # a scaffold of a full genome is reported unknown, never normalized
    out = normalize_chromosomes_with_registry(
        _frame(["scaffold_1", "chrM"]), registry=fr2, target="ensembl")
    assert out.dataframe["chr"].tolist() == ["scaffold_1", "MT"]
    assert dict(out.report.unknown) == {"scaffold_1": 1}
    assert not out.report.complete


# ---- 30. independence: identity invariants from the raw catalog file ----------------------

def test_catalog_json_identity_invariants_without_the_production_validator():
    raw = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2 and len(raw["assemblies"]) == 64
    owner, folded = {}, {}
    for entry in raw["assemblies"]:
        assert set(entry) == {"canonical_id", "ucsc_db", "aliases",
                              "display_label", "organism", "scientific_name",
                              "description", "registry_file"}
        names = [entry["canonical_id"], *entry["aliases"]]
        assert len(set(names)) == len(names)            # no repeats in one entry
        assert entry["canonical_id"] not in entry["aliases"]
        assert entry["ucsc_db"] in names
        assert entry["aliases"] == sorted(entry["aliases"])
        for name in names:
            assert name not in owner, (name, owner.get(name))
            owner[name] = entry["canonical_id"]
            assert folded.setdefault(name.casefold(), name) == name
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
    manifest = {e["assembly_id"]: e for e in MANIFEST["assemblies"]}
    for key, entry in manifest.items():
        assert owner[key] == entry["canonical_id"]          # old id still maps
        assert owner[entry["ucsc_db"]] == entry["canonical_id"]


def test_concurrent_first_loads_from_many_sessions_are_equivalent_and_canonical():
    """Streamlit serves sessions on threads. A racing first load may build the
    registry twice, but every result must be identical in content and carry
    the canonical id; the cache then settles on one object."""
    from concurrent.futures import ThreadPoolExecutor
    load_registry.cache_clear()
    spellings = [n for i in CATALOG[:12] for n in i.names] * 4
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda n: (n, load_registry(n)), spellings))
    for name, registry in results:
        info = find_assembly(name)
        assert registry.assembly_id == info.canonical_id
        reference = load_registry(info.canonical_id)
        assert len(registry) == len(reference)
        assert list(registry) == list(reference)
        sample = list(reference)[:20]
        for seq in sample:
            assert dict(registry.record(seq).aliases) == dict(
                reference.record(seq).aliases)
    assert all(load_registry(n) is load_registry(find_assembly(n).canonical_id)
               for n in spellings)
