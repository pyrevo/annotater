"""Runtime registry API (resolve / render) over the packaged GRCh38 registry.

Resolve/render API over the packaged registries (SPEC 5.1).
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import textwrap
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import (
    AUTHORITIES,
    NO_ALIAS_FOR_TARGET,
    UNKNOWN,
    ChromosomeRegistry,
    RegistryDataError,
    UnsupportedAssemblyError,
    UnsupportedAuthorityError,
    builder,
    load_registry,
    loader,
)

ROOT = Path(__file__).resolve().parent.parent
HEADER = "seq_id\tucsc\tassembly\tensembl\tgenbank\trefseq\n"


@pytest.fixture(scope="module")
def reg():
    return load_registry("GRCh38")


def _seq(reg, identifier):
    result = reg.resolve(identifier)
    assert result.resolved, identifier
    return result.seq_id


# --- loading ---------------------------------------------------------------

def test_loads_every_builder_record(reg):
    assert reg.assembly_id == "GRCh38"
    text = (builder.PACKAGE_DIR / "data" / "GRCh38.tsv").read_text()
    assert len(reg) == len(text.splitlines()) - 1 == 711


def test_authorities_match_builder_schema():
    assert AUTHORITIES == builder.AUTHORITIES
    assert ("seq_id",) + AUTHORITIES == builder.HEADER


def test_load_is_cached_and_independent_of_cwd(tmp_path, monkeypatch):
    first = load_registry("GRCh38")
    monkeypatch.chdir(tmp_path)
    assert load_registry("GRCh38") is first
    loader.load_registry.cache_clear()
    fresh = load_registry("GRCh38")
    assert fresh is not first and len(fresh) == len(first)


@pytest.mark.parametrize("name", ["HG38", "grch38", "GRCh37", "HG19", "", "x"])
def test_unsupported_assembly_fails_clearly_without_fallback(name):
    with pytest.raises(UnsupportedAssemblyError, match="GRCh38.*hg19"):
        load_registry(name)


# --- resolve ---------------------------------------------------------------

def test_chromosome_1_aliases_resolve_to_one_record(reg):
    ids = {_seq(reg, a) for a in ("chr1", "1", "NC_000001.11", "CM000663.2")}
    assert len(ids) == 1
    (seq_id,) = ids
    assert dict(reg.record(seq_id).aliases) == {
        "ucsc": "chr1", "assembly": "1", "ensembl": "1",
        "genbank": "CM000663.2", "refseq": "NC_000001.11",
    }


def test_mitochondrial_aliases_resolve_to_one_record(reg):
    ids = {_seq(reg, a) for a in ("chrM", "MT", "J01415.2", "NC_012920.1")}
    assert len(ids) == 1
    (seq_id,) = ids
    assert dict(reg.record(seq_id).aliases) == {
        "ucsc": "chrM", "assembly": "MT", "ensembl": "MT",
        "genbank": "J01415.2", "refseq": "NC_012920.1",
    }
    assert ids != {_seq(reg, "chr1")}


@pytest.mark.parametrize("identifier", [
    "NC_000001",       # accession version is part of identity
    "NC_000001.10",    # a different (GRCh37) accession
    "CM000663",
    "Chr1", "CHR1", "chrx", "x",   # exact, case-sensitive
    "M", "chrMT", "chr23", "23", "MT ", " chr1", "chr01", "01",
    "unknown_contig", "",
])
def test_unknown_identifiers_are_not_guessed(reg, identifier):
    result = reg.resolve(identifier)
    assert not result.resolved
    assert result.seq_id is None and result.reason == UNKNOWN
    assert result.identifier == identifier


def test_resolve_requires_str(reg):
    for bad in (None, 1, float("nan"), b"chr1"):
        with pytest.raises(TypeError):
            reg.resolve(bad)


def test_alt_and_unplaced_resolve(reg):
    assert reg.resolve("chr10_GL383545v1_alt").resolved
    assert reg.resolve("GL383545.1").seq_id == reg.resolve("NW_003315934.1").seq_id
    assert reg.resolve("HSCHR10_1_CTG1").seq_id == _seq(reg, "chr10_GL383545v1_alt")
    assert reg.resolve("KI270752.1").seq_id == _seq(reg, "chrUn_KI270752v1")


# --- render ----------------------------------------------------------------

def test_render_each_authority_for_chr1(reg):
    seq_id = _seq(reg, "NC_000001.11")
    got = {a: reg.render(seq_id, a) for a in AUTHORITIES}
    assert {a: r.alias for a, r in got.items()} == {
        "ucsc": "chr1", "assembly": "1", "ensembl": "1",
        "genbank": "CM000663.2", "refseq": "NC_000001.11",
    }
    assert all(r.rendered and r.reason is None for r in got.values())
    assert all(r.seq_id == seq_id for r in got.values())


def test_unsupported_authority_fails_clearly(reg):
    seq_id = _seq(reg, "chr1")
    for bad in ("UCSC", "ncbi", "", "chr", None):
        with pytest.raises(UnsupportedAuthorityError):
            reg.render(seq_id, bad)


def test_render_unknown_seq_id_is_programmer_error(reg):
    with pytest.raises(KeyError):
        reg.render("GRCh38:not-a-record", "ucsc")


# --- unknown alias vs. no_alias_for_target ---------------------------------

def test_unknown_alias_differs_from_missing_target_alias(reg):
    unknown = reg.resolve("NC_000001")
    assert not unknown.resolved and unknown.reason == UNKNOWN

    known = reg.resolve("chr10_GL383545v1_alt")
    assert known.resolved and known.reason is None
    missing = reg.render(known.seq_id, "ensembl")
    assert not missing.rendered
    assert missing.alias is None and missing.reason == NO_ALIAS_FOR_TARGET
    # No substitution or fallback to another authority.
    assert missing.seq_id == known.seq_id and missing.authority == "ensembl"
    assert reg.render(known.seq_id, "assembly").alias == "HSCHR10_1_CTG1"
    assert UNKNOWN != NO_ALIAS_FOR_TARGET


def test_unplaced_sequence_without_refseq(reg):
    seq_id = _seq(reg, "chrUn_KI270752v1")
    assert reg.render(seq_id, "ensembl").alias == "KI270752.1"
    assert reg.render(seq_id, "genbank").alias == "KI270752.1"
    refseq = reg.render(seq_id, "refseq")
    assert refseq.alias is None and refseq.reason == NO_ALIAS_FOR_TARGET


# --- round trips -----------------------------------------------------------

@pytest.mark.parametrize("source", ["NC_000001.11", "chr1", "CM000663.2", "1",
                                    "NC_012920.1", "J01415.2", "MT", "chrM",
                                    "GL383545.1", "KI270752.1"])
def test_round_trip_through_every_available_authority(reg, source):
    seq_id = _seq(reg, source)
    rendered = 0
    for authority in AUTHORITIES:
        out = reg.render(seq_id, authority)
        if out.alias is None:
            continue
        rendered += 1
        assert reg.resolve(out.alias).seq_id == seq_id
    assert rendered >= 3


def test_every_record_alias_round_trips(reg):
    for seq_id in reg:  # whole registry, all authorities
        for authority in AUTHORITIES:
            out = reg.render(seq_id, authority)
            if out.rendered:
                assert reg.resolve(out.alias).seq_id == seq_id


# --- data integrity --------------------------------------------------------

def test_records_are_read_only(reg):
    record = reg.record(_seq(reg, "chr1"))
    with pytest.raises(TypeError):
        record.aliases["ucsc"] = "x"
    with pytest.raises(FrozenInstanceError):
        record.seq_id = "x"
    with pytest.raises(FrozenInstanceError):
        reg.resolve("chr1").seq_id = "x"


def test_no_alias_is_invented_for_empty_cells(reg):
    # Every non-empty rendered alias is exactly a TSV cell; every empty
    # cell renders as no_alias_for_target.
    text = (builder.PACKAGE_DIR / "data" / "GRCh38.tsv").read_text()
    for line in text.splitlines()[1:]:
        seq_id, *cells = line.split("\t")
        for authority, cell in zip(AUTHORITIES, cells):
            out = reg.render(seq_id, authority)
            assert out.alias == (cell or None)
            if not cell:
                assert out.reason == NO_ALIAS_FOR_TARGET


def test_duplicate_alias_across_records_fails_loudly():
    text = HEADER + "a\tchrA\t1\t\t\t\n" + "b\tchrB\t1\t\t\t\n"
    with pytest.raises(RegistryDataError, match="belongs to both"):
        ChromosomeRegistry.from_tsv("T", text)


def test_alias_equal_to_other_records_name_fails_loudly():
    text = HEADER + "a\tchrA\t\t\t\t\n" + "b\tchrB\tchrA\t\t\t\n"
    with pytest.raises(RegistryDataError):
        ChromosomeRegistry.from_tsv("T", text)


def test_same_alias_in_two_columns_of_one_record_is_allowed():
    reg = ChromosomeRegistry.from_tsv("T", HEADER + "a\tchrA\t1\t1\t\t\n")
    assert reg.resolve("1").seq_id == "a"


@pytest.mark.parametrize("text,match", [
    ("seq_id\tucsc\n", "header"),
    (HEADER, "no records"),
    (HEADER.rstrip("\n"), "final newline"),
    (HEADER + "a\tchrA\n", "expected 6 fields"),
    (HEADER + "\tchrA\t\t\t\t\n", "empty seq_id"),
    (HEADER + "a\t\t1\t\t\t\n", "empty seq_id or ucsc"),
    (HEADER + "a\tchrA\t\t\t\t\n" + "a\tchrB\t\t\t\t\n", "duplicate seq_id"),
])
def test_corrupt_packaged_data_fails_loudly(text, match):
    with pytest.raises(RegistryDataError, match=match):
        ChromosomeRegistry.from_tsv("T", text)


# --- seq_id opacity ---------------------------------------------------------

def test_seq_id_is_opaque_to_runtime():
    # Keys that look like "<assembly>:<name>" but contradict the record,
    # and keys with no structure at all, behave identically.
    text = (HEADER + "GRCh99:chrZ\tchrOne\tA1\t\t\t\n"
            + "42\tchrTwo\tA2\tE2\t\t\n")
    reg = ChromosomeRegistry.from_tsv("T", text)
    assert reg.resolve("chrOne").seq_id == "GRCh99:chrZ"
    assert reg.render("GRCh99:chrZ", "ucsc").alias == "chrOne"
    assert reg.render("42", "ensembl").alias == "E2"
    assert reg.resolve("chrZ").reason == UNKNOWN


def test_runtime_source_never_parses_seq_id():
    tree = ast.parse(Path(loader.__file__).read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"split", "partition", "rpartition",
                                       "rsplit", "startswith", "removeprefix"}):
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            # the only str.split used is the TSV tab/newline parse
            assert set(args) <= {"\t", "\n"}, ast.dump(node)


# --- no network --------------------------------------------------------------

def test_runtime_modules_import_no_network_clients():
    forbidden = {"urllib", "http", "socket", "requests", "ssl", "ftplib",
                 "httpx", "aiohttp"}
    tree = ast.parse(Path(loader.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & forbidden


def test_resolution_works_with_network_disabled():
    code = textwrap.dedent("""
        import socket
        def blocked(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket.connect = blocked
        socket.create_connection = blocked
        socket.getaddrinfo = blocked
        from streamlit_app.core.chrom_registry import load_registry
        r = load_registry("GRCh38")
        s = r.resolve("NC_000001.11").seq_id
        assert r.render(s, "ucsc").alias == "chr1"
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# --- packaging ---------------------------------------------------------------

def test_built_wheel_contains_runtime_registry_and_works(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed; cannot build the wheel")
    dist = tmp_path / "dist"
    build = subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist),
                            str(ROOT)], capture_output=True, text=True, check=False)
    assert build.returncode == 0, build.stderr
    (wheel,) = dist.glob("*.whl")
    prefix = "streamlit_app/core/chrom_registry/"
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        zf.extractall(tmp_path / "site")
    from streamlit_app.core.chrom_registry import load_catalog
    registry_files = [i.registry_file for i in load_catalog()]
    assert len(registry_files) == 64
    for required in ("catalog.json", "catalog.py", "loader.py", "source.py",
                     "custom.py", "__init__.py", *registry_files):
        assert prefix + required in names, required
    # Build-only inputs stay in the source tree and out of the runtime wheel.
    assert not [n for n in names if n.startswith(prefix + "upstream/")]
    assert prefix + "sources.json" not in names
    with zipfile.ZipFile(wheel) as zf:
        registry_bytes = sum(i.compress_size for i in zf.infolist()
                             if i.filename.startswith(prefix + "data/"))
    assert registry_bytes < 4_000_000          # compressed registries
    assert wheel.stat().st_size < 5_000_000

    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(tmp_path / "site")!r})
        from streamlit_app.core.chrom_registry import load_registry, loader
        assert loader.__file__.startswith({str(tmp_path / "site")!r}), loader.__file__
        r = load_registry("GRCh38")
        s = r.resolve("CM000663.2").seq_id
        assert r.render(s, "refseq").alias == "NC_000001.11"
        h = load_registry("hg19")
        t = h.resolve("CM000663.1").seq_id
        assert h.render(t, "refseq").alias == "NC_000001.10"
        assert h.resolve("chrM").seq_id != r.resolve("chrM").seq_id
        assert h.render(h.resolve("chrMT").seq_id, "ensembl").alias == "MT"
        assert not h.render(h.resolve("chrM").seq_id, "ensembl").rendered
        counts = [len(load_registry(a)) for a in
                  ("GRCm39", "dm6", "GRCz11", "rn7")]
        d = load_registry("dm6")
        assert d.render(d.resolve("2L").seq_id, "ucsc").alias == "chr2L"
        m = load_registry("mm10")
        assert m.render(m.resolve("NC_000067.6").seq_id, "ucsc").alias == "chr1"
        print(len(r), len(h), *counts)
    """)
    run = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                         capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "711 298 61 1870 1923 176"
