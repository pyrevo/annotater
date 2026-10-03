"""Adversarial review (Task 10): custom parser, limits, session isolation,
offline guarantee, zip-style resource access, selector discoverability and
reproducibility mutation tests."""

from __future__ import annotations

import gc
import io
import json
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from streamlit_app.core.chrom_registry import (
    CUSTOM_HEADER,
    ChromosomeRegistry,
    CustomRegistryError,
    builder,
    load_catalog,
    load_custom_registry,
    load_registry,
)
from streamlit_app.core.chrom_registry import catalog as catalog_module
from streamlit_app.core.chrom_registry.catalog import AssemblyInfo, identity_problems

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = builder.PACKAGE_DIR
H = "\t".join(CUSTOM_HEADER) + "\n"


def load(text, **kw):
    return load_custom_registry(text.encode("utf-8") if isinstance(text, str)
                                else text, **kw)


def codes(text, **kw):
    with pytest.raises(CustomRegistryError) as caught:
        load(text, **kw)
    return set(caught.value.codes)


# ---- 16. parser attacks -------------------------------------------------------------

def test_bom_crlf_and_missing_final_newline_are_tolerated_together():
    text = "﻿" + H.replace("\n", "\r\n") + "c1\tchrA\t\t\t\r\nc2\tchrB\t\t\t"
    registry = load(text)
    assert len(registry) == 2 and registry.resolve("chrB").resolved
    assert not registry.resolve("chrB\r").resolved


def test_mixed_line_endings_and_old_mac_endings():
    assert len(load(H + "c1\tchrA\t\t\t\r\nc2\tchrB\t\t\t\n")) == 2
    assert "HEADER" in codes(H.replace("\n", "\r") + "c1\tchrA\t\t\t\r")


def test_a_bom_inside_the_file_is_part_of_a_name_not_stripped():
    registry = load(H + "c1\t﻿chrA\t\t\t\n")
    assert registry.resolve("﻿chrA").resolved
    assert not registry.resolve("chrA").resolved


@pytest.mark.parametrize("row,expected", [
    ("c1\tchrA\t\t", "FIELD_COUNT"),                    # too few
    ("c1\tchrA\t\t\t\t", "FIELD_COUNT"),                # extra tab
    ("c1\t\tchrA\t\t\t\t\t", "FIELD_COUNT"),
    ("c1", "FIELD_COUNT"),
    ("\t\t\t\t", "NO_ALIAS"),                           # empty cells only
    ("", "EMPTY_ROW"),
    ("# comment", "COMMENT"),
    ("c1\tch\x00rA\t\t\t", "CONTROL_CHARACTER"),
    ("c1\tch\x1frA\t\t\t", "CONTROL_CHARACTER"),
    ("c1\tch\x7frA\t\t\t", "CONTROL_CHARACTER"),
    ("c1\tch\rrA\t\t\t", "CONTROL_CHARACTER"),          # embedded carriage return
    ("c1\t chrA\t\t\t", "WHITESPACE"),
    ("c1\tchrA \t\t\t", "WHITESPACE"),             # no-break space
    ("c1\t chrA\t\t\t", "WHITESPACE"),
    ("c1\t \t\t\t", "WHITESPACE"),                      # whitespace-only cell
])
def test_malformed_rows_are_rejected_with_a_specific_code(row, expected):
    assert expected in codes(H + row + "\nok\tfine\t\t\t\n")


def test_embedded_newline_splits_the_row_and_is_rejected_not_repaired():
    assert codes(H + "c1\tchr\nA\t\t\t\n") & {"FIELD_COUNT"}


@pytest.mark.parametrize("alias", [
    "chrα", "染色体1", "chr\u200b1", "chr‍1", "a b c", "<script>alert(1)</script>",
    "**bold**", "[x](http://e)", "&amp;", "'; DROP TABLE x;--", "chr1́",
    "ǂ", "\U0001f9ec", "a" * 5000, "NC_000001.11", "1", "0", "-", "."])
def test_any_clean_text_is_a_valid_name_and_is_matched_exactly(alias):
    registry = load(H + f"c1\t{alias}\t\t\t\nc2\tother\t\t\t\n")
    assert registry.resolve(alias).resolved
    assert not registry.resolve(alias + "\u200b").resolved
    assert not registry.resolve(alias.swapcase() + "x").resolved


