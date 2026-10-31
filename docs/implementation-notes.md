# Implementation notes

Living audit log for the Polars-Bio parity initiative. Task 1 recorded the
baseline; this section records the **Task 2.5 dependency/runtime/reference
audit**.

## Task 2.5 — dependency/runtime/reference audit (2026-09-21)

### Supported environment

| Item | Value |
|---|---|
| Python | 3.12.14 (venv at `.venv`, created by `uv` 0.11.8) |
| OS (audit host) | macOS arm64 |
| bedtools | v2.31.1 at `/opt/homebrew/bin/bedtools` (Homebrew, **system mode**) |
| pybedtools | 0.12.1 |
| polars | 1.44.2 |
| polars-bio | 0.35.1 |
| pandas | 3.0.6 |
| numpy | 2.5.3 |
| streamlit | 1.64.0 (native `st.testing.v1.AppTest` works headless) |
| pytest | 9.1.1 (with `pytest-cov` 7.1.0) |

The venv has no `pip` module; it is managed by `uv`. `uv.lock` is committed
alongside the exact-pinned `pyproject.toml` / `requirements.txt` and
`requirements-dev.txt`. `SPEC.md` contains **no normative minimum-Python
requirement**; **Python 3.12 is the currently tested and supported
runtime** established by Task 2.5. The exact dependency pins install on
Python ≥ 3.12 (verified installable under 3.14), so `pyproject.toml`
declares `requires-python = ">=3.12,<3.15"`; CI builds 3.12 and the
production Dockerfile uses `python:3.12-slim`. Python 3.13/3.14 satisfy
the range but are **not** part of the tested CI matrix; 3.10/3.11 cannot
install the pins at all (e.g. `numpy==2.5.3` requires ≥ 3.12).

### pybedtools mode: system binary, not embedded

- `pybedtools.check_for_bedtools()` → `True`; no `set_bedtools_path` was
  ever called. pybedtools 0.12.1 resolves the `bedtools` executable from
  `PATH` at call time (`shutil.which`); the command line observed in a live
  `intersect` was `bedtools intersect -a ... -wb -wa -b ...`.
- There is **no embedded/private bedtools binary** in the venv, and
  pybedtools 0.12.1 exposes no `utils.bedtoolsPath` attribute (removed API).
- Consequence: any environment (developer machine, container, CI) MUST
  install a bedtools binary and put it on `PATH`. CI installs it via
  `apt-get` (Ubuntu) / `brew` (macOS).

### polars-bio 0.35.1 API contract (observed, verified live)

- The historical `polars_bio.io.genomic_intervals.overlap` path **no
  longer exists**; `polars_bio.io` is a module, not a package. The current
  entry point is **top-level `polars_bio.overlap`** (and `nearest`,
  `count_overlaps`, `coverage`, ...).
- `pb.overlap` signature (0.35.1):
  `(df1, df2, suffixes=('_1','_2'), on_cols=None, cols1=['chrom','start','end'],
  cols2=['chrom','start','end'], algorithm='Coitrees', low_memory=False,
  overlap_output='join', distinct_output=False, output_type='polars.LazyFrame', ...)`
- `overlap_output="join"` (default) returns joined pairs with `_1`/`_2`
  suffixes. `overlap_output="left"` returns **only left rows that overlap**
  (confirmed: it is NOT a left outer join — consistent with
  `docs/engine-contract.md` section 6).
