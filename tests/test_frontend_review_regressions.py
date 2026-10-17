"""Review findings F2, F3, F4, F5, N2, N3 — React source regressions.

These guard the frontend half of the reviewed fixes. There is no JS test
runner in this repo, and the existing parity suite already asserts on
``App.jsx`` source (see
``test_api_functional_parity.test_frontend_source_defaults_match_the_backend_contract``),
so the guards here follow the same convention.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "frontend" / "src" / "App.jsx").read_text("utf-8")


def test_f2_vcf_export_control_only_renders_for_vcf_queries():
    # The VCF download anchor must stay inside the VCF-query condition; the
    # server-side gate (test_shared_vcf_export.TestVcfExportGating) is the
    # enforcement, this is the UI half of the same contract.
    assert "queryData?.format?.toLowerCase() === 'vcf'" in APP_SOURCE
    assert "/api/export/vcf?filter_type=" in APP_SOURCE
    # The guard must come before the anchor in the source.
    assert (
        APP_SOURCE.index("queryData?.format?.toLowerCase() === 'vcf'")
        < APP_SOURCE.index("/api/export/vcf?filter_type=")
    )


def test_f3_single_position_sentinel_defaults_and_maps_to_null():
    sentinel = "None (single positions)"
    assert f"const NO_END_COLUMN = '{sentinel}';" in APP_SOURCE
    # Auto-detection falls back to the sentinel, not a positional column.
    assert (
        "data.columns.find(c => /end|stop/i.test(c)) || NO_END_COLUMN" in APP_SOURCE
    )
    # The mapping payload translates the sentinel to an explicit null.
    assert "end_col: endCol === NO_END_COLUMN ? null : endCol" in APP_SOURCE
    # The sentinel is a selectable option, not just an internal default.
    assert "<option value={NO_END_COLUMN}>{NO_END_COLUMN}</option>" in APP_SOURCE


def test_f4_gene_list_panel_rendered_from_execute_payload():
    assert "gene_list" in APP_SOURCE
    assert "Top 10 genes" in APP_SOURCE
    assert "gene_list.txt" in APP_SOURCE
    assert "gene_list.csv" in APP_SOURCE
    # The panel is driven by the execute response, not a second fetch.
    assert "execResult?.gene_list" in APP_SOURCE
    assert "/api/results/gene-list" not in APP_SOURCE


def test_f5_stale_results_cleared_on_relevant_changes():
    assert "const clearResults = () => {" in APP_SOURCE
    # Every configuration change that invalidates a previous run must clear
    # the displayed results (the full wiring list is reviewed finding F5).
    for change in (
        "setEngine('bedtools'); clearResults()",
        "setEngine('polars-bio'); clearResults()",
        "setMode(e.target.value); clearResults()",
        "setJoin('left'); clearResults()",
        "setCoordSystem(e.target.value); clearResults()",
        "setAnnotSystem(e.target.value); clearResults()",
        "setGenomeAssembly(e.target.value); clearResults()",
        "setChrHandling(e.target.value); clearResults()",
        "setUseStrand(e.target.checked); clearResults()",
        "setMinOverlap(parseFloat(e.target.value)); clearResults()",
    ):
        assert change in APP_SOURCE, change
    # Loading a new dataset or a new upload starts from no results.
    assert APP_SOURCE.count("clearResults()") >= 12


def test_n2_coord_system_change_invalidates_the_loaded_dataset():
    # The declared coordinate system is baked into the parsed table at upload
    # time, so changing the declaration afterwards must invalidate the stored
    # dataset for that side (locally and server-side) and force a re-upload,
    # not silently re-run the stale table (final-gate finding N2).
    assert "const invalidateDataset = (role) => {" in APP_SOURCE
    # The F5 wiring above is preserved with the invalidation appended.
    assert (
        "setCoordSystem(e.target.value); clearResults(); invalidateDataset('query')"
        in APP_SOURCE
    )
    assert (
        "setAnnotSystem(e.target.value); clearResults(); invalidateDataset('annot')"
        in APP_SOURCE
    )
    # The server-side copy is cleared too ...
    assert "/api/dataset/clear" in APP_SOURCE
    # ... and the file input is remounted so the browser's picker cannot
    # silently reuse the invalidated file on re-upload.
    assert "setQueryUploadKey((k) => k + 1)" in APP_SOURCE
    assert "setAnnotUploadKey((k) => k + 1)" in APP_SOURCE
    assert 'key={`query-upload-${queryUploadKey}`}' in APP_SOURCE
    assert 'key={`annot-upload-${annotUploadKey}`}' in APP_SOURCE


def test_n3_stale_execute_responses_are_discarded_and_controls_locked():
    # An in-flight /api/execute response only lands if no invalidating event
    # happened after the run started, so a stale run can never resurrect
    # results for a newer configuration (final-gate finding N3).
    assert "const runGeneration = useRef(0);" in APP_SOURCE
    assert "const generation = ++runGeneration.current;" in APP_SOURCE
    assert "if (runGeneration.current !== generation) return;" in APP_SOURCE
    # A superseded run finishing must not re-enable the button while a newer
    # run is still in flight.
    assert "const activeExecGeneration = useRef(0);" in APP_SOURCE
    assert "if (activeExecGeneration.current === generation) setIsExecuting(false);" in APP_SOURCE
    # While a run is in flight the configuration controls are locked ...
    assert APP_SOURCE.count("disabled={isExecuting}") >= 13
    # ... and the results header states the operation the run actually used.
    assert "{execResult.stats.mode} / {execResult.stats.join}" in APP_SOURCE