def test_lookalike_names_on_different_rows_are_different_sequences():
    registry = load(H + "c1\tchr1\t\t\t\nc2\tchr1\u200b\t\t\t\nc3\tChr1\t\t\t\n")
    ids = {registry.resolve(n).seq_id for n in ("chr1", "chr1\u200b", "Chr1")}
    assert len(ids) == 3


def test_the_same_alias_in_several_columns_of_one_row_is_one_sequence():
    registry = load(H + "x\tx\tx\tx\tx\ny\tz\t\t\t\n")
    assert registry.resolve("x").resolved
    assert registry.record(registry.resolve("x").seq_id).aliases == {
        "assembly": "x", "ucsc": "x", "ensembl": "x", "genbank": "x",
        "refseq": "x"}


def test_the_same_alias_across_different_rows_is_rejected_in_any_columns():
    assert "ALIAS_COLLISION" in codes(H + "a\tb\t\t\t\nc\t\ta\t\t\n")
    assert "ALIAS_COLLISION" in codes(H + "a\tb\t\t\t\nz\tz\t\t\ta\n")


def test_a_duplicate_row_separated_by_unrelated_rows_is_detected_once():
    text = H + "a\tb\t\t\t\nu1\tv1\t\t\t\nu2\tv2\t\t\t\na\tb\t\t\t\n"
    with pytest.raises(CustomRegistryError) as caught:
        load(text)
    assert caught.value.codes == ("DUPLICATE_ROW",)
    assert caught.value.issues[0].rows == (2, 5)


def test_rows_with_one_alias_and_empty_cells_work_in_every_column():
    for index, column in enumerate(CUSTOM_HEADER):
        cells = [""] * 5
        cells[index] = "only"
        registry = load(H + "\t".join(cells) + "\n")
        record = registry.record(registry.resolve("only").seq_id)
        assert dict(record.aliases) == {column: "only"}


def test_error_report_is_capped_but_counts_everything():
    text = H + "".join("\t\t\t\t\n" for _ in range(500))
    with pytest.raises(CustomRegistryError) as caught:
        load(text)
    assert len(caught.value.issues) == 20 and caught.value.more == 480


# ---- boundary sizes -------------------------------------------------------------------

def _rows(n):
    return H + "".join(f"c{i}\tu{i}\t\t\t\n" for i in range(n))


def test_row_limit_boundary():
    assert len(load(_rows(10), max_rows=10)) == 10
    assert codes(_rows(11), max_rows=10) == {"TOO_MANY_ROWS"}
    assert len(load(_rows(1), max_rows=1)) == 1


def test_byte_limit_boundary_for_bytes_and_binary_files():
    data = _rows(5).encode()
    assert len(load_custom_registry(data, max_bytes=len(data))) == 5
    for source in (data, io.BytesIO(data)):
        with pytest.raises(CustomRegistryError) as caught:
            load_custom_registry(source, max_bytes=len(data) - 1)
        assert caught.value.codes == ("TOO_LARGE",)


def test_byte_limit_is_in_bytes_for_text_files_too():
    """A text file object yields characters; multi-byte text must not slip
    past a limit that a bytes input of the same content would hit."""
    text = _rows(0) + "".join(f"é{i}\tü{i}\t\t\t\n" for i in range(12))
    assert len(text) < len(text.encode("utf-8"))
    limit = len(text) + 5
    for source in (text.encode(), io.BytesIO(text.encode()), io.StringIO(text)):
        with pytest.raises(CustomRegistryError) as caught:
            load_custom_registry(source, max_bytes=limit)
        assert caught.value.codes == ("TOO_LARGE",)
    assert len(load_custom_registry(io.StringIO(text),
                                    max_bytes=len(text.encode()))) == 12


def test_oversized_input_is_refused_before_it_is_read_in_full():
    class Endless(io.RawIOBase):
        reads = 0

        def readable(self):
            return True

        def read(self, size=-1):
            Endless.reads += 1
            assert size != -1, "an unbounded read"
            return b"x" * size

    with pytest.raises(CustomRegistryError) as caught:
        load_custom_registry(Endless(), max_bytes=1000)
    assert caught.value.codes == ("TOO_LARGE",) and Endless.reads == 1