- **Coordinate-system behavior (important):** since 0.35.1, polars-bio reads
  a coordinate-system metadata stamp set at I/O time; when metadata is
  missing it falls back to the global session option
  `datafusion.bio.coordinate_system_zero_based`, whose default is **1-based
  (closed intervals)** and it emits a `UserWarning` on every call.
  Upstream spec (biodatageeks/polars-bio,
  `openspec/.../coordinate-system/spec.md`) documents: 0-based = half-open
  `[start, end)`, 1-based = closed `[start, end]`.
  Verified live: with the option explicitly set to `true`, touching
  intervals `[10,20)` vs `[20,25)` produce **0** overlap rows; with the
  default (unset, 1-based), the same inputs produce **1** (wrong, for
  AnnotateR's canonical 0-based data).
- `pb.overlap` accepts pandas DataFrames directly; observed output dtypes:
  `chrom_*` String, `start_*`/`end_*` int64.

### Observed current engine behavior (captured, not fixed)

Fixtures: query `chrA:100-200 (g1)`, `chrA:10-20 (g2)`, `chrA:2000-2100
(g3)`; annotation `chrA:150-250 (f1)`, `chrA:2000-2050 (f2)`.

| Scenario | BedtoolsEngine | PolarsBioEngine |
|---|---|---|
| inner, 1 match + 1 non-match | 2 rows; columns already exactly canonical `coord_*`/`annot_*` + `has_overlap` (bool) | 2 rows; but **both frames get `coord_` prefix**, `_1`/`_2` suffixes, internal `coord_pb_row_id_1` leaked |
| left, same fixture | 3 rows, unmatched query once with `has_overlap=False`; unmatched annotation fields are bedtools sentinels `.`/`-1` (not canonical NA) | 3 rows, unmatched query once with `has_overlap=False`; clean `coord_*` columns plus duplicated suffixed `coord_*_1/_2` columns |
| no match, inner | 0 rows | 0 rows |
| no match, left | 1 query row, `has_overlap=False` | 1 query row, `has_overlap=False` |
| touching `[10,20)` vs `[20,25)` | correctly 0 rows | **incorrectly 1 row** (1-based default re-interpretation, see above) |
| one-base `[10,20)` vs `[19,20)` | 1 row | 1 row |

These deviations are encoded as explicit assertions in
`tests/test_engine_contract.py`; the currently-failing ones are marked
`xfail(strict=True)` with the precise root cause so the suite stays green
while the deviations remain documented. Because the markers are **strict**,
any future run in which a guarded assertion unexpectedly passes fails the
suite with XPASS, forcing the obsolete marker to be reviewed and removed.
**Removing an xfail marker requires the engine to actually pass the
assertion** (Task 3/4 work).

### Current implementation limitations

1. **Polars-Bio coordinate-system mis-interpretation (highest risk).**
   `PolarsBioEngine` passes canonical 0-based half-open DataFrames to
   `pb.overlap` without declaring the coordinate system, so polars-bio
   0.35.1's 1-based global default applies. Touching intervals are reported
   as overlapping. Fix (explicit `pb.set_option` / metadata stamp) belongs
   to Task 3/4; the audit only records and tests against it.
2. **Polars-Bio result schema.** `PolarsBioEngine._post_process` prefixes
   *every* column with `coord_` (including annotation-frame columns),
   leaks the internal `pb_row_id` row-identity column, and keeps
   polars-bio `_1`/`_2` suffixes. Violates SPEC section 9.2 and
   `docs/engine-contract.md` section 3 (annotation fields must carry the
   `annot_` provenance prefix).
3. **Bedtools left-mode sentinels.** `BedtoolsEngine._bedtool_to_df` keeps
   bedtools `-loj` sentinel values (`.` / `-1`) in unmatched annotation
   fields instead of canonical missing values (engine-contract section 6).
   Its `to_dataframe(header=None)` also positionally names 6-wide rows as
   BED6 (`name`/`score`/`strand`) before the engine renames columns.
4. **Backend exception swallowing.** `PolarsBioEngine._join_overlap` catches
   *all* exceptions from `pb.overlap` and returns an empty frame
   (`logger.error` + `return pl.DataFrame()`) — SPEC section 9 requires
   explicit propagation. Same pattern in `_find_nearest`. Not changed here
   (no behavior changes in Task 2.5); must be fixed in Task 4.
5. **Python interpreter range.** Exact pins require Python ≥ 3.12
   (`numpy==2.5.3`). `SPEC.md` states no minimum-Python requirement, so
   there is no SPEC conflict: 3.12 is the Task 2.5 supported runtime and
   `pyproject.toml` / CI / Docker all declare it. Python 3.10/3.11 are not
   supported while these exact pins hold.
6. **Dependency disposition (audit complete).** Repository-wide audit
   (runtime code, tests, dynamic imports, export paths, documentation
   workflows, deployment files):
   - **removed:** `python-magic`, `validators`, `pyranges`, `altair` — no
     imports, dynamic imports, tests, or documentation-supported workflow
     uses any of them. `altair` remains available transitively via
     `streamlit`, so Streamlit charting is unaffected.
   - **retained:** `openpyxl` — concrete role: Excel export
     (`pd.ExcelWriter(engine='openpyxl')` in
     `streamlit_app/streamlit_app.py`, Excel download path).
   `requirements.txt`, `pyproject.toml`, and `uv.lock` were updated and the
   lockfile regenerated after removal. Every *remaining* runtime dependency
   has a verified current role: `streamlit` (app framework), `pandas`
   (canonical tables), `numpy` (`core/annotator.py`), `pybedtools`
   (Bedtools backend), `polars` (Polars-Bio backend dependency),
   `polars-bio` (Polars-Bio backend), `openpyxl` (Excel export), `plotly`
   (app charts, `streamlit_app.py`).
7. **`pb.overlap` warning noise.** Every polars-bio call in tests emits the
   missing-coordinate-metadata `UserWarning` (see limitation 1). It
   disappears once the engine declares the coordinate system.

### Contract tests added (Task 2.5)

**Scope note (honest Task 3 boundary):** Task 2.5 was a dependency/runtime
audit; it did **not** implement Task 3. While recording the observed
backend output contracts, the audit *opportunistically established an
initial engine-contract baseline*: `tests/test_engine_contract.py` carries
parameterized differential tests over both `BedtoolsEngine` and
`PolarsBioEngine`, and captures **five known deviations as strict xfails**.
This is intentionally a minimal harness, not the full Task 3 suite. Task 3
should later expand it systematically (more modes, strand handling, larger
synthetic fixtures, nearest-operator semantics, result-adapter edge cases)
and keep the strict-xfail guardrail convention.

- `tests/test_engine_contract.py` — both engines through identical
  fixtures: inner match/non-match, left mode preserving the non-matching
  query exactly once with `has_overlap=False`, no-match → 0 rows (inner) /
  preserved query row (left), plus SPEC section 4 boundary semantics
  (touching = no overlap, one-base = overlap, different chromosomes) and
  canonical-schema assertions (strict-xfail where currently deviated).
- `tests/test_parser_contract.py` — BED passthrough, GFF3 1-based
  inclusive → 0-based half-open, VCF POS/END span → canonical, custom CSV
  with declared coordinate system, and known formats immune to
  `declared_system` re-interpretation.
- `tests/test_streamlit_app_contract.py` — `st.testing.v1.AppTest`
  headless smoke run of `streamlit_app/streamlit_app.py`.

### Test command and baseline

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

(or `python -m pytest` with the venv activated; `pytest.ini` pins
`testpaths = tests` and `pythonpath = .`).

Task 2.5 completion baseline: **142 passed, 5 xfailed, 0 failed, 0
skipped** (previous baseline: 117 passed). See the task report for the
exact three consecutive full-suite runs.

### CI

`.github/workflows/python-tests.yml` runs the suite on `ubuntu-latest` and
`macos-latest` with Python 3.12, installs the bedtools binary via
`apt-get`/`brew`, installs `requirements-dev.txt`, and runs `pytest`
(3.10/3.11 are omitted from the matrix because the exact pins cannot
install there; see limitation 5).

### Docker runtime verification (Task 2.5 review resolution)

- The production `Dockerfile` was updated from `python:3.10-slim` to
  `python:3.12-slim` to match the supported runtime. The image's
  `HEALTHCHECK` invokes `curl`; `python:3.12-slim` does not ship `curl`, so
  `curl` was added to the apt install list (previously the healthcheck
  would have failed with command-not-found in the final image).
- Verification was performed by building the image from scratch
  (`docker build --platform linux/amd64 -t annotater:task25 .` —
  successful; the earlier default-platform arm64 build is the one
  described in the platform limitation below) and running checks inside
  the resulting container. Observed output:
  - Python 3.12.14; `bedtools --version` → `bedtools v2.31.1`
    (`/usr/bin/bedtools`)
  - imports OK: `pybedtools` 0.12.1, `polars` 1.44.2, `polars_bio`
    0.35.1 (top-level `pb.overlap` callable), `streamlit` 1.64.0,
    `pandas` 3.0.6, `numpy` 2.5.3, `openpyxl` 3.1.5
  - AnnotateR core public API imports OK (`streamlit_app.core`:
    `BedtoolsEngine`, `PolarsBioEngine`, `FormatDetector`,
    `BEDParser`/`GFFParser`/`VCFParser`, `CoordinateConverter`,
    `CoordinateNormalizer`, canonicalization/validation helpers)
  - `curl` 8.14.1 present (`/usr/bin/curl`) — the only external command
    used by the `HEALTHCHECK` (`curl --fail
    http://localhost:8501/_stcore/health`) and the compose healthcheck
  - full test suite in an equivalent clean container (production image +
    mounted `tests/` + `pytest.ini`, ephemeral `pip install pytest
    pytest-cov`; the production image intentionally excludes test
    dependencies): **142 passed, 5 xfailed, 0 failed, 0 skipped**, exit
    code 0
- **Known platform limitation (found during Docker verification):**
  `polars-bio==0.35.1` publishes a manylinux **x86_64-only** wheel (no
  `aarch64` wheel); on Linux/aarch64, pip falls back to the sdist and the
  maturin/Rust source build fails in the slim image. The supported
  production image therefore targets `linux/amd64`
  (`docker build --platform linux/amd64 ...`), which matches the GitHub
  CI runners. Native arm64 Linux deployment would require either an
  upstream `aarch64` wheel or a Rust toolchain build stage — out of
  Task 2.5 scope. (macOS arm64 developer machines are unaffected: a
  `macosx_11_0_arm64` wheel exists.)
## Task 3 — engine parity harness (2026-09-22)

Task 3 built the systematic Bedtools <-> Polars-Bio parity harness and
used it to produce the first complete, executable deviation inventory.
**No engine behavior was fixed in this task** (the one exception is the
minimal canonical-adapter bug fix S1 below, which was required for the
harness to run at all and is engine-neutral). Polars-Bio was not touched;
all Polars-Bio deviations are assigned to Task 4.

### Harness design (`tests/parity/`)

Three layers of evidence, per `docs/engine-contract.md` section 14:

1. **Explicit expected fixtures** (`cases.py`, `fixtures.py`): tiny
   in-memory canonical tables (0-based half-open) with expected rows
   encoded as `(query_row, annot_row_or_None)` tuples in canonical row
   order, derived from `max(starts) < min(ends)` and the SPEC 7.2
   left-mode rules — never from backend output.
2. **Per-engine contract tests**: each engine runs through
   `run_and_canonicalize` (engine → raw result →
   `canonicalize_annotation_result`) and is compared with
   `assert_canonical_equal` — a strict comparator enforcing exact
   canonical column set + order, row count (multiplicity), row order,
   NA-aware values, real booleans, and contractually normative dtypes
   (`coord_start`/`coord_end` int64, `annot_start`/`annot_end` Int64,
   `has_overlap` bool).
3. **Differential comparison** (`test_differential_parity.py`):
   Bedtools canonical result vs Polars-Bio canonical result on
   representative fixtures, in addition to layer 1+2.

Coverage areas: overlap (exact/partial/containment, one-to-many,
many-to-many, duplicates), boundary off-by-one matrix (incl.
zero-based coordinates and `chr0`/`chr10` lexical trap), left-join
(UNM = canonical missing, not bedtools `-loj` sentinels), metadata
provenance (colliding names, arbitrary/numeric/boolean/missing values,
column order, reserved prefixes), deterministic ordering (inputs placed
out of coordinate order), strand (`use_strand=False` neutrality only),
and the error/failure contract (SPEC 9.2). Raw-layer diagnostics
(`test_backend_raw_diagnostics.py`) attribute each deviation to its
exact layer and record positive controls for conformant layers.

xfail discipline: markers are EXPLICIT per (case, engine) with
root-cause reasons (registry in `tests/parity/fixtures.py`);
`xfail_strict = true` is now global in `pytest.ini`. A fixed deviation
XPASSes and fails CI until its stale marker is removed; a new
non-conforming case fails loudly instead of silently xfailing.
`tests/test_engine_contract.py` was shrunken to smoke-level raw-output
contract tests; all five Task 2.5 strict xfails were migrated into the
parity harness with equal-or-better coverage (none lost).

### Current deviation inventory (Task 3)

**Polars-Bio (all assigned to Task 4):**

- **P1 — non-canonical result schema.**
  `PolarsBioEngine._post_process` prefixes BOTH frames with `coord_`,
  retains polars-bio `_1`/`_2` suffixes, leaks the internal `pb_row_id`
  column, and no `annot_*` columns exist.
  `canonicalize_annotation_result` therefore rejects every non-empty
  output (`CanonicalSchemaError`) before any semantic comparison.
  Violates SPEC 6 (exact canonical column set with provenance prefixes)
  and SPEC 9.2 (provenance must not be guessed by suffix heuristics);
  engine-contract section 3.
  *Pinned by:* every non-empty canonical-level parity case (36 strict
  xfails), `test_polars_raw_inner_output_is_canonical` (raw layer), and
  all differential cases.
- **P2 — coordinate system never declared.**
  `PolarsBioEngine` does not set polars-bio's coordinate-system option,
  so polars-bio 0.35.1's global default (1-based CLOSED intervals)
  re-interprets canonical 0-based half-open data: touching intervals
  (`[10,20)` vs `[20,25)`) are reported as overlapping. Violates SPEC 5;
  engine-contract section 4. The deviation is in the RAW overlap call
  (wrong row set before any post-processing).
  *Pinned by:* 5 touching/boundary strict xfails plus
  `test_polars_raw_touching_intervals_do_not_overlap`.
- **P3 — `pb.overlap` failures swallowed.**
  `_join_overlap` catches ALL exceptions and returns an empty frame
  (log only), converting backend failure into a plausible empty result.
  Violates SPEC 9.2. *Pinned by:*
  `test_polars_overlap_backend_failure_propagates` (strict xfail).
- **P4 — `pb.nearest` failures swallowed.** Same pattern in
  `_find_nearest`. Violates SPEC 9.2. *Pinned by:*
  `test_polars_nearest_backend_failure_propagates` (strict xfail).

**Bedtools:**

- **B1 — empty-input guard drops left rows.**
  `BedtoolsEngine.intersect` returns an empty frame whenever EITHER
  input is empty, so `how="left"` with an empty annotation table drops
  every query row instead of preserving them as unmatched. Violates
  SPEC 7.2; engine-contract section 6. *Pinned by:*
  `left_empty_annotation_table[bedtools]` (strict xfail).
- **B2 — missing metadata lost.** A missing metadata value on a matched
  row round-trips as the `'.'` sentinel and the column degrades to
  string, instead of canonical missing. Violates SPEC 6 /
  engine-contract section 8. *Pinned by:*
  `metadata_missing_values_matched_rows[bedtools]` (strict xfail).
- **B3 — numeric-looking string metadata re-typed.** String metadata
  such as `'3.5'` round-trips as float `3.5` because
  `BedTool.to_dataframe` re-infers dtypes from text. Violates SPEC 6
  (deterministic metadata preservation) and SPEC 10.3. *Pinned by:*
  `metadata_string_numeric_looks[bedtools]` (strict xfail).
- **B4 — raw left sentinels.** Raw left-mode output keeps bedtools
  `-loj` sentinel values (`'.'`/`'-1'`) in unmatched annotation fields
  instead of canonical missing. Currently masked at the public level by
  `canonicalize_annotation_result`; the engine should emit canonical
  missing directly (engine-contract sections 6/8; Task 5). *Pinned by:*
  `test_bedtools_raw_left_unmatched_uses_canonical_missing` (strict
  xfail).
- **B5 — result-parsing failures swallowed (DISCOVERED in Task 3).**
  `BedtoolsEngine._bedtools_to_df` catches ALL
  `BedTool.to_dataframe` exceptions and returns an empty DataFrame —
  the same SPEC 9.2 violation class as P3/P4, on the Bedtools side.
  *Pinned by:* `test_bedtools_result_parsing_failure_propagates`
  (strict xfail).

**Shared canonical adapter:**

- **S1 — all-matched frames with bool/int64 `annot_*` columns crashed
  canonicalization (DISCOVERED and MINIMALLY FIXED in Task 3).**
  `canonicalize_annotation_result` unconditionally executed
  `out.loc[~matched, annot_cols] = CANONICAL_MISSING`; under pandas 3.x
  the scalar is dtype-validated even when the mask is empty, raising
  `TypeError: Invalid value 'nan' for dtype 'bool'` for any all-matched
  result carrying a bool annotation column (verified on pinned pandas
  3.0.6: bool raises; a plain-int64 column was probed and does not). This is
  engine-neutral (it would crash for both engines) and blocked the
  harness from testing the metadata contract, so it was fixed with a
  one-line guard (`if (~matched).any():`) in
  `streamlit_app/core/schema.py`. No matched-row semantics changed.
  *Pinned by:* `metadata_boolean_values` (the pre-fix crash case) and
  `metadata_numeric_values` (both engines now pass).

### Positive controls (layers that already conform)

- Bedtools **raw inner** output is already canonical (exact
  `coord_*`/`annot_*` schema + `has_overlap` bool):
  `test_bedtools_raw_inner_output_is_canonical` passes.
- Bedtools **ordering and multiplicity** are deterministic and match
  the canonical ordering rule for every ordering fixture, including
  duplicate-valued rows (rerun determinism verified).
- Polars-bio **left row reconstruction** (row-id join back onto the
  query frame) correctly preserves unmatched query rows at the RAW
  layer — its left-mode deviation is only the schema (P1), not row
  loss: `test_polars_raw_left_reconstructs_unmatched_queries`.
- **Empty inputs** produce valid empty results for both engines (0
  rows, full canonical schema after adaptation) — distinct from the
  swallowed-failure deviations above.
- **Unknown `mode`** raises an explicit `ValueError` for both engines;
  **malformed input** (missing `chr`) raises explicitly for both;
  **bedtools backend failure** (`BedTool.intersect` raising) propagates.
- Strand values round-trip as metadata and do not affect matching when
  `use_strand=False` (Bedtools; Polars-Bio blocked by P1 only).

### Documented gaps (not tested — not yet normative)

- `use_strand=True` semantics (SPEC 8.3; engine-contract section 10) —
  neither engine implements it; no fixture invents the behavior. Note
  for Task 6: `BedtoolsEngine._df_to_bedtool` places metadata columns
  in source order, so a `strand` column lands in the BED name position,
  not the BED6 strand position — `-s` semantics would misread it.
- `min_overlap` (engine-contract section 9): ambiguous mapping to
  bedtools `-f`/`-F`/`-r`/`-e` must be fixed in a dedicated task before
  parity is claimed.
- `contains`/`within`/`closest` (engine-contract sections 11-12):
  predicates not yet normative.

### Test command and baseline (Task 3)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 3 completion baseline: **199 passed, 60 xfailed, 0 failed, 0
skipped** (previous baseline: 142 passed, 5 xfailed). The 60 strict
xfails are exactly the P1-P4/B1-B5 deviations above (see the inventory
for which fixture pins which deviation). Pinned environment: Python
3.12.14, bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2,
polars-bio 0.35.1, pandas 3.0.6.

## Task 4 — Polars-Bio contract compliance (2026-09-22)

**Result: P1–P4 resolved.** `PolarsBioEngine` now satisfies the engine
contract for the covered parity surface: canonical result schema with
explicit provenance, 0-based half-open coordinate semantics,
deterministic ordering, left-mode reconstruction, and backend error
propagation. All 55 strict Polars-Bio xfails from Task 3 were converted
to passing tests (their markers were removed); the 5 Bedtools xfails
(B1–B5) remain, out of scope for this task.

### PolarsBioEngine rewrite (deviations P1–P4)

The engine was rewritten around a single explicit mapping strategy.
The old code passed pandas DataFrames into `pb.overlap` and repaired
the output with a broken `_right`-suffix heuristic; it also set no
coordinate-system metadata and swallowed all backend exceptions.

- **Per-frame coordinate stamping (P2).** Both backend frames are
  stamped `frame.config_meta.set(coordinate_system_zero_based=True)`
  on the polars frame (polars 1.44 `config_meta`, read by polars-bio
  0.35.1's `_metadata.get_coordinate_system`). This is the narrowest
  mechanism: it declares the coordinate system exactly where the data
  lives, without mutating the process-wide
  `datafusion.bio.coordinate_system_zero_based` option (polars-bio's
  own default is 1-based CLOSED, the wrong model for canonical data).
  No global option is read or written, so BedtoolsEngine and
  PolarsBioEngine can run in one process without interfering, and the
  engine is correct regardless of any external global setting.
- **Explicit provenance mapping (P1).** Backend frames carry a
  collision-safe positional row-identity column
  (`_pb_query_row_id` / `_pb_annot_row_id`, suffix-bumped if the name
  already exists). `pb.overlap`/`pb.nearest` are called with explicit
  `suffixes=("_1", "_2")`, `cols1`, `cols2`. The adapter builds the
  rename map from the KNOWN input schema (never from suffix
  heuristics on the output) and validates the raw output as an exact
  column-set match; any mismatch raises `CanonicalSchemaError`
  (SPEC 9.2). Row IDs are dropped before the public result.
- **Deterministic ordering.** Rows are sorted by
  `(query_row_id, annotation_row_id)` — input row identity, never
  coordinate — giving the canonical order (query input order, then
  annotation input order) including for duplicate-valued rows.
- **Left mode.** Unmatched queries are reconstructed by set-difference
  on query row IDs and appear exactly once with canonical missing
  annot fields and `has_overlap=False` (SPEC 7.2), in canonical
  position (sorted by row ID with the matched rows).
- **Error propagation (P3, P4).** `pb.overlap` / `pb.nearest` are
  called without any try/except: backend exceptions propagate. A 0-row
  result with no exception is a genuine no-match (valid empty), not a
  swallowed failure.
- **Input validation.** Engine entry validates both inputs with
  `validate_canonical_interval_table`; malformed input raises
  `CanonicalSchemaError` instead of reaching the backend.
- **Empty results.** A 0-row raw result short-circuits to a genuinely
  empty result (`inner`: empty frame; `left`: unmatched query rows).

### Newly discovered in Task 4

- **P5 (fixed) — `pb.nearest` phantom rows for empty annotation.**
  With an empty annotation frame, `pb.nearest` still emits one row per
  query with ALL annotation fields null (k=1 with no neighbor); the
  adapter previously turned these into `has_overlap=True` rows with
  NA annotation coordinates. `_nearest` now drops rows whose
  annotation row ID is null, so closest mode with an empty annotation
  table returns a genuinely empty result (SPEC 9.2). *Pinned by:*
  `test_polars_inner_empty_inputs_return_empty_result`.
- **`pb.nearest` distance dtype** is integer when the gap is integral
  (observed `Int64` for integral inputs); consumers must not assume
  float.

### Focused regression tests (`tests/test_polars_bio_engine.py`)

New module pinning guarantees the parity suite only exercises
indirectly: half-open semantics with the global option explicitly set
to the wrong model (per-frame stamping wins); the engine leaves the
process-wide option untouched; raw output has no backend artifacts
(no `_1`/`_2` suffixes, no row-ID columns, exact canonical column
set); raw output is accepted as-is by
`canonicalize_annotation_result` for every how/mode combination
(`closest` declares `distance` as an extra column); empty-input
matrix (all mode/how/emptiness combinations); left with empty
annotation preserves queries; closest distance column semantics;
malformed input raises explicitly.

### Test command and baseline (Task 4)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 4 completion baseline: **262 passed, 5 xfailed, 0 failed, 0
skipped** (previous baseline: 199 passed, 60 xfailed). The 5 remaining
strict xfails are exactly B1–B5 (Bedtools). Pinned environment: Python
3.12.14, bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2,
polars-bio 0.35.1, pandas 3.0.6.

### Remaining known deviations (unchanged, Task 5/6)

B1 (empty-input guard drops left rows), B2 (missing metadata lost),
B3 (numeric-looking string metadata re-typed), B4 (raw left
sentinels), B5 (result-parsing failures swallowed) — all Bedtools;
see the Task 3 inventory above. Documented gaps (non-normative):
`use_strand=True`, `min_overlap`, `contains`/`within` (Task 6).

## Task 5 — Bedtools contract compliance (2026-09-22)

**Result: B1–B5 resolved.** `BedtoolsEngine` now satisfies the engine
contract on the covered parity surface: canonical result schema with
explicit provenance, lossless metadata round-trip, canonical missing on
unmatched left rows, deterministic empty-input handling, and backend
error propagation. All 5 strict Bedtools xfails from Task 3 were
converted to passing tests (their markers were removed). `use_strand`,
`min_overlap`, and `contains`/`within` semantics remain documented
gaps (Task 6).

### BedtoolsEngine rewrite (deviations B1–B5)

The engine was rewritten around an identity-only adapter. The old code
serialized the WHOLE input frame (stringified metadata, `.fillna('.')`)
into BED, read the raw output through pandas dtype inference
(`to_dataframe` with no dtype argument), guessed provenance from column
counts, and swallowed every `to_dataframe` exception.

- **Identity-only serialization (B2, B3).** The bedtools text file now
  carries ONLY `chr`/`start`/`end` plus a collision-safe internal
  row-identity column (`_bt_query_row_id` / `_bt_annot_row_id`,
  suffix-bumped if the name exists) per side. User metadata never
  crosses the text boundary: after matching, every published
  coord/annotation/metadata value is re-attached from the ORIGINAL
  validated input frames by row identity. Missing values become
  canonical missing (`pd.NA`), never the `'.'` sentinel (B2);
  numeric-looking strings keep their type (B3); numpy scalars are
  reduced to the Python scalars the canonicalizer's `astype(object)`
  publication uses, so raw output matches the canonicalized expected
  values cell-for-cell.
- **Structural sentinel handling (B4).** Raw output is read with
  `to_dataframe(header=None, dtype=str)` — pure text, no dtype
  inference. Match determination is structural, not value-based:
  bedtools `-loj` fills unmatched annotation fields with sentinels
  (`.`/`-1`), and the adapter reads the INTERNAL annotation row-id
  column, where `'.'` can only be a backend sentinel (row ids are
  engine-generated integers `0..n-1`). Real user metadata values such
  as `'.'` or `'-1'` are re-attached from the input frame and can never
  be mistaken for missing values. Unmatched rows carry canonical
  missing in every `annot_*` field and `has_overlap=False`.
- **Deterministic empty-input handling (B1).** Both inputs are
  validated with `validate_canonical_interval_table` first (malformed
  input raises, never a silent empty result). With an empty annotation
  table, `left` mode returns every query row unmatched WITHOUT
  invoking bedtools (the canonical result is already known); `inner`
  returns a genuinely empty result. A 0-row raw result with no
  exception is a genuine no-match, never a swallowed failure.
- **Error propagation (B5).** `intersect`/`closest`/`to_dataframe` are
  called without any try/except; backend and conversion exceptions
  propagate to the caller (SPEC 9.2). `pybedtools.cleanup()` runs in a
  `finally` block.
- **Deterministic ordering.** Rows are sorted by
  `(query row id, annotation row id)` — input row identity, never
  coordinate — giving the canonical order (query input order, then
  annotation input order) including for duplicate-valued rows.
- **Raw layout validation.** The raw frame must have exactly
  `2 * columns_per_side` columns (8 unstranded) or `2 *
  columns_per_side + 1` for `closest -d` (9 unstranded); any other
  layout raises `CanonicalSchemaError` (no positional guessing).

### Newly discovered / handled in Task 5

- **`use_strand=True` needed an explicit strand column.** bedtools
  `-s` requires a strand in column 6; the old code only worked by
  accident (user `strand` metadata happened to cross the boundary in
  column order). The stranded serialization now carries
  `chr/start/end/<row id>/. (score)/strand` per side (12 raw columns,
  13 with `closest -d`): the user's `strand` metadata when present,
  else `'.'` (unstranded, matches nothing under `-s`). The unstranded
  path is unchanged. The flag itself is still forwarded to bedtools
  `-s` unchanged — `use_strand` SEMANTICS remain Task 6 scope.
- **bedtools `closest -d` distance is its own non-normative value**:
  for `[15,25)` vs `[100,200)` it reports 76 (the Polars-Bio `nearest`
  gap for the same pair is 75). Closest's full semantics stay Task 6;
  the adapter only guarantees a lossless `Int64` round-trip of the
  backend-reported value (`NA` when no feature was found).
  (**Superseded by Task 6E — see the Task 6E section below: closest no
  longer consumes any backend-native selection or distance; the
  canonical gap is 75 on both engines, pinned by a regression test.)**
- **`bedtools closest` requires genomically sorted input** (pre-existing
  bedtools requirement, unchanged): unsorted query/annotation frames
  raise `BEDToolsError` from the binary itself, which now propagates
  explicitly instead of being swallowed.

### Focused regression tests (`tests/test_bedtools_engine.py`)

New module pinning guarantees the parity suite only exercises
indirectly: raw output is exactly the canonical column set (no BED
field names, row-id columns, or `col_N` padding) and is accepted as-is
by `canonicalize_annotation_result` for every how/mode combination
(`closest` declares `distance`); the real-user-value regression — user
metadata values `'.'`/`'-1'` survive a matched round-trip verbatim,
genuinely missing values round-trip as `pd.NA` (never `'.'`), and
numeric-looking strings (`'3.5'`, `'00123'`) keep their type; left
mode with an empty annotation table is produced deterministically with
ZERO bedtools invocations (monkeypatched proof); backend
(`BEDToolsError`) and conversion (`to_dataframe`) failures propagate;
duplicate-valued rows keep the (query identity, annotation identity)
expansion order; `closest` keeps the lossless `Int64` distance extra
column; `use_strand` is forwarded to bedtools `-s` unchanged.

### Test command and baseline (Task 5)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 5 completion baseline: **282 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 262 passed, 5 xfailed). No known-deviation
xfails remain for either engine. Pinned environment: Python 3.12.14,
bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2, polars-bio 0.35.1,
pandas 3.0.6.

### Remaining known deviations (Task 6)

None for the canonical covered surface. Documented gaps (non-normative,
unchanged in Task 5): `use_strand=True` semantics (flag forwarded,
matching semantics undefined), `min_overlap` (forwarded to `-f` in
overlap mode only), `contains`/`within` (`-f 1.0`/`-F 1.0`
placeholders), `closest` full semantics (distance definition, tie
breaking).

## Task 6A — min_overlap semantics (2026-09-23)

**Scope:** fix one backend-independent meaning for the existing single
`min_overlap` parameter and lock it with contract + parity tests.
Strand/contains/within/closest semantics remain out of scope (Task
6B–6E backlog, untouched).

### Normative definition (SPEC 8.2)

`min_overlap` is the **minimum fraction of the canonical query
interval covered by a single annotation interval** for that
query/annotation pair to qualify as a match:

```text
overlap_length = max(0, min(q_end, a_end) - max(q_start, a_start))
query_length   = q_end - q_start
qualifies iff  overlap_length > 0 AND overlap_length / query_length >= min_overlap
```

- Query-relative: denominator is the query length. NOT the annotation
  fraction, NOT reciprocal (bedtools `-r`), NOT either-side (`-e`),
  NOT coverage summed across annotation rows.
- Inclusive threshold (`>=`); ordinary positive overlap still required
  (touching intervals never match, even at `min_overlap=0`).
- Valid domain: `None` (no threshold) or a number in `[0, 1]` (int or
  float — integers `0`/`1` are valid numeric equivalents, normalized to
  `float`). Negative, >1, NaN, ±inf, booleans, and non-numeric types
  raise `ValueError`; invalid values are never clamped or forwarded to
  a backend.
- Left mode: the threshold participates in match determination. A
  query whose annotation matches all fail the threshold is emitted
  exactly once, unmatched (`has_overlap=False`, no failing match row).

### Validation policy

Validated once in the shared `AnnotationEngine` constructor via the
module-level `validate_min_overlap` (in `streamlit_app/core/annotator.py`),
so both backends validate identically and the rejection happens
**before any backend execution** (proven by a monkeypatched no-call
test). One consistent exception type: `ValueError`, matching the
existing public API's invalid-parameter handling (unknown `mode`).

### Architecture: shared canonical post-filter

```text
canonical inputs
      ↓
ordinary backend overlap (NO backend fraction option for min_overlap)
      ↓
canonical matched pairs
      ↓
shared min_overlap_keep_mask filter   ← SPEC 8.2 predicate, one code path
      ↓
left reconstruction (if how="left")
      ↓
canonical output
```

`min_overlap_keep_mask(df, min_overlap)` in
`streamlit_app/core/annotator.py` is the single contract-level
predicate; both engines call it on their canonical-column frames
(after backend matching, before left reconstruction). Unmatched
(-loj sentinel) rows are excluded from the predicate and pass through
unchanged; queries losing all matches are then reconstructed as
unmatched by the existing left logic.

### Bedtools strategy

`min_overlap` is **no longer mapped to bedtools `-f`** (the historical
behavior). Reasons, all demonstrated during this task:

- bedtools v2.31.1 rejects `-f 0.0` outright (its range is
  `(0.0, 1.0]`, verified against the installed binary): the old
  wiring made the valid no-op threshold `0.0` a hard `BEDToolsError`;
- the contract is backend-independent by definition — applying the
  identical shared predicate removes any reliance on bedtools'
  version-specific fraction arithmetic (double division + `<` cutoff);
- `-f`/`-F` remain internally available and are still used only by the
  non-normative contains/within placeholders (unchanged, Task 6C/6D
  scope).
- For the record: bedtools v2.31.1 `-f` was empirically verified to be
  a fraction of A (the query) and to use an inclusive cutoff, so the
  old behavior agreed with the new contract for `0 < f <= 1`; the
  `f = 0` crash and the version-coupling are why the shared filter was
  preferred anyway.

### Polars-Bio strategy

Pinned polars-bio 0.35.1 `overlap` exposes **no fraction mechanism**
(signature + docstring verified against the installed package), so
AnnotateR's query-fraction contract is enforced explicitly with the
same shared predicate over the ordinary `pb.overlap` pairs. The
`coordinate_system_zero_based=True` per-frame metadata handling is
untouched; no global configuration introduced.

### Tests

- `tests/parity/cases.py`: `MIN_OVERLAP_CASES` — 25 cases × 2 engines
  (50 parameterized tests) covering: full overlap at thresholds 0/0.5/1.0; exactly-half boundary
  (0.49/0.50/0.51, pins `>=`); one-base boundary (0.10/0.11); touching
  at 0.0; annotation-larger-than-query at 1.0 (query-relative);
  query-larger-than-annotation (0.10/0.11); reciprocal distinction
  (annotation 10% covered, query 100% → match at 1.0, would fail under
  `-r`); no aggregation across two 0.30 annotations (inner + left);
  one-pass-one-fail; multiple qualifying in annotation input order;
  duplicate queries (inner + left, incl. all-failing left); duplicate
  annotations; metadata (incl. missing value) through filtering; left
  mixed qualifying/failing/no-match; 1/3 precision boundary (Task 6A
  review: pins IEEE-754 exactly-rounded division at an irrational
  threshold); within-placeholder scope (Task 6A review: the filter is
  NOT applied in the non-normative `within` mode). 8 of them are also in
  `DIFFERENTIAL_CASES` (direct engine-vs-engine layer, which now
  forwards `case.engine_kwargs`).
- `tests/parity/test_min_overlap_parity.py`: every case against BOTH
  engines via the strict canonical comparator (explicit expected rows,
  never backend output).
- `tests/test_min_overlap_validation.py`: invalid values
  (`-0.01`, `-1`, `1.01`, `2`, NaN, ±inf, `True`, `False`, `"0.5"`)
  raise `ValueError` for both engines; valid values (`None`, `0`,
  `0.0`, `0.5`, `1`, `1.0`) accepted with documented int normalization;
  monkeypatched proof that an invalid value never invokes either
  backend; both engines accept/reject exactly the same value set.

### Behavior changes

- **Bug fixed:** `min_overlap=0.0` previously crashed BedtoolsEngine
  (bedtools `-f 0.0` is a hard error); it is now a valid no-op
  threshold, matching the UI help text ("0 = any overlap").
- **Bug fixed:** PolarsBioEngine previously ignored `min_overlap`
  entirely; it now enforces the same contract.
- For `0 < min_overlap <= 1` in plain overlap mode, BedtoolsEngine
  results are unchanged (bedtools `-f` agreed with the contract there);
  the code path changed (post-filter instead of `-f`) but results do
  not.
- Invalid thresholds (out of range/NaN/±inf/bool/non-numeric) now
  raise `ValueError` at engine construction instead of being forwarded
  to bedtools (error) or silently ignored (polars-bio).
- No changes to strand, contains, within, or closest behavior; no new
  user-facing knobs; no UI changes (the slider already maps 0 → `None`).
  The min_overlap post-filter is explicitly gated to `overlap` mode in
  both engines (Task 6A review decision — the non-normative
  contains/within placeholders keep their exact pre-Task-6A behavior),
  pinned by `min_overlap_within_placeholder_not_applied`.

### Review (Task 6A)

Two independent fresh-context Pi subagent reviews (semantics-vs-spec and
implementation/tests) at HEAD: both verdicts **OK with notes**, all
normative points CONFORMS, no P0/P1 semantics findings. Resolved
findings: (1) PLAN.md case count 22 → 25; (2) the post-filter was
initially applied in all modes that route through the shared overlap
path — gated to `overlap` mode only so the contains/within placeholders
are untouched, with a pinning parity case; (3) added a 1/3 precision
pinning case. Accepted as-is (documented, no change): `np.int64` is
rejected as non-numeric (SPEC 8.2 names Python int/float; the UI passes
Python float); the mocked-backend validation test proves rejection at
construction, which satisfies "before backend execution" by definition.
Deferred: stale `use_strand` bullet in `tests/parity/test_extended_semantics.py`
(pre-existing since Task 5; fixed when Task 6B lands), min_overlap ×
`use_strand` cases (6B), min_overlap + left + empty-table cases
(early-return paths, low risk).

### Test command and baseline (Task 6A)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 6A completion baseline: **375 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 282 passed), run twice after the review
fixes. Focused counts: min-overlap contract parity 50 passed (25 cases
× 2 engines), differential parity 16 passed (8 pre-existing + 8
min-overlap), validation 35 passed, full parity suite 178 passed.
Pinned
environment: Python 3.12.14, bedtools 2.31.1, pybedtools 0.12.1,
polars 1.44.2, polars-bio 0.35.1, pandas 3.0.6.

### Remaining known deviations (Task 6 backlog)

`min_overlap` is now normative and parity-protected. Documented gaps
(non-normative, unchanged in Task 6A): `use_strand=True` matching
semantics (flag forwarded to bedtools `-s`; the stranded serialization
exists but the contract is undefined), `contains`/`within` (bedtools
`-f 1.0`/`-F 1.0` placeholders / polars-bio no-op — engine-contract
section 11), `closest` full semantics (distance definition, tie
breaking; the 76-vs-75 discrepancy noted in Task 5 remains).

## Task 6B — strand semantics (2026-09-23)

`use_strand` now has one normative, backend-independent meaning (SPEC
8.3; engine-contract section 10):

- `use_strand=False`: strand does not participate in match
  qualification (pre-Task-6B behavior, unchanged);
- `use_strand=True`: a pair qualifies only if the interval predicate
  qualifies AND both rows carry an explicit canonical strand
  (`+`/`-`) and the strands are equal.

### Decisions

- **Missing/unknown strand is NOT a wildcard.** Canonical missing
  (including a source `.` after normalization) and an entirely absent
  strand column on either input make a stranded match impossible —
  including unknown-vs-unknown. The behavior is identical for both
  engines because the predicate is shared.
- **No native backend strand option.** Bedtools no longer forwards `-s`
  on the overlap path: its treatment of `.`/missing strand is
  undocumented and must not define the AnnotateR contract (bedtools'
  stranded serialization + `-s` were also structurally broken — the
  12-column raw layout parsed the strand column as the annotation row
  id, so any stranded inner match crashed). Pinned polars-bio 0.35.1
  `overlap` exposes no strand option at all. Both engines therefore run
  an ordinary unstranded overlap and apply the shared canonical
  predicate post-hoc — the same architecture as Task 6A `min_overlap`.
  The stranded serialization + native `-s` remain ONLY in the
  non-normative `closest` placeholder, unchanged (Task 6E scope).
  (**Superseded by Task 6E:** the closest path no longer uses stranded
  serialization or native `-s`; both engines apply the shared strand
  predicate to the closest candidate set before nearest selection.)
- **No mode gating.** The shared strand predicate applies to every mode
  that routes through the engines' overlap path (overlap and the
  non-normative contains/within placeholders), because SPEC 8.3 defines
  strand as orthogonal to the *selected* interval predicate. This
  slightly changes both engines' contains/within placeholder behavior
  (strand now participates identically on both) while those predicates
  remain non-normative — their full contract is Task 6C/6D scope.
  (Contrast Task 6A: `min_overlap` IS gated to overlap mode because
  SPEC 8.2 is defined for the overlap method only.)
- **Logical AND with `min_overlap`.** The predicates are independent:
  strand is applied first, `min_overlap` second; neither bypasses the
  other (no precedence).
- **Left mode.** A query whose geometrical overlaps all fail the strand
  predicate is unmatched exactly once (SPEC 7.2); a query with at least
  one qualifying match emits only its qualifying matches.
- **Validation.** Canonical strand values other than `+`/`-`/missing
  (`?`, `*`, `plus`, `1`, `""`, ...) were already rejected by
  `validate_canonical_interval_table` before Task 6B; Task 6B adds
  engine-level tests proving rejection for both engines BEFORE any
  backend execution. No parser/validation redesign was needed.

### Implementation

- `streamlit_app/core/annotator.py`:
  - new contract-level `strand_keep_mask(df, q_meta, a_meta)`:
    `coord_strand == annot_strand` with both values explicit
    (`+`/`-`); canonical missing (pd.NA/NaN) compares False; an absent
    strand column on either side yields an all-False mask (NOT a
    fall-back to unstranded mode);
  - `BedtoolsEngine._overlap`: ordinary unstranded `intersect` (no
    `s` flag, always the 4-column identity serialization per side) +
    the shared strand post-filter after matching and before left
    reconstruction (`-loj` sentinel rows pass through untouched);
    `_to_bed` gained an explicit `stranded` parameter (only
    `_closest` requests the stranded layout now);
  - `PolarsBioEngine._adapt_overlap_result`: the same shared post-filter
    before the `min_overlap` filter;
  - stale docstrings (Task 6-scope flag forwarding, stranded overlap
    serialization, "engines do not yet implement" strand bullets)
    corrected.
- UI: the checkbox already passed a boolean correctly; only the help
  text was updated to state the normative semantics (missing strand
  never matches in stranded mode).

### Tests

- `tests/parity/cases.py`: `STRAND_CASES` expanded from 1 to 29
  explicit-fixture cases covering the full Task 6B fixture matrix
  (same/opposite/missing/both-missing strands, `.` normalization,
  one-query-two-strands, duplicate queries/annotations, left mismatch /
  left mixed, different chromosome, touching boundaries,
  strand × min_overlap composition (both pass / strand fail /
  threshold fail / left reconstruction), and missing strand column in
  inner and left mode); 15 representative strand fixtures added to
  `DIFFERENTIAL_CASES`.
- `tests/parity/test_extended_semantics.py` →
  `tests/parity/test_strand_parity.py`: per-engine contract layer
  (29 cases × 2 engines) plus
  `test_strand_dot_source_value_not_wildcard` (BED file end-to-end:
  source `.` → canonical missing → not a wildcard under stranded
  matching, both engines).
- `tests/test_strand_validation.py`: malformed canonical strand values
  (`?`, `*`, `plus`, `1`, `""`) raise `InvalidIntervalError` for BOTH
  engines before any backend execution (monkeypatched no-backend
  proof).
- `tests/test_bedtools_engine.py`:
  `test_bedtools_strand_flag_forwarded` replaced by
  `test_bedtools_overlap_does_not_delegate_strand_to_backend` (no
  `s` flag on the overlap path; `closest` still forwards its
  non-normative `-s`).

### Behavior changes

- Bedtools `use_strand=True` (overlap mode): previously delegated to
  native `-s` with a stranded serialization; the missing-strand
  behavior of that path was backend-defined and the layout parsing was
  broken (crash on stranded inner matches). Now: explicit AnnotateR
  contract, both engines identical.
- Polars-Bio `use_strand=True` (overlap mode): previously ignored the
  flag entirely (silently returned unstranded results — a SPEC
  violation). Now enforces the same shared contract.
- `use_strand=False` results are unchanged on both engines.
- Contains/within placeholders: strand now participates identically on
  both engines (documented above); the placeholders remain
  non-normative.
- Closest: unchanged (native `-s` on bedtools, ignored on polars-bio),
  non-normative, Task 6E scope. (**Superseded by Task 6E — closest is
  fully normative now; see the Task 6E section below.**)

### Test command and baseline (Task 6B)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 6B completion baseline: **460 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 375 passed), run twice. Focused counts:
strand contract parity 59 passed (29 cases × 2 engines + 1 `.`
end-to-end), strand validation 13 passed, differential parity 31
passed (16 pre-existing + 15 strand), full parity suite 250 passed.

### Remaining known deviations (Task 6 backlog)

`use_strand` and `min_overlap` are now normative and parity-protected.
Documented gaps (non-normative): `contains`/`within` (bedtools
`-f 1.0`/`-F 1.0` placeholders / polars-bio no-op — engine-contract
section 11), `closest` full semantics (distance definition, tie
breaking; the 76-vs-75 discrepancy noted in Task 5 remains; the
bedtools `-s` forwarding there is a placeholder, not the Task 6B
contract).

## Task 6C — contains semantics (2026-09-23)

`mode="contains"` now has one normative, backend-independent meaning
(SPEC 8.4; engine-contract section 11):

> **contains means the query interval fully contains the annotation
> interval.**

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)

