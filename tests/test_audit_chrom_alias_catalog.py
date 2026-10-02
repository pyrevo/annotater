"""Audit tooling for the UCSC chromAlias catalog (offline).

Synthetic tables plus the six pinned production upstream files; the network
is never used (fetchers are injected). The committed audit snapshot is
checked for internal consistency only.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "audit_chrom_alias_catalog", ROOT / "scripts" / "audit_chrom_alias_catalog.py")
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

UPSTREAM = ROOT / "streamlit_app" / "core" / "chrom_registry" / "upstream"
SNAPSHOT = ROOT / "audits" / "chrom_alias_catalog" / "report.json"


def gz(*lines: str) -> bytes:
    return gzip.compress(("\n".join(lines) + "\n").encode())


def run(*lines: str, db: str = "tstDb1") -> dict:
    meta = {"db": db, "organism": None, "common_name": None,
            "scientific_name": None, "tax_id": None, "assembly_name": None,
            "source_name": None}
    return audit.audit_source(meta, gz(*lines), 200)


CLEAN = ("1\tchr1\tassembly,ensembl", "CM000001.1\tchr1\tgenbank",
         "NC_000001.1\tchr1\trefseq", "X\tchrX\tensembl")


# ---- catalog ----------------------------------------------------------------

def _catalog(**entries):
    return json.dumps({"dataTime": "2026-01-01T00:00:00",
                       "downloadTime": "2026:02:03T04:05:06Z",
                       "ucscGenomes": entries}).encode()


def test_catalog_candidates_are_filtered_explicitly_and_labels_are_verbatim():
    data = _catalog(
        zzz9={"active": 1, "organism": "Zed", "genome": "Zed",
              "scientificName": "Zed zed", "taxId": 5,
              "description": "Jan. 2020 (Z/zzz9)", "sourceName": "Lab"},
        old1={"active": 0, "organism": "Old"},
        **{"bad/id": {"active": 1}},
        aaa1={"active": 1, "organism": "Ay"},
    )
    meta, candidates, excluded = audit.parse_catalog(data)
    assert [c["db"] for c in candidates] == ["aaa1", "zzz9"]   # sorted
    assert sorted(excluded, key=lambda e: e["db"]) == [
        {"db": "bad/id", "reason": "invalid database id"},
        {"db": "old1", "reason": "not active"}]
    zed = candidates[1]
    assert zed["organism"] == "Zed" and zed["scientific_name"] == "Zed zed"
    assert zed["assembly_name"] == "Jan. 2020 (Z/zzz9)" and zed["tax_id"] == 5
    # missing metadata stays null; nothing is derived from the database id
    assert candidates[0]["scientific_name"] is None
    assert candidates[0]["assembly_name"] is None
    assert meta["catalog_entries"] == 4


# ---- row parsing ------------------------------------------------------------

@pytest.mark.parametrize("line,reason", [
    ("a\tb", "2 fields"), ("a\tb\tc\td", "4 fields"),
    ("\tchr1\tensembl", "empty field"), ("a\tchr1\t", "empty field"),
    (" a\tchr1\tensembl", "surrounding whitespace"),
    ("a\tchr1\tensembl\r", "surrounding whitespace"),
])
def test_malformed_rows_are_reported_and_not_repaired(line, reason):
    rows, malformed = audit.parse_rows(gz("1\tchr1\tassembly", line))
    assert rows == [("1", "chr1", "assembly")]
    assert malformed == [(2, reason)]


def test_unreadable_and_empty_tables_are_malformed():
    assert audit.parse_rows(b"not gzip")[1][0][1].startswith("unreadable")
    assert audit.parse_rows(gzip.compress(b""))[1] == [(0, "no rows")]


# ---- classification ---------------------------------------------------------

def test_clean_table_with_partial_authorities_passes():
    r = run(*CLEAN)
    assert r["status"] == "PASS" and r["reason_codes"] == ["PASS"]
    assert r["wide_schema_lossless"] and r["builder_ok"] and r["oracle_ok"]
    assert r["loader_ok"] and r["estimated_tsv_exact"]
    assert r["sequence_records"] == 2 and r["alias_rows"] == 4
    assert r["authority_counts"]["genbank"] == 1
    assert r["authority_missing"] == {"ucsc": 0, "assembly": 1, "ensembl": 0,
                                      "genbank": 1, "refseq": 1}
    assert r["source_label_sets"]["assembly,ensembl"] == 1


def test_no_ensembl_or_assembly_aliases_is_still_a_pass():
    r = run("CM000001.1\tchr1\tgenbank", "NC_000001.1\tchr1\trefseq")
    assert r["status"] == "PASS"
    assert r["authorities_present"] == ["ucsc", "genbank", "refseq"]


def test_insdc_shaped_ensembl_names_are_counted_but_never_relabelled():
    """Ensembl names that are INSDC accessions stay ensembl-only (no genbank
    alias is inferred from syntax); the audit just measures the gap."""
    r = run("AEYP01107703.1\tscaf1\tensembl", "CM000001.1\tchr1\tgenbank")
    assert r["status"] == "PASS"
    assert r["insdc_shaped_without_genbank_label"] == 1
    assert r["authority_counts"]["genbank"] == 1


def test_missing_source_is_not_a_model_failure():
    meta = {"db": "gone1"}
    r = audit.audit_source(meta, None, 404)
    assert (r["status"], r["reason_codes"]) == ("NO_SOURCE", ["NO_CHROM_ALIAS"])
    assert r["alias_rows"] is None and r["wide_schema_lossless"] is None
    r = audit.audit_source(meta, None, None, error="timeout")
    assert (r["status"], r["reason_codes"]) == ("ERROR", ["FETCH_ERROR"])


def test_several_aliases_per_sequence_and_authority_fail_and_are_kept():
    r = run("A00001.1\tscaf1\tgenbank", "A00002.1\tscaf1\tgenbank",
            "NC_000001.1\tscaf1\trefseq")
    assert r["status"] == "FAIL"
    assert r["reason_codes"] == ["MULTIPLE_ALIAS_PER_AUTHORITY"]
    assert r["wide_schema_lossless"] is False and r["builder_ok"] is False
    assert r["examples"]["multi_alias"] == [
        {"chrom": "scaf1", "authority": "genbank",
         "aliases": ["A00001.1", "A00002.1"]}]
    assert r["multi_alias_count"] == 1
    assert r["estimated_tsv_exact"] is False       # an estimate, flagged


def test_alias_naming_two_sequences_is_a_collision():
    r = run("1\tchr1\tassembly", "1\tchr2\tassembly")
    assert r["status"] == "FAIL" and "ALIAS_COLLISION" in r["reason_codes"]
    assert r["collision_count"] == 1
    assert r["examples"]["collisions"][0] == {
        "alias": "1", "kind": "several_sequences", "chroms": ["chr1", "chr2"]}
    assert r["wide_schema_lossless"] is False


def test_alias_equal_to_another_sequences_ucsc_name_is_a_collision():
    r = run("chr2\tchr1\tassembly", "2\tchr2\tassembly")
    assert r["status"] == "FAIL"
    assert r["examples"]["collisions"] == [
        {"alias": "chr2", "kind": "equals_other_ucsc_name",
         "chroms": ["chr1"]}]


def test_unsupported_and_repeated_source_labels_fail():
    r = run("1\tchr1\txenbase")
    assert r["status"] == "FAIL"
    assert r["reason_codes"] == ["UNSUPPORTED_SOURCE_LABEL"]
    assert run("1\tchr1\tensembl,ensembl")["reason_codes"] == [
        "UNSUPPORTED_SOURCE_LABEL"]


def test_malformed_rows_fail_without_hiding_the_rest():
    r = run("1\tchr1\tassembly", "broken line")
    assert r["status"] == "FAIL" and "MALFORMED_ROWS" in r["reason_codes"]
    assert r["malformed_rows"] == 1 and r["alias_rows"] == 1


@pytest.mark.parametrize("line,kind", [
    ("NC_001807.4\tchrM\tgenbank", "genbank_label_on_refseq_shape"),
    ("CM000663.1\tchr1\trefseq", "refseq_label_on_insdc_shape"),
    ("NC_000001.11\tchr1\tassembly", "refseq_shape_without_refseq_label"),
])
def test_source_label_mismatch_needs_review_and_is_not_corrected(line, kind):
    r = run(line)
    assert (r["status"], r["reason_codes"]) == ("REVIEW",
                                               ["SOURCE_LABEL_MISMATCH"])
    assert r["label_issue_count"] == 1
    assert r["examples"]["label_issues"][0]["kind"] == kind
    assert r["builder_ok"] is False        # the builder agrees; no auto-fix


@pytest.mark.parametrize("line,sig", [
    ("AC_000158.1\tchr1\trefseq", "A2_D6.D1"),         # RefSeq AC_ prefix
    ("LFLD01S000001.1\tscaf\tgenbank", "A4D2A1D6.D1"),  # WGS scaffold shape
    ("NC_016008\tchrM\tgenbank", "A2_D6"),              # unversioned
])
def test_unknown_accession_shapes_are_reported_not_accepted(line, sig):
    r = run(line)
    assert (r["status"], r["reason_codes"]) == ("REVIEW", ["ACCESSION_SHAPE"])
    assert r["examples"]["accession_issues"][0]["signature"] == sig
    assert r["accession_issue_count"] == 1 and r["builder_ok"] is False


def test_fail_takes_precedence_over_review():
    r = run("1\tchr1\txenbase", "NC_000001.1\tchr1\tgenbank")
    assert r["status"] == "FAIL"
    assert {"UNSUPPORTED_SOURCE_LABEL", "SOURCE_LABEL_MISMATCH"} <= set(
        r["reason_codes"])


def test_case_collisions_are_counted_and_stay_exact():
    same = run("Chr1\tchr1\tassembly", "CM000001.1\tchr1\tgenbank")
    assert same["status"] == "PASS" and same["case_collision_count"] == 1
    assert same["case_collision_cross_record"] == 0
    cross = run("CHR1\tchr2\tassembly", "1\tchr1\tassembly")
    assert cross["status"] == "PASS" and cross["case_collision_count"] == 1
    assert cross["case_collision_cross_record"] == 1


def test_independent_oracle_flags_a_registry_that_differs_from_the_rows():
    rows = [("1", "chr1", "assembly"), ("CM000001.1", "chr1", "genbank")]
    facts = audit.expected_cells(rows)
    text = audit.render_wide("tstDb1", facts)
    assert audit.oracle_compare(facts, text) == []
    forged = text.replace("\tCM000001.1\t", "\tCM000002.1\t")
    diff = audit.oracle_compare(facts, forged)
    assert ("chr1", "genbank", "CM000001.1") in diff
    assert ("chr1", "genbank", "CM000002.1") in diff


def test_size_accounting_equals_the_builders_output_for_passing_tables():
    r = run(*CLEAN)
    rows, _ = audit.parse_rows(gz(*CLEAN))
    built = audit.builder.build_registry(rows, "tstDb1")
    assert r["estimated_tsv_bytes"] == len(built.encode())
    assert 0 < r["estimated_tsv_gzip_bytes"] < r["estimated_tsv_bytes"] + 50


def test_mitochondrial_records_and_name_shapes_are_descriptive_only():
    r = run("chrM\tchrM\tensembl", "MT\tchrMT\tassembly",
            "2L\tchr2L\tensembl", "1\tchrI\tensembl")
    assert r["status"] == "PASS"
    assert r["mito"]["records"] == ["chrM", "chrMT"] and r["mito"]["multiple"]
    assert r["name_shapes"] == {"chr_letter": 1, "chr_other": 2,
                                "chr_roman": 1}


def test_accession_signature():
    assert audit.signature("CM000663.2") == "A2D6.D1"
    assert audit.signature("NC_001807.4") == "A2_D6.D1"


# ---- pinned production upstream files: current six assemblies ----------------

def _production(db: str, filename: str) -> dict:
    meta = {"db": db}
    return audit.audit_source(meta, (UPSTREAM / filename).read_bytes(), 200)


@pytest.mark.parametrize("db,filename", [
    ("hg38", "hg38.chromAlias.txt.gz"), ("mm39", "mm39.chromAlias.txt.gz"),
    ("dm6", "dm6.chromAlias.txt.gz"), ("danRer11", "danRer11.chromAlias.txt.gz"),
    ("rn7", "rn7.chromAlias.txt.gz"),
])
def test_current_assemblies_without_corrections_pass(db, filename):
    r = _production(db, filename)
    assert r["status"] == "PASS", r["reason_codes"]
    assert r["wide_schema_lossless"] and r["oracle_ok"] and r["loader_ok"]
    assert r["production_assembly"] == audit.PRODUCTION[db]


def test_hg19_needs_review_exactly_for_its_one_reviewed_correction():
    r = _production("hg19", "hg19.chromAlias.txt.gz")
    assert (r["status"], r["reason_codes"]) == ("REVIEW",
                                               ["SOURCE_LABEL_MISMATCH"])
    assert [e["alias"] for e in r["examples"]["label_issues"]] == ["NC_001807.4"]
    assert r["label_issue_count"] == 1
    assert r["mito"]["records"] == ["chrM", "chrMT"] and r["mito"]["multiple"]


# ---- reproducible, offline report --------------------------------------------

def _fake_fetch(responses):
    calls = []

    def fetch(url, timeout=60):
        calls.append(url)
        if url == audit.CATALOG_URL:
            return 200, _catalog(
                okA1={"active": 1, "organism": "A"},
                gone1={"active": 1, "organism": "G"},
                bad1={"active": 1, "organism": "B"}), ""
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(url)
    fetch.calls = calls
    return fetch


RESPONSES = {
    "/okA1/": (200, gz(*CLEAN), "Mon"),
    "/gone1/": (404, None, ""),
    "/bad1/": (200, gz("1\tchr1\tassembly", "1\tchr2\tassembly"), "Tue"),
}


def test_report_is_deterministic_and_rerunnable_from_the_cache(tmp_path):
    cache = audit.Cache(tmp_path)
    fetch = _fake_fetch(RESPONSES)
    first = audit.run_audit(cache, fetch=fetch)
    calls = len(fetch.calls)
    offline = audit.run_audit(cache)                    # cache only, no fetch
    again = audit.run_audit(cache, fetch=fetch)         # everything cached
    assert len(fetch.calls) == calls                    # no repeat downloads
    def dump(report):
        return json.dumps(report, sort_keys=True)
    assert dump(first) == dump(offline) == dump(again)
    s = first["summary"]
    assert s["candidates"] == 3 and s["with_chrom_alias"] == 2
    assert s["status_counts"] == {"FAIL": 1, "NO_SOURCE": 1, "PASS": 1}
    assert s["reason_code_counts"]["ALIAS_COLLISION"] == 1
    assert first["audit"]["audit_date"] == "2026-02-03"
    assert [a["db"] for a in first["assemblies"]] == ["bad1", "gone1", "okA1"]
    assert "ERROR" not in s["status_counts"]


def test_uncached_candidate_is_an_error_not_a_verdict(tmp_path):
    cache = audit.Cache(tmp_path)
    fetch = _fake_fetch({**RESPONSES, "/okA1/": OSError("boom")})
    report = audit.run_audit(cache, fetch=fetch)
    by_db = {a["db"]: a for a in report["assemblies"]}
    assert by_db["okA1"]["status"] == "ERROR"
    assert by_db["okA1"]["reason_codes"] == ["FETCH_ERROR"]


def test_offline_run_never_calls_a_fetcher(tmp_path, monkeypatch):
    cache = audit.Cache(tmp_path)
    audit.run_audit(cache, fetch=_fake_fetch(RESPONSES))

    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(audit, "http_fetch", boom)
    monkeypatch.setattr(audit.urllib.request, "urlopen", boom)
    assert audit.run_audit(cache)["summary"]["candidates"] == 3


def test_pass_size_summary_counts_only_passing_assemblies(tmp_path):
    report = audit.run_audit(audit.Cache(tmp_path), fetch=_fake_fetch(RESPONSES))
    size = report["summary"]["pass_size"]
    ok = next(a for a in report["assemblies"] if a["db"] == "okA1")
    assert size["assemblies"] == 1
    assert size["tsv_bytes_total"] == ok["estimated_tsv_bytes"]
    assert size["tsv_bytes_median"] == ok["estimated_tsv_bytes"]


def test_summary_text_lists_every_assembly(tmp_path):
    report = audit.run_audit(audit.Cache(tmp_path), fetch=_fake_fetch(RESPONSES))
    text = audit.summary_text(report)
    for db in ("okA1", "gone1", "bad1"):
        assert f"| {db} |" in text


# ---- committed snapshot (consistency only; never refetched in tests) ---------

@pytest.mark.skipif(not SNAPSHOT.exists(), reason="no committed snapshot")
class TestCommittedSnapshot:
    def setup_method(self):
        self.report = json.loads(SNAPSHOT.read_text())

    def test_counts_are_consistent(self):
        a, s = self.report["assemblies"], self.report["summary"]
        assert s["candidates"] == len(a) == self.report["audit"]["candidate_count"]
        statuses = {}
        for entry in a:
            statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
        assert statuses == s["status_counts"]
        assert "ERROR" not in statuses

    def test_every_reason_code_is_declared_and_consistent_with_status(self):
        for entry in self.report["assemblies"]:
            assert set(entry["reason_codes"]) <= set(audit.REASONS)
            status = entry["status"]
            if status == "PASS":
                assert entry["reason_codes"] == ["PASS"]
            if status == "NO_SOURCE":
                assert entry["reason_codes"] == ["NO_CHROM_ALIAS"]
            if status == "FAIL":
                assert set(entry["reason_codes"]) & set(audit.FAIL_CODES)
            if status == "REVIEW":
                assert set(entry["reason_codes"]) & set(audit.REVIEW_CODES)
                assert not set(entry["reason_codes"]) & set(audit.FAIL_CODES)

    def test_passing_entries_are_fully_verified(self):
        for entry in self.report["assemblies"]:
            if entry["status"] == "PASS":
                assert entry["wide_schema_lossless"] is True
                assert entry["builder_ok"] and entry["oracle_ok"]
                assert entry["loader_ok"] and entry["estimated_tsv_exact"]
                assert entry["collision_count"] == 0
                assert entry["label_issue_count"] == 0
                assert entry["accession_issue_count"] == 0

    def test_the_six_current_assemblies_classify_as_known(self):
        by_db = {a["db"]: a for a in self.report["assemblies"]}
        assert {db: by_db[db]["status"] for db in audit.PRODUCTION} == {
            "hg38": "PASS", "hg19": "REVIEW", "mm39": "PASS", "dm6": "PASS",
            "danRer11": "PASS", "rn7": "PASS"}

    def test_the_audit_and_the_builder_never_disagree(self):
        assert self.report["summary"]["builder_audit_disagreements"] == 0

    def test_snapshot_pins_its_inputs(self):
        meta = self.report["audit"]
        assert meta["catalog_url"] == audit.CATALOG_URL
        assert len(meta["catalog_sha256"]) == 64
        for entry in self.report["assemblies"]:
            if entry["status"] != "NO_SOURCE":
                assert len(entry["source_sha256"]) == 64