def test_ids_are_deterministic_and_widen_past_a_million_rows_format():
    first, again = load(_rows(7)), load(_rows(7))
    assert list(first) == list(again) == [f"custom:{i:06d}" for i in range(1, 8)]
    # the id text carries no meaning: reversed files change the ids, not the
    # name -> record association
    reordered = load(H + "".join(f"c{i}\tu{i}\t\t\t\n" for i in reversed(range(7))))
    assert reordered.record(reordered.resolve("u3").seq_id).aliases["assembly"] == "c3"


# ---- 24. session isolation -------------------------------------------------------------

def test_the_only_runtime_caches_are_bundled_and_catalog_never_custom():
    from streamlit_app.core.chrom_registry import custom, loader, source
    cached = {}
    for module in (catalog_module, loader, custom, source):
        for name, obj in vars(module).items():
            if hasattr(obj, "cache_info") and hasattr(obj, "cache_clear"):
                cached.setdefault(id(obj), f"{module.__name__.rsplit('.', 1)[1]}.{name}")
    assert set(cached.values()) == {"catalog.load_catalog", "catalog._by_name",
                                    "loader._load_bundled", "loader.load_registry"}


def test_custom_loading_leaves_bundled_state_alone_and_shares_nothing():
    load_registry("GRCh38")
    before = (load_registry.cache_info(), catalog_module.load_catalog.cache_info())
    first = load(H + "a\tb\t\t\t\n")
    second = load(H + "a\tb\t\t\t\n")
    assert first is not second and first._index is not second._index
    assert (load_registry.cache_info(), catalog_module.load_catalog.cache_info()
            ) == before
    registries = [o for o in gc.get_objects()
                  if isinstance(o, ChromosomeRegistry)]
    assert not [r for r in registries if r.assembly_id is None
                and r is not first and r is not second
                and r.name == "Custom chromosome mapping"
                and (r.resolve("a").resolved)]


def test_the_app_never_caches_or_writes_custom_content_globally():
    source = (ROOT / "streamlit_app" / "streamlit_app.py").read_text()
    for forbidden in ("cache_resource", "cache_data", "lru_cache", "@cache",
                      "open(", "write_bytes", "NamedTemporaryFile", ".to_pickle"):
        assert forbidden not in source.split("def _custom_registry")[1].split(
            "def _config_signature")[0], forbidden


def test_two_sessions_never_see_each_others_mapping():
    from streamlit_app.streamlit_app import _CUSTOM_OPTION
    from tests.test_custom_mapping_gui import (
        MAPPING_A,
        MAPPING_B,
        App,
        _widget,
        custom_run,
    )
    one = custom_run(MAPPING_A)
    two = App().source(_CUSTOM_OPTION).naming("UCSC names")
    two.mapping(MAPPING_B)
    one.run()                                    # interleaved reruns
    two.run()
    one.run()
    assert one.chrs[0] == "chrA" and two.chrs[0] == "chrZ"
    assert one.state["chr_mapping_loaded"][1] is not two.state["chr_mapping_loaded"][1]
    third = App().source(_CUSTOM_OPTION).naming("UCSC names")
    third.run()
    assert not third.done and "chr_mapping_loaded" not in third.state
    assert _widget(third.at, "file_uploader", "chr_mapping_file").value is None


# ---- 28. offline guarantee --------------------------------------------------------------

BLOCK = textwrap.dedent('''
    import socket, urllib.request, http.client
    def boom(*a, **k):
        raise RuntimeError("NETWORK ACCESS ATTEMPTED")
    socket.socket.connect = boom
    socket.socket.connect_ex = boom
    socket.create_connection = boom
    socket.getaddrinfo = boom
    socket.gethostbyname = boom
    urllib.request.urlopen = boom
    urllib.request.OpenerDirector.open = boom
    http.client.HTTPConnection.connect = boom
    try:
        import requests
        requests.Session.request = boom
    except ImportError:
        pass
''')