contains(Q, A) =
    q_start <= a_start
    AND
    q_end >= a_end
```

Directionality is fixed. Boundary equality counts (identical intervals,
shared left boundary, shared right boundary all qualify). Partial
overlaps, boundary-touching intervals, and annotation-contains-query
(the `within` direction) do not qualify. This resolves the former
non-normative `contains` placeholder from the Task 6A/6B notes above.

### Decisions

- **contains is NOT `min_overlap = 1.0`.** `min_overlap` (SPEC 8.2)
  measures the fraction of the QUERY interval covered by one annotation
  and is defined for overlap mode only; containment constrains both
  annotation boundaries against the query. Neither implication holds:
  `Q[10,20)/A[0,100)` matches at `min_overlap = 1.0` but is not
  containment; `Q[0,100)/A[10,20)` is containment but covers only 10% of
  the query. Both directions are pinned by regression tests.
- **`min_overlap` is not applied in contains mode** (SPEC 8.2 is scoped
  to the overlap method). The Task 6A gate is preserved exactly; the
  contains exemption is now pinning-tested rather than incidental.
- **Strand composes by logical AND** (SPEC 8.3). Task 6B's decision that
  the strand predicate is NOT mode-gated means it applies to contains
  unchanged: a contained pair still needs an explicit equal strand under
  `use_strand=True`, and missing strand is not a wildcard.
- **Left mode respects `how`.** `mode="contains"` now honors
  `how="left"` (the old Bedtools placeholder forced an inner run): every
  query row survives, contained matches are emitted in annotation input
  order, and a query with zero contained annotations appears exactly once
  as unmatched (`has_overlap=False`, canonical-missing `annot_*`).
- **`within` is untouched** and remains non-normative future scope
  (Task 6D). Its placeholder mapping (bedtools `-F 1.0`; polars-bio
  plain overlap with a documented no-op filter) is unchanged, as is
  `closest`. (**Superseded by Task 6D — see the Task 6D section below:**
  `within` is now normative and the placeholder mapping is removed.)
- **`has_overlap` keeps its name.** In a non-overlap mode it means
  "the selected relation produced a qualifying match"; the canonical
  column is deliberately not renamed in this task.

### Implementation

- `streamlit_app/core/annotator.py`:
  - new contract-level shared predicate
    `contains_keep_mask(df)` implementing
    `coord_start <= annot_start AND coord_end >= annot_end`. Unmatched
    rows (missing annotation coordinates) evaluate to False.
  - `BedtoolsEngine.intersect`: `overlap` and `contains` share the
    ordinary backend overlap path; the former
    `-f 1.0` placeholder for contains is removed. `how` is passed
    through, so left-mode reconstruction applies. `within` keeps its
    `-F 1.0` placeholder (`how="inner"`, unchanged).
  - `BedtoolsEngine._overlap`: the shared contains post-filter runs
    after the strand predicate and before left reconstruction;
    `-loj` sentinel rows pass through untouched.
  - `PolarsBioEngine.intersect`: `overlap` and `contains` share the
    `pb.overlap` path; only `within` keeps `_filter_fraction`.
  - `PolarsBioEngine._adapt_overlap_result`: the same shared contains
    post-filter runs after the strand predicate and before left
    reconstruction; queries losing every candidate are reconstructed as
    unmatched.
- Candidate generation is **ordinary backend overlap**, never a
  backend-native containment flag and never a Cartesian query x
  annotation product: containment implies overlap, so overlap candidates
  are lossless. Both engines use the same shared predicate, so the
  meaning is identical by construction (same architecture as the Task 6A
  `min_overlap` and Task 6B `strand` predicates).
- Bedtools strategy: the old `-f 1.0` mapping was removed, not
  preserved. Bedtools `-f` is a fraction of A (the query) — a different,
  version-coupled predicate whose direction is backend-defined — so it
  must not define the AnnotateR contract. `-f`/`-F` now remain only for
  the non-normative `within` placeholder.
- Polars-Bio strategy: pinned polars-bio 0.35.1 exposes no
  query-contains-annotation primitive, so ordinary `pb.overlap`
  candidates are filtered by the same shared predicate. The per-frame
  `coordinate_system_zero_based=True` metadata, exception propagation,
  deterministic ordering, and row-identity handling from Tasks 4-6B are
  untouched.

### Tests

- `tests/parity/cases.py`: `CONTAINS_CASES` — 34 explicit-fixture cases
  covering strict containment, exact equality, shared left/right
  boundaries, annotation-contains-query, partial left/right overlap,
  touching left/right, different chromosome, multiple contained
  annotations (including annotation input order vs coordinate order),
  mixed contained/partial/container, duplicate queries and annotations,
  left no-qualifying / mixed / multi-query reconstruction, both
  `min_overlap` asymmetry directions, the `min_overlap`-not-applied
  exemption (inner + left), strand same/opposite/missing/both-missing/
  missing-column/ignored, metadata preservation, and the empty-input
  matrix. 21 representative cases are also in `DIFFERENTIAL_CASES`.
- `tests/parity/test_contains_parity.py`: per-engine contract layer
  (34 cases x 2 engines) plus backend-independent units of the shared
  predicate (truth table incl. equality/boundaries/reverse direction,
  missing annotation), the explicit contains-vs-`min_overlap=1.0`
  asymmetry for both engines, the `min_overlap`-not-applied regression,
  left reconstruction, empty-input row counts, and monkeypatched proofs
  that neither backend receives a fraction/containment option
  (candidate generation is ordinary overlap).
- `tests/test_bedtools_engine.py`, `tests/test_polars_bio_engine.py`:
  the raw-schema and empty-input matrices now include `contains` mode.
- UI copy: `streamlit_app/config/settings.py` description corrected from
  the wrong direction ("Find annotations completely containing
  coordinates") to the normative one; the stale `bedtools_args: {"f":
  1.0}` entry was replaced by the ordinary-overlap args actually used.
  README/QUICKSTART contains wording corrected to the same direction.
  No UI redesign; the mode selector surface is unchanged.

### Behavior changes

- `mode="contains"` on BOTH engines previously returned the wrong or
  approximate relation (bedtools `-f 1.0` = annotation-covers-query with
  an inner-only forced join; polars-bio returned plain overlap). It now
  returns query-contains-annotation, for inner and left.
- The old `-f 1.0` placeholder path was removed from BedtoolsEngine.
- `within` and `closest` behavior is unchanged.

### Test command and baseline (Task 6C)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Focused counts: contains contract parity 80 passed (34 cases x 2 engines
+ 12 focused tests), differential parity 52 passed (31 pre-existing +
21 contains), full parity suite 351 passed. Repository-wide:
**561 passed, 0 xfailed, 0 failed, 0 skipped** (previous baseline: 460
passed). Pinned environment: Python 3.12.14, bedtools 2.31.1, pybedtools
0.12.1, polars 1.44.2, polars-bio 0.35.1, pandas 3.0.6.

### Remaining known deviations (Task 6 backlog)

`min_overlap`, `use_strand`, and `contains` are now normative and
parity-protected. Documented gaps (non-normative): `within` (bedtools
`-F 1.0` placeholder / polars-bio plain-overlap no-op), and `closest`
full semantics (distance definition, tie breaking; the 76-vs-75
discrepancy noted in Task 5 remains; the bedtools `-s` forwarding there
is a placeholder).

## Task 6D — within semantics (2026-09-24)

`mode="within"` now has one normative, backend-independent meaning
(SPEC 8.5; engine-contract section 11):

> **within means the query interval is fully contained within the
> annotation interval.**

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)

within(Q, A) =
    a_start <= q_start
    AND
    a_end >= q_end
```

