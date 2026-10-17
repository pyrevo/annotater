"""Task 14.4 — shared, framework-independent, lossless annotated VCF export.

Guards the contract that the Streamlit and FastAPI frontends share one VCF
writer (``streamlit_app.core.vcf_export.build_annotated_vcf``) and that the
previously divergent FastAPI exporter no longer silently discards FORMAT /
sample genotype data.

Expected VCF content is hand-computed from the fixtures below (independent of
the exporter under test) and cross-checked with pysam where available.
"""

from __future__ import annotations

import re
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.config import Settings
from streamlit_app.core.engine_registry import build_engine, engine_available
from streamlit_app.core.normalization import normalize_intervals
from streamlit_app.core.parsers import GFFParser, VCFParser
from streamlit_app.core.schema import canonicalize_annotation_result
from streamlit_app.core.vcf_export import (
    UnrecoverableVCFError,
    VCFExportError,
    VCFInfoDeclarationConflict,
    build_annotated_vcf,
    deterministic_date_stamp,
)
from streamlit_app.streamlit_app import convert_df_to_vcf
from tests.test_custom_mapping_gui import App, _has

ROOT_DATE = "20200101"


# ---------------------------------------------------------------------------
# Fixtures (tiny, hand-auditable; independent of the exporter)
# ---------------------------------------------------------------------------

QUERY_VCF = (
    b"##fileformat=VCFv4.2\n"
    b"##contig=<ID=chr1>\n"
    b'##INFO=<ID=DP,Number=.,Type=Integer,Description="read depth">\n'
    b'##INFO=<ID=END,Number=1,Type=Integer,Description="end position">\n'
    b'##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">\n'
    b'##FORMAT=<ID=AD,Number=R,Type=Integer,Description="allelic depths">\n'
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
    # Matched by geneA; carries ID, QUAL, FILTER, INFO(DP), FORMAT GT:AD.
    b"chr1\t100\tsnv1\tA\tT\t50\tPASS\tDP=10\tGT:AD\t0/1:8,2\n"
    # Unmatched; symbolic variant with END; QUAL/FILTER missing.
    b"chr1\t300\t.\tC\t<DEL>\t.\t.\tEND=400\tGT:AD\t./.:.\n"
)

ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tens\tgene\t1\t120\t.\t+\t.\tID=geneA;Name=geneA\n"
    b"chr1\tens\tgene\t900\t950\t.\t+\t.\tID=geneC;Name=geneC\n"
)

# geneA contributes exactly these ANNOT_* tokens (score/frame/gene_*/Parent are
# missing for this fixture and are therefore omitted from the INFO field).
_GENE_A_ANNOT_INFO = (
    "ANNOT_strand=+;ANNOT_source=ens;ANNOT_feature=gene;"
    "ANNOT_attributes=ID:geneA|Name:geneA;ANNOT_ID=geneA;ANNOT_Name=geneA"
)

EXPECTED_RECORDS = [
    ["chr1", "100", "snv1", "A", "T", "50", "PASS",
     f"DP=10;{_GENE_A_ANNOT_INFO}", "GT:AD", "0/1:8,2"],
    ["chr1", "300", ".", "C", "<DEL>", ".", ".",
     "END=400", "GT:AD", "./.:."],
]


def _write(tmp_path, name, data) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _build_result(tmp_path, query=QUERY_VCF, annot=ANNOT_GFF, engine="bedtools"):
    """Full real core path: parse -> normalize -> engine -> canonicalize."""
    qp = _write(tmp_path, "query.vcf", query)
    ap = _write(tmp_path, "annot.gff", annot)
    parsed = VCFParser.parse(qp)
    header = parsed.attrs.get("vcf_header_lines")
    coord_df = normalize_intervals(parsed, coordinate_system="1-based")
    annot_df = normalize_intervals(GFFParser.parse(ap), coordinate_system="1-based")
    raw = build_engine(engine, mode="overlap").intersect(coord_df, annot_df, how="left")
    result = canonicalize_annotation_result(raw, coord_df, annot_df)
    return result, header


def _records(vcf_text: str):
    return [
        line.split("\t")
        for line in vcf_text.splitlines()
        if line and not line.startswith("#")
    ]


def _header_lines(vcf_text: str):
    return [line for line in vcf_text.splitlines() if line.startswith("##")]