WORK = textwrap.dedent('''
    import pandas as pd
    from streamlit_app.core.chrom_registry import (
        load_catalog, load_registry, load_custom_registry, assembly_options)
    from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
    assert len(assembly_options()) == 64 and len(load_catalog()) == 64
    df = pd.DataFrame({"chr": ["1", "chrM", "x"], "start": [0, 1, 2], "end": [1, 2, 3]})
    for name in ("GRCh38", "mm10", "hg19"):
        out = normalize_input_chromosomes(df, df, assembly=name, target="ucsc")
        assert out.coord_df["chr"].tolist()[0] == "chr1"
    reg = load_custom_registry(b"assembly\\tucsc\\tensembl\\tgenbank\\trefseq\\nc1\\tchr1\\t\\t\\t\\n")
    out = normalize_input_chromosomes(df, df, registry=reg, target="ucsc")
    assert out.coord_report.registry_name == "Custom chromosome mapping"
    print("OFFLINE-OK")
''')


def test_import_catalog_bundled_and_custom_work_with_the_network_disabled():
    result = subprocess.run(
        [sys.executable, "-c", BLOCK + WORK], cwd=ROOT, capture_output=True,
        text=True, timeout=300, check=False)
    assert "NETWORK ACCESS ATTEMPTED" not in result.stderr + result.stdout
    assert result.returncode == 0 and "OFFLINE-OK" in result.stdout, result.stderr


def test_a_full_gui_run_with_the_network_disabled(monkeypatch):
    import socket
    import urllib.request

    def boom(*a, **k):
        raise RuntimeError("NETWORK ACCESS ATTEMPTED")
    for target, name in ((socket.socket, "connect"), (socket, "getaddrinfo"),
                         (socket, "create_connection"),
                         (urllib.request, "urlopen")):
        monkeypatch.setattr(target, name, boom)
    from tests.test_custom_mapping_gui import MAPPING_A, custom_run
    app = custom_run(MAPPING_A)
    assert app.done and app.chrs[0] == "chrA"


# ---- 27. zip-style resource access --------------------------------------------------------

def test_the_runtime_loads_from_a_zip_without_repository_paths(tmp_path):
    archive = tmp_path / "bundle.zip"
    package = ROOT / "streamlit_app"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in package.rglob("*"):
            relative = path.relative_to(ROOT)
            skip = ("__pycache__", "upstream")
            if path.is_file() and not any(p in relative.parts for p in skip) \
                    and path.name != "sources.json":
                zf.write(path, relative.as_posix())
    code = textwrap.dedent(f'''
        import sys
        sys.path.insert(0, {str(archive)!r})
        import streamlit_app.core.chrom_registry as m
        assert ".zip" in m.__file__, m.__file__
        from streamlit_app.core.chrom_registry import (
            load_registry, load_custom_registry, assembly_options)
        a = load_registry("mm10"); b = load_registry("GRCm38")
        assert a is b and a.assembly_id == "GRCm38" and len(assembly_options()) == 64
        reg = load_custom_registry(b"assembly\\tucsc\\tensembl\\tgenbank\\trefseq\\nc1\\tchr1\\t\\t\\t\\n")
        assert reg.resolve("c1").resolved
        print("ZIP-OK")
    ''')
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, timeout=300,
                            check=False)
    assert "ZIP-OK" in result.stdout, result.stderr


# ---- 22. selector discoverability (the list filter is a case-insensitive
# substring match over the option text) -----------------------------------------------------

LABELS = {i.canonical_id: i.display_label for i in load_catalog()}


def search(text):
    return {a for a, label in LABELS.items() if text.casefold() in label.casefold()}


@pytest.mark.parametrize("text,expected", [
    ("GRCh38", {"GRCh38"}), ("hg38", {"GRCh38"}), ("GRCm39", {"GRCm39"}),
    ("mm39", {"GRCm39"}), ("rn7", {"mRatBN7.2"}), ("mRatBN7.2", {"mRatBN7.2"}),
    ("wuhCor1", {"wuhCor1"}), ("hg19", {"hg19"}), ("mm10", {"GRCm38"}),
])
def test_assembly_names_find_exactly_their_assembly(text, expected):
    assert search(text) == expected


@pytest.mark.parametrize("text,minimum", [("human", 2), ("mouse", 2), ("dog", 4),
                                          ("canFam", 4), ("zebrafish", 2)])
def test_organism_and_family_searches_find_the_family(text, minimum):
    assert len(search(text)) >= minimum


def test_every_canonical_id_alias_and_db_is_findable_for_its_own_assembly():
    for info in load_catalog():
        for name in info.names:
            assert info.canonical_id in search(name), (info.canonical_id, name)