Directionality is fixed and is the opposite of `contains`: the
annotation is the containing interval, the query is the contained
interval. Boundary equality counts (identical intervals, shared left
boundary, shared right boundary all qualify). Partial overlaps,
boundary-touching intervals, and query-contains-annotation (the
`contains` direction) do not qualify. This resolves the former
non-normative `within` placeholder described in the Task 6A/6B/6C notes
above.

### Decisions

- **within is the directional inverse of contains.** `within(Q, A) ==
  contains(A, Q)`: the predicate is the same boundary comparison with the
  query/annotation roles swapped. Equality satisfies BOTH relations,
  because equal intervals contain each other. Both directions and the
  equality case are pinned by regression tests.
- **within is NOT `min_overlap`, and not a coverage threshold.**
  `min_overlap` (SPEC 8.2) measures the fraction of the QUERY covered by
  one annotation and is defined for overlap mode only. `Q[10,20)` vs
  `A[5,15)` has query fraction exactly 0.5, so `min_overlap=0.5`
  qualifies in overlap mode while `within` must not qualify at any
  threshold; `Q[10,20)` vs `A[0,100)` is `within` and also happens to
  cover the whole query. The relation is never inferred from an overlap
  percentage (or from a backend fraction option).
- **`min_overlap` is not applied in within mode** (SPEC 8.2 is scoped to
  the overlap method; the Task 6A mode gate is preserved verbatim). Note
  the exemption is not observable *for a genuine within pair*: full query
  coverage means the query fraction is exactly 1.0, so every valid
  threshold is satisfied anyway. The test suite therefore pins the
  distinction in the direction that IS observable — a partial candidate
  that passes a 0.5 threshold but is not a within match — plus a direct
  predicate assertion that within pairs have query fraction 1.0.
