# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Modern React + Tailwind CSS frontend interface with real-time progress indicators, interactive statistics visualizations, gene frequency charting, and one-click data previews.
- FastAPI backend service (`streamlit_app.api_server`) exposing annotation endpoints, sample dataset inspection, and progress tracking.
- Automated frontend linting and build validation step (`oxlint` + `vite build`) in GitHub Actions CI workflow (`python-tests.yml`).
- Multi-stage Docker build producing an optimized production container image with embedded frontend assets and non-root user execution (`appuser:appgroup`).
- Restored the "Charts and gene list" results panel from the original Streamlit application: a top-10 gene/feature bar chart and gene-list export (`.txt` / comma-separated `.csv`) for external enrichment tools (g:Profiler, Enrichr, DAVID, STRING), served by the new `GET /api/results/gene-list` endpoint and the `gene_list` field of the execute response.
- `POST /api/dataset/clear` endpoint that discards one role's stored dataset together with any result derived from it, without allocating a session (it is a state removal, not a write).
- Frontend behavioral test suite (dev-only `vitest` + `jsdom` + Testing Library, `frontend/src/app.behavior.test.jsx`, run by `npm test`) covering the two final-gate races in the real component: coordinate-system change invalidating a loaded dataset (N2), and a superseded in-flight `/api/execute` response being discarded while all inputs stay locked (N3).

### Changed
- Result statistics report match coverage as query-row-identity matches (`matched_query_count`), and the React results header and summary use it instead of result-row counts.
- Annotated VCF export is only offered for VCF queries, in the React UI and enforced at the HTTP boundary, matching the Streamlit application.
- The results table is cleared whenever the dataset or any execution configuration changes, so a stale result can no longer be displayed as if it belonged to a new run.
- Single-position queries (no end column) now map to one-base intervals via an explicit "None (single positions)" end-column sentinel instead of silently using a positional column.
- Changing the declared coordinate system of an already-loaded file now invalidates that side's dataset (locally, server-side, and the file picker) and requires a re-upload under the new declaration, instead of silently re-running the stale, already-normalized table (final-gate finding N2).
- While an annotation run is in flight all configuration controls are locked, and a superseded run's response can no longer land in the UI: an `/api/execute` response is applied only if no invalidating event happened after the run started (final-gate finding N3). The results header now states the operation mode and join the run actually used.
- `docs/deployment.md` now states what the React/FastAPI image actually reads: `PORT`, `FORWARDED_ALLOW_IPS`, `MAX_FILE_SIZE_MB`, and the new `ANNOTATER_CORS_ORIGINS`; the upload's temporary parsing copy lives under the system temp directory (`tempfile.mkdtemp`) and is deleted immediately, not under `TEMP_DIR` (which, with `CLEANUP_AFTER_HOURS`, belongs to the Streamlit-generation helpers only); the session-cookie section documents the `__Host-` prefixed HTTPS cookie name (final-gate finding N5).

### Fixed
- Single-position (end-column-less) queries no longer depend on which column happens to be third in the input table.

### Security
- `GET /api/results/data` page size is bounded to 10,000 rows per request.
- Unauthenticated read requests are served by throwaway sessions: they consume no session capacity, receive no session cookie, and can no longer evict a real user's state from the bounded session store.
- Session capacity is now consumed lazily on the first state write: anonymous or forged-cookie requests — including failed writes such as oversized or invalid uploads — allocate no session slot and can no longer exhaust the store or evict a real user's session (final-gate finding N4).
- Over HTTPS the session cookie is issued and honoured only under the `__Host-` prefixed name `__Host-annotater_session` (Secure, `Path=/`, no `Domain`), scoped to the exact issuing host: an unprefixed `annotater_session` cookie — even one carrying a live token planted by a sibling subdomain — is ignored over TLS, closing the session-fixation path (final-gate finding N1). Plain-HTTP local development keeps the unprefixed name.
- CORS no longer reflects arbitrary request origins; cross-origin access requires an explicit allowlist via the `ANNOTATER_CORS_ORIGINS` environment variable (default: none). A bare `*` entry is rejected because, with credentialed CORS, it would reflect every request origin (final-gate finding N6).

## [0.1.0-rc2] - 2026-10-02

### Added
- Assembly-aware chromosome normalization architecture supporting standard assemblies (GRCh38, GRCh37, GRCm39, etc.) and custom coordinate registries.
- Strict parity verification harness between Bedtools and Polars-Bio backends across overlap, closest, and strand-aware modes.
- End-to-end container health smoke checks and deterministic benchmark harness in CI.
- Comprehensive documentation covering deployment, architecture, engine contracts, and reproducibility.

### Changed
- Streamlit application unified backend selection allowing dynamic engine switching with guaranteed schema parity.
- License formalized as BSD-3-Clause across codebase, packaging, and metadata.

## [0.1.0-rc1] - 2026-09-28

### Added
- Initial release candidate for AnnotateR on SciLifeLab Serve.
- Core genomic coordinate annotation pipeline with interchangeable Bedtools and Polars-Bio execution engines.
- Basic Streamlit UI for coordinate upload (BED, VCF), annotation files (BED, GFF, GTF), and tabular exports.