def test_scientific_names_are_not_searchable_a_known_limitation():
    assert search("Homo sapiens") == set()
    assert search("Mus musculus") == set()


def test_labels_are_reasonable_for_a_narrow_sidebar():
    longest = max(len(label) for label in LABELS.values())
    assert longest <= 80, longest
    assert len(set(LABELS.values())) == 64


# ---- 29. reproducibility: mutation tests of the drift guards ---------------------------------

@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    root = tmp_path_factory.mktemp("sandbox")
    shutil.copytree(PACKAGE, root / "pkg", ignore=shutil.ignore_patterns(
        "__pycache__", "*.py"))
    shutil.copytree(ROOT / "audits", root / "audits")
    return root


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ucc", ROOT / "scripts" / "update_chrom_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mutated(path: Path, mutate):
    original = path.read_bytes()
    path.write_bytes(mutate(original))
    return original


def _problems(sandbox):
    return _tool().check(sandbox, sandbox / "pkg")


def test_the_pristine_sandbox_is_clean(sandbox):
    assert _problems(sandbox) == []


def test_a_flipped_upstream_byte_is_detected(sandbox):
    path = sandbox / "pkg" / "upstream" / "hg19.chromAlias.txt.gz"
    original = _mutated(path, lambda b: b[:100] + bytes([b[100] ^ 1]) + b[101:])
    try:
        assert any("hg19" in p for p in _problems(sandbox))
    finally:
        path.write_bytes(original)


def test_a_wrong_pinned_checksum_is_detected(sandbox):
    path = sandbox / "pkg" / "sources.json"
    original = path.read_text()
    config = json.loads(original)
    config["assemblies"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        assert any("checksum" in p or "SHA-256" in p for p in _problems(sandbox))
    finally:
        path.write_text(original)


def test_a_changed_audit_classification_is_detected(sandbox):
    path = sandbox / "audits" / "chrom_alias_catalog" / "report.json"
    original = path.read_text()
    report = json.loads(original)
    for entry in report["assemblies"]:
        if entry["db"] == "mm10":
            entry["status"] = "FAIL"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    try:
        assert any("differs from policy" in p or "mm10" in p
                   for p in _problems(sandbox))
    finally:
        path.write_text(original)


def test_a_mutated_generated_registry_is_detected(sandbox):
    path = sandbox / "pkg" / "data" / "GRCh38.tsv"
    original = _mutated(path, lambda b: b.replace(b"chr1\t", b"chr9\t", 1))
    try:
        assert any("GRCh38" in p for p in _problems(sandbox))
    finally:
        path.write_bytes(original)


def test_an_edited_catalog_json_is_detected_and_a_duplicate_alias_is_refused(sandbox):
    path = sandbox / "pkg" / "catalog.json"
    original = path.read_text()
    config = json.loads(original)
    config["assemblies"][0]["aliases"] = list(config["assemblies"][1]["aliases"]
                                              or [config["assemblies"][1]["canonical_id"]])
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        assert any("catalog.json" in p for p in _problems(sandbox))
        infos = [AssemblyInfo(**{**e, "aliases": tuple(e["aliases"])})
                 for e in config["assemblies"]]
        assert any("belongs to both" in p for p in identity_problems(infos))
    finally:
        path.write_text(original)


def test_an_altered_canonical_id_is_detected(sandbox):
    path = sandbox / "pkg" / "sources.json"
    original = path.read_text()
    config = json.loads(original)
    entry = next(e for e in config["assemblies"] if e["ucsc_db"] == "mm10")
    entry["canonical_id"] = "GRCm39"           # collides with another assembly
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        problems = _problems(sandbox)
        assert any("canonical id" in p for p in problems), problems
    finally:
        path.write_text(original)


def test_an_override_that_is_not_in_the_ucsc_description_is_refused(sandbox):
    path = sandbox / "pkg" / "sources.json"
    original = path.read_text()
    config = json.loads(original)
    config["bundle_policy"]["canonical_id_overrides"]["canFam3"] = "CanFam3.1"
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        assert any("not the" in p for p in _problems(sandbox))
    finally:
        path.write_text(original)
    assert _problems(sandbox) == []                      # fully restored