- **Strand composes by logical AND** (SPEC 8.3). Task 6B's decision that
  the strand predicate is NOT mode-gated means it applies to within
  unchanged: a contained pair still needs an explicit equal strand under
  `use_strand=True`, and missing/unknown strand (including an absent
  strand column) is not a wildcard.
- **Left mode respects `how`.** Every query row survives; within matches
  are emitted in annotation input order; a query with zero containing
  annotations appears exactly once as unmatched (`has_overlap=False`,
  canonical-missing `annot_*`). Failing candidate rows are never emitted
  alongside an unmatched row.
- **`has_overlap` keeps its name**: in within mode it means "the selected
  relation produced a qualifying match".

### Implementation

- `streamlit_app/core/annotator.py`:
  - new contract-level shared predicate `within_keep_mask(df)`
    implementing `annot_start <= coord_start AND annot_end >= coord_end`.
    Unmatched rows (missing annotation coordinates) evaluate to False.
  - `BedtoolsEngine.intersect`: `overlap`, `contains`, and `within` now
    share the ordinary backend overlap path. The former placeholder call
    (`how="inner", F=1.0`) is removed, as are the `f`/`F` keyword
    arguments of `BedtoolsEngine._overlap`: no fraction flag is forwarded
    to bedtools anywhere on the overlap path.
  - `BedtoolsEngine._overlap`: the interval-relation post-filter
    (`contains_keep_mask` or `within_keep_mask`, selected by `mode`) runs
    after the strand predicate and before left reconstruction; `-loj`
    sentinel rows pass through untouched.
  - `PolarsBioEngine.intersect`: `overlap`, `contains`, and `within` share
    the `pb.overlap` path; the obsolete `_filter_fraction` no-op helper is
    deleted.
  - `PolarsBioEngine._adapt_overlap_result`: the same shared predicates
    are applied after the strand predicate and before left reconstruction;
    queries losing every candidate are reconstructed as unmatched.