def _minimal_df(annot_value="g1"):
    return pd.DataFrame({
        "coord_chr": ["chr1", "chr2"],
        "coord_start": [99, 299],
        "coord_end": [100, 300],
        "coord_id": ["v1", "v2"],
        "coord_ref": ["A", "C"],
        "coord_alt": ["T", "G"],
        "coord_qual": [50.0, pd.NA],
        "coord_filter": ["PASS", pd.NA],
        "coord_info": ["DP=10", ""],
        "annot_gene": [annot_value, pd.NA],
    })


# ---------------------------------------------------------------------------
# Core contract (item 1, 2, 3, 8, 9, 10, 11)
# ---------------------------------------------------------------------------

class TestCoreExportContract:
    def test_full_export_matches_hand_computed_records(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        assert _records(out) == EXPECTED_RECORDS

    def test_chrom_header_preserves_format_and_sample(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        chrom = next(l for l in out.splitlines() if l.startswith("#CHROM"))
        assert chrom == "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1"

    def test_pos_is_start_plus_one(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        pos = [r[1] for r in _records(out)]
        assert pos == ["100", "300"]  # coord_start 99/299 -> POS 100/300

    def test_every_emitted_annot_key_is_declared(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        declared = set(re.findall(r"##INFO=<ID=([A-Za-z0-9_]+),", out))
        for record in _records(out):
            info = record[7]
            if info == ".":
                continue
            for token in info.split(";"):
                key = token.split("=")[0]
                if key.startswith("ANNOT_"):
                    assert key in declared, key

    def test_original_info_survives_verbatim(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        # The unmatched record keeps END=400 exactly, nothing reordered/renamed.
        assert _records(out)[1][7] == "END=400"

    def test_missing_annotation_value_omits_field(self):
        out = build_annotated_vcf(_minimal_df(), None, None, date_stamp=ROOT_DATE)
        recs = _records(out)
        assert "ANNOT_gene=g1" in recs[0][7]
        assert "ANNOT_gene" not in recs[1][7]
        assert recs[1][7] == "."  # no leading empty / no ANNOT_gene=.

    def test_missing_values_render_as_vcf_missing(self):
        out = build_annotated_vcf(_minimal_df(), None, None, date_stamp=ROOT_DATE)
        recs = _records(out)
        assert recs[0][5] == "50"          # integer-valued QUAL round-trips
        assert recs[1][5] == "."           # missing QUAL -> "."
        assert recs[1][6] == "."           # missing FILTER -> "."
        assert "<NA>" not in out and "nan" not in out

    def test_header_preserved_single_fileformat_and_provenance(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        lines = out.splitlines()
        assert len([l for l in lines if l.startswith("##fileformat")]) == 1
        assert any(l.startswith("##INFO=<ID=DP,") for l in lines)
        assert any(l.startswith("##FORMAT=<ID=GT,") for l in lines)
        assert any(l.startswith("##FORMAT=<ID=AD,") for l in lines)
        assert "##contig=<ID=chr1>" in lines
        assert f"##source=AnnotateR {Settings.VERSION}" in lines
        assert f"##date={ROOT_DATE}" in lines

    def test_missing_header_synthesizes_valid_fileformat(self):
        out = build_annotated_vcf(_minimal_df(), None, None, date_stamp=ROOT_DATE)
        lines = out.splitlines()
        assert lines[0] == "##fileformat=VCFv4.2"
        assert len([l for l in lines if l.startswith("##fileformat")]) == 1

    def test_export_is_valid_vcf_per_pysam(self, tmp_path):
        _require_bedtools()
        pysam = pytest.importorskip("pysam")
        VariantFile = getattr(pysam, "VariantFile", None)
        if VariantFile is None:
            pytest.skip("pysam.VariantFile unavailable in this build")
        result, header = _build_result(tmp_path)
        out = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        path = tmp_path / "out.vcf"
        path.write_text(out + "\n", "utf-8")
        vf = VariantFile(str(path))
        try:
            recs = list(vf)
        finally:
            vf.close()
        assert len(recs) == 2
        assert [r.chrom for r in recs] == ["chr1", "chr1"]
        assert [int(r.pos) for r in recs] == [100, 300]
        assert recs[0].ref == "A" and tuple(recs[0].alts) == ("T",)
        assert recs[0].qual == 50
        assert recs[0].samples["S1"]["GT"] in ("0/1", (0, 1))
        assert "ANNOT_ID" in recs[0].info
        assert "DP" in recs[0].info


# ---------------------------------------------------------------------------
# ANNOT_* collision policy (item 4)
# ---------------------------------------------------------------------------

class TestAnnotCollisionPolicy:
    def test_original_annot_string_declaration_is_not_overwritten(self):
        header = [
            "##fileformat=VCFv4.2",
            '##INFO=<ID=ANNOT_gene,Number=1,Type=String,Description="original">',
        ]
        out = build_annotated_vcf(_minimal_df(), header, None, date_stamp=ROOT_DATE)
        decls = [l for l in out.splitlines() if l.startswith("##INFO=<ID=ANNOT_gene")]
        assert len(decls) == 1
        assert 'Description="original"' in decls[0]
        assert "ANNOT_gene=g1" in _records(out)[0][7]

    def test_non_string_original_annot_declaration_is_typed_error(self):
        header = [
            "##fileformat=VCFv4.2",
            '##INFO=<ID=ANNOT_gene,Number=1,Type=Integer,Description="bad">',
        ]
        with pytest.raises(VCFInfoDeclarationConflict, match="ANNOT_gene"):
            build_annotated_vcf(_minimal_df(), header, None, date_stamp=ROOT_DATE)

    def test_export_error_is_a_value_error(self):
        # The Streamlit/Streamlit-era tests rely on ValueError semantics.
        assert issubclass(VCFExportError, ValueError)
        assert issubclass(UnrecoverableVCFError, VCFExportError)
        assert issubclass(VCFInfoDeclarationConflict, VCFExportError)


# ---------------------------------------------------------------------------
# Failure contract (item 10)
# ---------------------------------------------------------------------------

class TestFailureContract:
    def test_no_coordinate_columns_raises_typed_error(self):
        df = pd.DataFrame({"foo": [1, 2]})
        with pytest.raises(UnrecoverableVCFError):
            build_annotated_vcf(df)
        # It is a ValueError, and it is never a successful-looking VCF string.

    def test_malformed_export_error_is_bounded(self, monkeypatch):
        """The API returns a bounded 422 and never leaks private paths."""
        monkeypatch.setattr(api_server, "store", SessionStore())
        client = TestClient(app)
        session = api_server.store.create()
        session.data["result"] = {
            "df": pd.DataFrame({"foo": [1, 2]}),
            "coord_format": "vcf",
            "vcf_header_lines": None,
            "vcf_contig_renames": {},
        }
        client.cookies.set(SESSION_COOKIE_NAME, session.token)
        response = client.get("/api/export/vcf")
        assert response.status_code == 422
        body = response.text
        assert "/tmp/" not in body
        assert "annotater-upload" not in body


# ---------------------------------------------------------------------------
# Determinism (item 13)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_explicit_date_stamp_honored(self):
        out = build_annotated_vcf(_minimal_df(), None, None, date_stamp="20210303")
        assert "##date=20210303" in out.splitlines()

    def test_source_date_epoch_env_honored(self, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
        assert deterministic_date_stamp() == "19700101"
        out = build_annotated_vcf(_minimal_df(), None, None)
        assert "##date=19700101" in out.splitlines()

    def test_without_env_still_produces_valid_date(self, monkeypatch):
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        out = build_annotated_vcf(_minimal_df(), None, None)
        assert re.search(r"^##date=\d{8}$", out, re.M)

    def test_repeated_export_is_byte_identical(self, tmp_path):
        _require_bedtools()
        result, header = _build_result(tmp_path)
        a = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        b = build_annotated_vcf(result, header, None, date_stamp=ROOT_DATE)
        assert a == b


# ---------------------------------------------------------------------------
# Frontend equivalence + no dropped samples (items 7, 14)
# ---------------------------------------------------------------------------

class TestFrontendEquivalence:
    def test_streamlit_wrapper_matches_core(self, tmp_path, monkeypatch):
        """The Streamlit wrapper and the core writer are the same code path:
        with a fixed date (via SOURCE_DATE_EPOCH) and identical inputs they
        produce byte-identical output."""
        _require_bedtools()
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
        result, header = _build_result(tmp_path)
        core = build_annotated_vcf(result, header, None)
        streamlit = convert_df_to_vcf(result, header, None)
        assert streamlit == core

    def test_api_export_matches_core_and_keeps_samples(self, tmp_path, monkeypatch):
        """End-to-end: the FastAPI VCF export is byte-identical to the core
        writer and no longer discards FORMAT / sample genotype data."""
        _require_bedtools()
        monkeypatch.setattr(api_server, "store", SessionStore())
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")

        client = TestClient(app)
        _upload(client, "query.vcf", QUERY_VCF, "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        run = client.post("/api/execute", json=_REQUEST)
        assert run.status_code == 200, run.text

        session = next(iter(api_server.store._sessions.values()))
        res = session.data["result"]
        core = build_annotated_vcf(
            res["df"],
            res.get("vcf_header_lines"),
            res.get("vcf_contig_renames"),
        )

        response = client.get("/api/export/vcf")
        assert response.status_code == 200, response.text
        api_text = response.text

        # Byte-identical to the shared core writer.
        assert api_text == core
        # The historical FastAPI bug: FORMAT + sample genotype must survive.
        chrom = next(l for l in api_text.splitlines() if l.startswith("#CHROM"))
        assert chrom.endswith("\tFORMAT\tS1")
        assert "0/1:8,2" in api_text
        assert "./.:." in api_text
        # Filename is server-fixed, never derived from user input.
        disposition = response.headers["content-disposition"]
        assert "filename=annotated_variants.vcf" in disposition


# ---------------------------------------------------------------------------
# Streamlit error UI for typed export failures (item 10)
# ---------------------------------------------------------------------------

#: A VCF query whose header declares ANNOT_source with a non-String type.
#: Combined with an annotation carrying a ``source`` column, the export must
#: fail with a labeled error instead of offering an error-artifact download.
_UI_CONFLICT_VCF = (
    b"##fileformat=VCFv4.2\n"
    b'##INFO=<ID=ANNOT_source,Number=1,Type=Integer,Description="conflict">\n'
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    b"chr1\t100\tv1\tA\tT\t50\tPASS\t.\n"
)
_UI_ANNOT = b"##gff-version 3\nchr1\tsrc\tgene\t50\t250\t.\t+\t.\tID=g1;Name=G1\n"


class TestStreamlitExportErrorUI:
    def test_annot_type_conflict_is_labeled_error_without_a_download(self):
        app = App(_UI_CONFLICT_VCF, _UI_ANNOT, qname="q.vcf").run()
        assert not app.at.exception
        assert any(
            "Annotated VCF export is unavailable" in e for e in app.errors
        )
        assert any("ANNOT_source" in e for e in app.errors)
        assert not _has(app.at, "download_button", "download_vcf")


# ---------------------------------------------------------------------------
# Session isolation for VCF export (items 12, 14)
# ---------------------------------------------------------------------------

VCF_A = (
    b"##fileformat=VCFv4.2\n"
    b"##contig=<ID=chr1>\n"
    b'##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">\n'
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
    b"chr1\t100\tsnvA\tA\tT\t50\tPASS\t.\tGT\t0/1\n"
)
VCF_B = (
    b"##fileformat=VCFv4.2\n"
    b"##contig=<ID=chr2>\n"
    b'##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">\n'
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS2\n"
    b"chr2\t50\tsnvB\tC\tG\t40\tPASS\t.\tGT\t1/1\n"
)
GFF_A = b"##gff-version 3\nchr1\tens\tgene\t1\t200\t.\t+\t.\tID=genA;Name=genA\n"
GFF_B = b"##gff-version 3\nchr2\tens\tgene\t1\t200\t.\t+\t.\tID=genB;Name=genB\n"


class TestSessionIsolation:
    def test_no_shared_state_between_exports(self, tmp_path):
        # Two different frames, exported back to back: no bleed-over.
        df_a = _minimal_df(annot_value="alpha")
        df_b = _minimal_df(annot_value="beta")
        out_a = build_annotated_vcf(df_a, None, None, date_stamp=ROOT_DATE)
        out_b = build_annotated_vcf(df_b, None, None, date_stamp=ROOT_DATE)
        assert "ANNOT_gene=alpha" in out_a and "ANNOT_gene=beta" not in out_a
        assert "ANNOT_gene=beta" in out_b and "ANNOT_gene=alpha" not in out_b

    def test_session_isolation_for_vcf_export(self):
        _require_bedtools()
        a = TestClient(app)
        b = TestClient(app)
        for client, qv, gv, qname, aname in (
            (a, VCF_A, GFF_A, "a.vcf", "a.gff"),
            (b, VCF_B, GFF_B, "b.vcf", "b.gff"),
        ):
            _upload(client, qname, qv, "query")
            _upload(client, aname, gv, "annot")
            assert client.post("/api/execute", json=_REQUEST).status_code == 200

        va = a.get("/api/export/vcf").text
        vb = b.get("/api/export/vcf").text
        assert "snvA" in va and "snvA" not in vb
        assert "snvB" in vb and "snvB" not in va
        # A third, empty session never sees either.
        c = TestClient(app)
        assert c.get("/api/export/vcf").status_code == 404


# ---------------------------------------------------------------------------
# Performance (item 15)
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_fifty_k_rows_within_limit(self):
        n = 50_000
        df = pd.DataFrame({
            "coord_chr": ["chr1"] * n,
            "coord_start": list(range(n)),
            "coord_end": [s + 1 for s in range(n)],
            "coord_id": [f"v{i}" for i in range(n)],
            "coord_ref": ["A"] * n,
            "coord_alt": ["T"] * n,
            "coord_qual": [50.0] * n,
            "coord_filter": ["PASS"] * n,
            "coord_info": ["DP=10"] * n,
            "annot_gene": [f"g{i}" for i in range(n)],
        })
        started = time.monotonic()
        out = build_annotated_vcf(df, None, None, date_stamp=ROOT_DATE)
        elapsed = time.monotonic() - started
        assert len(_records(out)) == n
        assert elapsed < 60  # generous; the point is "no pathological timeout"


# ---------------------------------------------------------------------------
# Helpers for the HTTP tests
# ---------------------------------------------------------------------------

def _require_bedtools():
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")


_REQUEST = {
    "engine": "bedtools",
    "mode": "overlap",
    "join": "left",
    "feature_types": ["gene"],
    "use_strand": False,
    "min_overlap": 0.0,
    "assembly": None,
    "chr_naming": None,
}


def _upload(client, name, content, role, media="text/plain"):
    response = client.post(
        "/api/upload", files={"file": (name, content, media)}, data={"role": role}
    )
    assert response.status_code == 200, response.text
    return response


# ---------------------------------------------------------------------------
# Task 14.7a (review finding F2): VCF export is VCF-query-only
# ---------------------------------------------------------------------------

class TestVcfExportGating:
    """The HTTP boundary enforces the Streamlit rule ``coord_format == 'vcf'``.

    The exporter fabricates records from canonical intervals, so a BED/GFF/CSV
    query would produce REF/ALT placeholders. The gate is server-side and does
    not depend on the frontend hiding the control.
    """

    def _fresh(self, monkeypatch):
        monkeypatch.setattr(api_server, "store", SessionStore())

    def test_vcf_query_still_exports(self, monkeypatch):
        _require_bedtools()
        self._fresh(monkeypatch)
        client = TestClient(app)
        _upload(client, "query.vcf", QUERY_VCF, "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        assert client.post("/api/execute", json=_REQUEST).status_code == 200
        assert client.get("/api/export/vcf").status_code == 200

    def test_bed_query_vcf_export_is_rejected(self, monkeypatch):
        _require_bedtools()
        self._fresh(monkeypatch)
        client = TestClient(app)
        _upload(client, "q.bed", b"chr1\t0\t200\tq1\n", "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        assert client.post("/api/execute", json=_REQUEST).status_code == 200

        response = client.get("/api/export/vcf")
        assert response.status_code == 400, response.text
        assert "VCF export is only available" in response.json()["detail"]

    def test_other_formats_still_available_for_non_vcf_query(self, monkeypatch):
        _require_bedtools()
        self._fresh(monkeypatch)
        client = TestClient(app)
        _upload(client, "q.bed", b"chr1\t0\t200\tq1\n", "query")
        _upload(client, "annot.gff", ANNOT_GFF, "annot")
        assert client.post("/api/execute", json=_REQUEST).status_code == 200
        for fmt in ("csv", "tsv", "xlsx"):
            assert client.get(f"/api/export/{fmt}").status_code == 200