- Candidate generation is **ordinary backend overlap**, never a
  backend-native containment flag and never a Cartesian query x
  annotation product: a containment pair in either direction necessarily
  overlaps, so overlap candidates are lossless. Both engines use the same
  shared predicate, so the meaning is identical by construction (same
  architecture as the Task 6A `min_overlap`, Task 6B `strand`, and Task 6C
  `contains` predicates).
- Bedtools strategy: the old `-F 1.0` placeholder was removed, not
  preserved. Bedtools `-F` is a minimum overlap as a fraction of **B**,
  and AnnotateR passes the annotation table as `-b`, so `-F 1.0` computed
  annotation-inside-query — the *contains* direction — with an inner-only
  join (the documented `how="left"` contract was silently dropped on
  that path too). A backend-defined fraction flag must not define an
  AnnotateR relation, so the overlap path now forwards no
  `-f`/`-F`/`-r`/`-e` at all.
- Polars-Bio strategy: pinned polars-bio 0.35.1 exposes no containment
  primitive in either direction (verified against the installed package),
  so ordinary `pb.overlap` candidates are filtered by the same shared
  predicate. The per-frame `coordinate_system_zero_based=True` metadata,
  exception propagation, deterministic ordering, and row-identity
  handling from Tasks 4-6C are untouched.

### Tests

- `tests/parity/cases.py`: `WITHIN_CASES` — 39 explicit-fixture cases
  covering strict within, exact equality, shared left/right boundaries,
  query-contains-annotation, partial left/right overlap, touching
  left/right, different chromosome, multiple containing annotations
  (including annotation input order vs coordinate order), mixed
  containing/partial/contained, duplicate queries, duplicate annotations,
  duplicate query x annotation multiplicity, left no-qualifying / mixed /
  multi-query reconstruction, both within-vs-contains directions,
  equality satisfying both, the within-vs-`min_overlap` distinction
  (inner + left) and the `min_overlap`-not-applied exemption, strand
  same/opposite/missing/both-missing/missing-column/ignored plus stranded
  left reconstruction and stranded touching, metadata preservation, and
  the empty-input matrix. 23 representative cases are also in
  `DIFFERENTIAL_CASES`.
- `tests/parity/test_within_parity.py`: per-engine contract layer
  (39 cases x 2 engines) plus backend-independent units of the shared
  predicate (truth table, missing annotation, the exact inverse relation
  `within(Q, A) == contains(A, Q)` over the shared interval matrix, and
  the "within implies 100% query coverage" property that explains why the
  `min_overlap` exemption is not observable), the explicit
  within-vs-contains directionality/inversion for both engines, the
  within-vs-`min_overlap` distinction, the `min_overlap`-not-applied
  regression (inner + left + left-unmatched), left reconstruction,
  empty-input row counts, and monkeypatched proofs that neither backend
  receives a fraction/containment option (candidate generation is
  ordinary overlap).
- `tests/parity/cases.py` (Task 6A carry-over):
  `min_overlap_within_placeholder_not_applied` encoded the old
  placeholder result for `Q[0,9)`/`A[2,4)`, which is annotation-inside-
  query. It is replaced by `min_overlap_within_mode_not_applied`, which
  pins the same scope rule (SPEC 8.2 is overlap-only) against the now
  normative within semantics: the partial pair passes a 0.5 query
  fraction but is not a within match.
- `tests/test_bedtools_engine.py`, `tests/test_polars_bio_engine.py`: the
  raw-schema and empty-input matrices now include `within` mode.
- UI copy: `streamlit_app/config/settings.py` within description
  corrected from the wrong direction ("Find annotations completely
  within coordinates") to the normative one ("Return annotations that
  fully contain each query interval"), and the stale
  `bedtools_args: {"F": 1.0}` entry was removed (the engines no longer
  forward any fraction flag). README/QUICKSTART wording corrected to the
  same direction. No UI redesign; the mode selector surface is
  unchanged.

### Behavior changes

- `mode="within"` on BOTH engines previously returned the wrong relation:
  bedtools ran `-F 1.0` (a fraction of B = annotation-inside-query, i.e.
  the contains direction) with a forced inner join, and polars-bio
  returned plain unfiltered overlap. It now returns
  query-contained-by-annotation for inner and left, identically on both
  engines.
- The old `-F 1.0` placeholder path and the polars-bio
  `_filter_fraction` no-op were removed.
- `contains`, `min_overlap`, strand, canonicalization, parsing, and
  `closest` behavior are unchanged.

### Test command and baseline (Task 6D)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Focused counts: within contract parity 100 passed (39 cases x 2 engines
+ 22 focused tests), full parity suite 474 passed. Repository-wide:
**684 passed, 0 xfailed, 0 XPASS, 0 failed, 0 skipped** (previous
baseline: 561 passed). Pinned environment: Python 3.12.14, bedtools
2.31.1, pybedtools 0.12.1, polars 1.44.2, polars-bio 0.35.1, pandas
3.0.6.

### Remaining known deviations (Task 6 backlog)

`min_overlap`, `use_strand`, `contains`, and `within` are now normative
and parity-protected. The one documented gap left in Task 6 is `closest`
full semantics (distance definition, tie breaking; the 76-vs-75
backend discrepancy noted in Task 5 remains, as does the native bedtools
`-s` forwarding there). Task 6E (closest) is not started.
(**Superseded by Task 6E — see the Task 6E section below: closest is
now normative, the 76-vs-75 discrepancy is resolved canonically to 75
on both engines, and the native `-s` forwarding is gone.**)

---

## Task 6E — Closest semantics (backend-independent `closest`)

### What was built

`mode="closest"` is now a fully normative, backend-independent operation
(SPEC 8.6, engine-contract section 12). Both engines return the SAME
nearest rows, the SAME canonical integer distance, the SAME tie behavior,
and the SAME ordering for the same input.

- **One shared canonical definition** in
  `streamlit_app/core/annotator.py`:
  - `interval_distance(q_start, q_end, a_start, a_end)` —
    `max(0, a_start - q_end, q_start - a_end)`, exact integer numpy
    arithmetic (no floats; large-coordinate regression pinned).
  - `closest_matches(query, annotation, use_strand)` — per-query
    selection over SAME-CHROMOSOME candidates. Under `use_strand=True`
    the SPEC 8.3 strand predicate is applied to the candidate set BEFORE
    nearest selection (strand-before-nearest; missing/unknown strand is
    not a wildcard; an ineligible nearer annotation cannot suppress a
    farther eligible one). ALL candidates tied at the minimum distance
    are returned. Subtlety found by independent review: the canonical
    missing value is `pd.NA`, and a plain Python membership test
    (`strand not in STRAND_VALUES`) on `pd.NA` raises
    `TypeError: boolean value of NA is ambiguous` instead of being
    False — the annotation bucket loop therefore checks
    `pd.isna(strand) or strand not in STRAND_VALUES`, mirroring the
    NA-safe `Series.isin` membership test on the query side. Pinned by
    `test_pdna_strand_ineligible_not_crash_both_engines`.
  - `canonical_closest(...)` — assembles the canonical result frame:
    query input order, then annotation input order among the ties;
    `has_overlap=True` on every matched row (attachment flag, not an
    overlap predicate); left-mode queries with no eligible candidate
    appear exactly once with `has_overlap=False`, canonical-missing
    `annot_*` fields and canonical-missing distance.
- **Both engines delegate entirely to the shared selection**
  (`BedtoolsEngine` and `PolarsBioEngine` dispatch `mode="closest"` to
  `canonical_closest` before any backend call): no pybedtools
  `BedTool.closest`, no polars-bio `pb.nearest`, no native distance, no
  native strand forwarding, no bedtools sorted-input requirement on the
  closest path. `min_overlap` is still validated at engine construction
  but is deliberately NOT applied in closest mode.
- **Result schema:** one extra column `distance` (nullable `Int64`;
  integer >= 0 on matched rows, `pd.NA` on unmatched left rows). The
  canonicalization layer (`schema.py`) declares/handles the closest
  extra column; the parity comparator validates per-row expected
  distances.
- **Tests:** `tests/parity/test_closest_parity.py` (41 canonical
  ParityCase entries — 36 named scenarios including inner/left splits —
  × 2 engines with explicit expected rows AND explicit expected
  distances, both hand-derived from the SPEC 8.6 formula — never from
  backend output — plus `interval_distance`/`closest_matches` unit tests
  and focused regressions) and closest entries in the differential layer
  (`test_differential_parity.py`, 20 closest cases, comparing the full
  canonical result INCLUDING `distance` directly engine-vs-engine).
  Zero-row closest results are checked for the `distance` column too
  (empty distances tuples are passed through, never collapsed to None).

### Behavior changes

- Closest results are canonical, not backend-native:
  - the Task 5 76-vs-75 discrepancy (bedtools `closest -d` reports
    gap + 1 for separated pairs; polars-bio `nearest.distance` reports
    the gap) is resolved to the canonical gap **75** on BOTH engines;
    a regression test also asserts the native bedtools value (76) is
    produced by the binary and never leaks into AnnotateR results;
  - touching (bookended) pairs are distance **0** on both engines
    (bedtools native would report 1);
  - ALL tied-nearest annotations are returned on both engines (previously
    the backend's arbitrary one-tie selection);
  - row order is query input order on both engines (previously the
    backend's own ordering, and bedtools required genomically sorted
    input — the closest path no longer serializes anything to bedtools).
- `use_strand` now affects closest identically on both engines
  (strand-before-nearest, missing strand never a wildcard) — previously
  native `-s` on bedtools and ignored on polars-bio.
- `how="left"` closest: unmatched query rows carry `distance=pd.NA` and
  canonical-missing annotation fields on both engines (previously each
  backend's own missing convention).
- Empty inputs: empty query → empty result (inner and left); empty
  annotation → empty result (inner) or one unmatched row per query with
  `pd.NA` distance (left), on both engines. No native backend call is
  made for closest at all, so there is no native failure mode to
  swallow; malformed input is rejected by the engines' shared
  pre-dispatch validation (SPEC 9.2).

### Unchanged

- Overlap/min_overlap (Task 6A), strand (Task 6B), contains (Task 6C),
  and within (Task 6D) behavior is unchanged.
- No dependency changes; no new dependencies.
- The public mode is still `mode="closest"`; the UI mode name is
  unchanged (only its help text now describes the canonical semantics).

### Test command and baseline (Task 6E)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Repository-wide: **813 passed, 0 xfailed, 0 XPASS, 0 failed, 0
skipped** (previous main baseline: 684 passed; +129 from the closest
parity fixtures, helper unit tests, regressions, the `pd.NA`-strand
review regression, and the updated engine-level closest tests).
Focused: closest contract parity + helpers + regressions and the
differential layer together 210 passed.
Pinned environment: Python 3.12.14, bedtools 2.31.1, pybedtools 0.12.1,
polars 1.44.2, polars-bio 0.35.1, pandas 3.0.6.

Two independent subagent reviews (spec conformance + test adequacy) ran
on the final tree. The test-adequacy review passed with three minor
findings (all fixed: empty-result `distance`-column hardening, two new
absent-strand-column stranded fixtures, concrete-exception pin for the
malformed-input contract). The spec-conformance review found one
blocker — the `pd.NA` strand crash above — which was fixed and verified
in a second review round; its remaining note (SPEC 8.6 left-mode
wording vs all-ties emission) was resolved by rewording the spec.

### Remaining known deviations (Task 6 backlog)

NONE left in the Task 6 mode backlog: overlap + `min_overlap` (6A),
strand (6B), contains (6C), within (6D), and closest (6E) are all
normative and parity-protected, including closest in the differential
layer.

## Task 8 — Deployment, documentation, and benchmark (2026-09-25)

### What was built

- **Docker / SciLifeLab Serve readiness** (`Dockerfile`, `app.py`,
  `.dockerignore`, `scripts/docker_smoke.sh`, `docker-compose.yml`):
  - `app.py` at the repository root is a thin Serve entry-point shim
    (imports `streamlit_app.streamlit_app` and calls `main()`);
    `streamlit_app/streamlit_app.py` remains the single source of truth.
    Serve requires the main file to be named `app.py` in the image
    working directory.
  - The `Dockerfile` pins `FROM --platform=linux/amd64 python:3.12-slim`
    (the pinned polars-bio 0.35.1 has no linux/aarch64 wheel — re-verified
    against the PyPI JSON on 2026-09-25; see references.md), installs
    bedtools (Debian bookworm: 2.31.1) + curl, drops the former
    `build-essential` toolchain (every pinned dependency has an official
    manylinux wheel — verified by a clean build), and sets
    `ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", ...]`.
  - `.dockerignore` is now tracked (it was previously git-ignored) and
    keeps the image to app + examples + benchmark + smoke script.
  - `scripts/docker_smoke.sh` verifies inside the built image: bedtools
    on PATH at 2.31.x; core imports; a canonical smoke annotation on the
    bundled examples with BOTH engines (overlap + closest) passing the
    strict comparator; Streamlit startup from `app.py`;
    `/_stcore/health` green; UI HTTP 200.
- **Strict comparator moved into the package**
  (`streamlit_app/core/comparison.py`): `assert_canonical_equal` and its
  helpers now live in the application package so the production image can
  run the same parity gate inside the container without shipping
  `tests/`. `tests/parity/comparator.py` re-exports everything; all test
  imports are unchanged. The move is verbatim (no semantic change).
- **Backend benchmark** (`benchmarks/benchmark_engines.py`,
  `docs/benchmark.md`): deterministic synthetic workloads
  (sparse/dense/mixed/duplicates/stranded × overlap/contains/within/closest
  × small/medium/large) measuring the real AnnotateR execution path
  (`engine.intersect` + `canonicalize_annotation_result`). Every scenario
  passes the strict comparator BEFORE its timings are accepted; a parity
  failure aborts the benchmark with a non-zero exit. `closest` is measured
  like the others but is known to be the shared canonical path (Tasks
  6A–6E) — the numbers are reported as such, not hidden. Peak-RSS probes
  run in isolated subprocesses (`--measure-memory` / `--memory-only`).
- **CI** (`.github/workflows/python-tests.yml`): new `docker-smoke` job
  (ubuntu-latest, native amd64 build): `docker build --platform
  linux/amd64`, `scripts/docker_smoke.sh`, and `benchmark_engines.py
  --quick` in the container. The full benchmark is deliberately NOT a CI
  gate (performance numbers are reporting data, not pass/fail criteria).
- **Documentation**: new `docs/deployment.md` (Serve setup, build/test,
  configuration, verification, failure modes), new `docs/benchmark.md`
  (methodology + results + interpretation), refreshed README/QUICKSTART,
  `docs/references.md` updated with the exact current Serve pages and the
  PyPI wheel-availability evidence; `CITATION.cff` rewritten (the previous
  one contained an unrelated project's title and a Zenodo DOI that does
  not point to AnnotateR — removed).

### Key decisions

- **Synthetic coordinate cap (2³¹−1).** The bedtools backend goes through
  pybedtools, whose Cython iterator packs positions into a 32-bit CHRPOS
  field; coordinates >= 2³¹ raise `OverflowError`. This is a hard input
  limit of the BedtoolsEngine as implemented (discovered empirically when
  the first benchmark run generated a 5 Gb synthetic chromosome).
  Benchmark geometry adapts its packing gap to stay under the cap
  (`_fit_gap`); every natural chromosome is far below it. Documented in
  benchmark docs, references.md, and Limitations.
- **Benchmark scope.** Timings cover engine call + canonicalization only;
  parsing is backend-independent (SPEC 4.1) and is recorded separately as
  reference data, never inside per-backend timings. No Streamlit
  rendering is included.
- **UI wording stays neutral.** The benchmark measures workload-dependent
  differences; it does not support a blanket "high-performance" label for
  either backend, so the Task 7 neutral wording is kept.

### Release / versioning audit (current state, 2026-09-25)

- No git tags and no GitHub Releases exist.
- Versions are inconsistent: `pyproject.toml` = 0.1.0,
  `streamlit_app/config/settings.py` `Settings.VERSION` = 1.0.0,
  `CITATION.cff` previously 0.1.1 (now omits `version` — no formal
  release exists to cite).
- **License discrepancy (NEEDS A DECISION before release):** `LICENSE`
  is BSD-3-Clause (Copyright (c) 2025, Jyotirmoy Das) while `README.md`
  (badge + text) and the app footer say "GNU GPLv3". `CITATION.cff`
  omits the license field until this is resolved. This is a legal
  decision outside agent authority; flag to the maintainers.
- Recommended release step AFTER manual GUI acceptance: choose one
  license and make LICENSE/README/footer agree; pick a semantic version
  (suggest 1.0.0 once accepted); tag it; create the GitHub Release;
  publish the Docker image with that tag; then add the version/DOI to
  `CITATION.cff` and `Settings.VERSION`.

### Dependency-definition audit (Task 8)

The dependency definitions agree everywhere (checked 2026-09-25):

- `pyproject.toml` dependencies == `requirements.txt` (8 exact pins);
- `pyproject.toml` `[project.optional-dependencies].dev` ==
  `requirements-dev.txt` extra pins (pytest, pytest-cov, black, ruff);
- `uv lock --check` passes (uv.lock is in sync with pyproject.toml);
- CI installs `requirements-dev.txt`; the Docker image installs
  `requirements.txt`; README/QUICKSTART use the same files.
- No dependency changes in Task 8.

### Repository hygiene notes (Task 8 inspection)

- Legacy artifacts still tracked in git: `app/` (legacy Shiny app),
  `renv.lock`, `.Rprofile`, `docs/polars-bio_manual.pdf`. They are
  excluded from the Docker image via `.dockerignore`, but removal is a
  separate decision (out of Task 8 scope: no unrelated cleanup). The
  QUICKSTART previously linked a non-existent
  `.gemini/.../development_roadmap.md`; the link was replaced with the
  actual docs.
- `.pi/` agent artifacts and `benchmarks/results/` are git-ignored.

### Test command and baseline (Task 8)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Baseline at task start (clean main, commit aec841d):
**853 passed, 0 failed, 0 skipped** (28.34 s).

Task-8 focused re-runs (comparator move):
`tests/parity tests/test_streamlit_app_ui.py` → **623 passed**.

Full suite at task end: `.venv/bin/python -m pytest -q` → **853 passed in
24.51s** (0 failed, 0 skipped) — identical to the pre-task baseline
(853).

Full benchmark (local arm64, M1 Pro, 32 GB; commit aec841d; wall ≈ 115
min): 51/51 scenario-op cells (102 engine rows) parity-verified; results
in `docs/benchmark.md`. Notable honest findings: (a) polars-bio is faster
on all pair-producing operations at every tier (~3–10× small, ~8–15×
medium/large); (b) `closest` tracks within ~10% on both engines
(confirms the shared canonical path, Tasks 6A–6E) and is the dominant
cost at large scale (~2–4 min per engine at 100k×1M — shared-path
scale limitation); (c) bedtools cells show higher variance
(subprocess effects).

Docker verification (local, Apple M1 Pro, QEMU-emulated linux/amd64):

- `docker build --platform linux/amd64 -t annotater:dev .` → success
  (BuildKit lint warning about a constant `FROM --platform` worked
  around with `ARG PLATFORM=linux/amd64`).
- `docker run --rm --entrypoint bash annotater:dev
  /app/scripts/docker_smoke.sh` → **SMOKE PASS (exit 0)**:
  bedtools v2.31.1 on PATH; all core imports; canonical smoke
  annotation with both engines (6 rows each) strictly equal
  (`assert_canonical_equal`); `closest` smoke strictly equal;
  Streamlit started from the Serve entry point `app.py`;
  `/_stcore/health` OK; UI HTTP 200.
- Smoke fixes made during verification (documented here because they
  are easy to reintroduce): (a) `bedtools --version` prints
  "bedtools v2.31.1", so the script now extracts the numeric version
  instead of pattern-matching the raw string; (b) GFF3 example files
  parse with `fmt="gff"` (the GFF/GFF3 parser key; `"gff3"` is the
  custom-file branch and raises by design); (c) the Streamlit health
  window is 180s to cover QEMU-emulated first-import latency (native
  startup is ~10s);
- **Entry-point gotcha (CI + docs fixed):** the image ENTRYPOINT is
  the Streamlit server (Serve requirement), so bare
  `docker run image bash /app/scripts/docker_smoke.sh` appends the
  args to the entry point and starts the web server instead of the
  smoke (it then runs forever). Smoke and benchmark invocations use
  `--entrypoint bash` / `--entrypoint python`; CI workflow and
  docs/deployment.md carry this with a comment.
- `docker run --rm --entrypoint python annotater:dev
  /app/benchmarks/benchmark_engines.py --quick` → **exit 0**, both
  engines parity `verified` (this is CI's benchmark smoke step).

## Release-prep 0.1.0 housekeeping (post-Task 8, pre-GUI-acceptance)

Non-scientific pre-release pass on branch `release-prep-0.1.0`. No
genomic semantics, engine behavior, parsing, normalization, benchmark,
or Streamlit layout changes.

### Version alignment (done)

- Before: `pyproject.toml` = `0.1.0`; `streamlit_app/__init__.py`
  `__version__` = `1.0.0`; `streamlit_app/config/settings.py`
  `Settings.VERSION` = `1.0.0` (shown in the app footer).
- After: `Settings.VERSION` = `0.1.0` is the single source of truth;
  `streamlit_app.__version__` now derives from `Settings.VERSION`.
  Aligned with `pyproject.toml` (`0.1.0`).
- No git tag, no GitHub Release (created only after manual GUI
  acceptance, per `docs/release-plan-0.1.0.md`).
- `CITATION.cff` keeps no `version` / `date-released` / DOI /
  publication: none exist to claim; they are added during the release
  step (noted in the file).
- The legacy R app footer (`app/app.R`) already says "Version 0.1.0";
  it is historical and untouched.
- `docs/development_roadmap.md.resolved` historically *suggested*
  1.0.0; it is a resolved historical record and was not altered.

### License provenance audit — RESOLVED: maintainers selected BSD-3-Clause

License normalization was STOPPED in the first pass per the resolution
policy: provenance is ambiguous/conflicting. Evidence (historical
record, kept intact for transparency):

| Artifact | First relevant commit | License shown | Notes |
|---|---|---|---|
| Root `LICENSE` | `2fc8261` (2024-05-09, "Initial commit") | GPLv3 (full text) | Initial commit is only `.gitignore` (R template), 2-line README ("# annotator"), and the GPL text; no project code existed |
| Root `LICENSE` (replacement) | `a5fc572` (2025-06-27, "first devel version") | BSD-3-Clause (Copyright (c) 2025, Jyotirmoy Das) | GPL text replaced by BSD-3-Clause inside a bulk template-import commit that also added `CITATION.cff` titled "Image-Processing-MATLAB" with an external Zenodo DOI (10.5281/zenodo.11104350, date-released 2024-05-02), `CODEOWNERS.md`, `CODE_OF_CONDUCT.md`, `Dockerfile`. No commit message or other record mentions a license decision |
| `CITATION.cff` (original) | `a5fc572` (2025-06-27) | (no license field) | Belonged to an unrelated project (MATLAB image processing); rewritten in `867164e` (Task 8) for AnnotateR, license field omitted pending this decision |
| `app/annotater.R` | `d0aca6b` (2025-06-27, "Updated and launched on serve") | "GNU3 open license" (author header) | License statement in the project's own original R code |
| `app/app.R` | `d0aca6b` (2025-06-27) | "License: GNU GPLv3" (author header) | License statement in the project's own original R code; its footer also claims GPLv3 ("Version 0.1.0") |
| `README.md` (badge + License section) | `524c493` (2025-12-05, Streamlit app PR) | GPLv3 | Added after `LICENSE` was already BSD; badge/section link to the BSD `LICENSE` file, i.e. internally inconsistent from the start |
| Streamlit footer (`streamlit_app/streamlit_app.py`) | `524c493` (2025-12-05) | "License: GNU GPLv3" | Copied from the legacy R app footer |

Interpretation: no commit message, issue, or document records a
deliberate license (re-)decision. The oldest GPLv3 LICENSE predates any
project code and plausibly comes from the same pyrevo template that
later supplied the unrelated "Image-Processing-MATLAB" CITATION.cff; the
BSD-3-Clause LICENSE likewise arrived in a template-import commit with
no stated decision. The only license statements attached to the
project's own code (the R app, 2025-06-27) say GPLv3. Both readings
("stale template GPL" vs "stale template BSD, deliberate code headers")
remain possible — the decision is made to the maintainers.

Consequently, in this pass:

- no license declaration was changed (root `LICENSE`, README badge and
  License section, app footer, `pyproject.toml`, `CITATION.cff` all
  untouched in their license content);
- `CITATION.cff`'s omission note was updated to point at this audit;
- the README badge and footer retained GPLv3 wording until the
  maintainers decide; the Task 8 "release audit" recommendation stood.

#### License decision (maintainers, recorded 2026-09-28)

**RESOLVED — the maintainers selected BSD-3-Clause as the canonical
license for the current AnnotateR project/release**, after reviewing the
conflicting historical metadata in the table above. Both project
maintainers/contributors authorized the decision. The audit findings
above are historical: they explain why the decision was required, not
what the current license is.

Follow-up edits made under this decision (commit "docs: resolve
AnnotateR license as BSD-3-Clause"):

- root `LICENSE` kept (standard BSD-3-Clause text); copyright
  attribution updated to name both confirmed project authors
  ("Copyright (c) 2025, Jyotirmoy Das & Massimiliano Volpe") —
  conservative attribution, no ownership percentages or institutional
  ownership claimed;
- README license badge and License section: GPLv3 → BSD-3-Clause;
- Streamlit footer: "License: GNU GPLv3" → "License: BSD-3-Clause";
- `pyproject.toml`: added `license = { text = "BSD-3-Clause" }` (PEP 621);
- `CITATION.cff`: `license: BSD-3-Clause` added; `version` /
  `date-released` / DOI / publication still absent (no formal release
  exists yet; added during the v0.1.0 release step);
- historical GPL statements in the legacy R files (`app/annotater.R`,
  `app/app.R`) are retained unchanged as historical header text (see
  docs/legacy.md); the legacy implementation remains excluded from the
  production image.

### Legacy R implementation (retain / document / exclude / defer)

Audited `.Rprofile`, `app/annotater.R`, `app/app.R`, `app/www/*`,
`renv.lock`, `docs/polars-bio_manual.pdf`: all are historical/reference
artifacts, none is a runtime dependency of the current product, none is
referenced by current code except `docs/references.md` describing the
PDF. Inventory + disposition recorded in the new
[docs/legacy.md](legacy.md); a short note added at `app/README.md`.
Nothing deleted or moved. Production image exclusion re-verified:
`Dockerfile` white-lists app code only; `.dockerignore` excludes
`app/`, `renv.lock`, `renv/`.

`docs/polars-bio_manual.pdf`: downloaded copy of upstream Polars-Bio
docs; `docs/references.md` already states the online documentation takes
preference. It IS referenced (by references.md), so per the pass rules
it is retained for now and flagged as a removal candidate after GUI
acceptance.

### Changelog

The repository maintains no changelog (per-task records live in
`docs/implementation-notes.md` and `PLAN.md`). No changelog system was
created; the first-release summary belongs in the GitHub Release
(see `docs/release-plan-0.1.0.md` step 6).

### Hygiene

Tracked-artifact check: no `.pi/`, `__pycache__/`, `.DS_Store`,
`.pytest_cache/`, or `benchmarks/results/` files are tracked; all are
git-ignored. Untracked local-only items left untouched (reported):
`annotater-review_PR.zip` (review export, `*.zip` ignored), `.venv/`,
`__pycache__/`, `.pytest_cache/`, `.DS_Store`. No secrets/credentials
found in tracked content. No obsolete tracked ZIPs or test outputs.

## Documentation site build (Zensical Classic)

This note is developer-facing and is excluded from the published site
(`exclude_docs` in `mkdocs.yml`).

### Architecture

The `build` job of `.github/workflows/docs.yaml` is the production
documentation build. In order, it:

1. installs the pinned Zensical (`docs/requirements-zensical.txt`,
   `zensical==0.0.73`), the Material for MkDocs reference
   (`docs/requirements-docs.txt`) and Playwright
   (`docs/requirements-docs-browser.txt`), then Chromium;
2. builds a **Material reference site** into `$RUNNER_TEMP` (verification
   only; it is never uploaded or published);
3. builds the site with `zensical build --clean --strict` into `site/`
   (`theme.variant: classic` in `mkdocs.yml`);
4. runs `scripts/check_docs_site.py --self-test` on `site/` against the
   reference: exact 46-page inventory, internal links and anchors, content
   anchors, article text, navigation structure and order, canonical URLs,
   sitemap URLs, the Classic stylesheet, and a populated `search.json`;
5. runs `scripts/check_docs_search.py --self-test`: real Chromium over HTTP
   on desktop (mouse and keyboard) and mobile, searching a known term,
   opening a result;
6. only then uploads `site/` with `actions/upload-pages-artifact`.

The `--self-test` options apply deliberate breakages to isolated copies and
fail the job if any of them goes undetected. A missing Playwright or Chromium
fails the job (exit status 2). The `deploy` job is unchanged: it needs `build`
and runs only for pushes with `DOCS_PUBLISH == 'true'`. The former
experimental `docs-zensical` job and its `zensical-site` review artifact were
folded into `build` to avoid building twice.

### Intentional differences from Material for MkDocs

Not byte-identical; the structural check compares what readers and links
depend on, not the markup.

- Search index path: `/search.json` (was `/search/search_index.json`).
- `sitemap.xml.gz` is no longer generated (`sitemap.xml` is, with the same URLs).
- Search is a dialog (Ctrl/Cmd+K), results are more granular, and the search
  interface is English-only (Zensical does not localize it yet).
- The table-of-contents heading reads "On this page" instead of "Table of
  contents".
- Fenced code blocks nested in 3-space-indented list items render as real code
  blocks (Material rendered them as inline code with the language word leaked
  into the text); the checker tolerates exactly that difference on two pages.
- Zensical is a `0.0.x` release; pin it and bump deliberately.
- `file://` is not supported for search (the `offline` plugin would rewrite
  every URL to `*.html`); preview with `python -m http.server -d site`.

### Rollback

Use a reviewed pull request (or an explicitly authorised recovery action);
no documentation content changes are needed:

1. In `.github/workflows/docs.yaml` restore the previous `build` job: install
   `-r docs/requirements-docs.txt`, run `mkdocs build --strict`, upload `site`
   with `actions/upload-pages-artifact@v3`. Leave `deploy` untouched.
2. Optionally remove `docs/requirements-zensical.txt`,
   `docs/requirements-docs-browser.txt` and the two checker scripts.
   `theme.variant: classic` may stay: Material ignores it.
3. Material's `requirements-docs.txt` stays pinned (`mkdocs-material>=9.5,<10`)
   for exactly this purpose; Material for MkDocs reaches end of life on
   2027-05-05.

The previous behaviour is also recoverable by reverting the cutover commit.
