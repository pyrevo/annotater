#!/bin/sh
# In-container smoke test for the AnnotateR production image scientific core.
#
# Verifies, in order:
#   1. bedtools is on PATH at the expected version;
#   2. core imports succeed (app package + both engines + canonical adapter);
#   3. a canonical smoke annotation completes with BOTH engines on the
#      bundled example data, and the two canonical results are strictly
#      equal (the same strict comparator the parity suite uses);
#   4. exact, hand-computed scientific assertions on tiny inline fixtures.
#
# This script is deliberately server-agnostic: it checks the scientific
# runtime only.  The served FastAPI/React application (startup, routes,
# sessions, export) is covered separately by scripts/docker_smoke_api.sh, and
# the network-disabled scientific runtime by scripts/offline_smoke.py.
#
# Exits non-zero on the first failure.  Used by CI (docker job) and by
# local deployment verification (see docs/deployment.md).
set -eu

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

# --- 1. bedtools ----------------------------------------------------------
command -v bedtools >/dev/null 2>&1 || fail "bedtools not found on PATH"
# `bedtools --version` prints e.g. "bedtools v2.31.1"; extract the number.
BEDTOOLS_VERSION_RAW="$(bedtools --version 2>/dev/null | head -n1)"
BEDTOOLS_VERSION="$(printf '%s\n' "$BEDTOOLS_VERSION_RAW" | sed -n 's/.*v\([0-9][0-9.]*\).*/\1/p')"
echo "bedtools: ${BEDTOOLS_VERSION_RAW}"
[ -n "$BEDTOOLS_VERSION" ] || fail "could not parse bedtools version from: ${BEDTOOLS_VERSION_RAW}"
case "$BEDTOOLS_VERSION" in
    2.31.*) echo "bedtools version OK (2.31.x)" ;;
    *) fail "unexpected bedtools version: ${BEDTOOLS_VERSION}" ;;
esac

# --- 2+3. imports, engines, canonical smoke annotation --------------------
python - <<'EOF'
import sys

import pandas as pd

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.comparison import assert_canonical_equal
from streamlit_app.core.normalization import parse_and_normalize
from streamlit_app.core.schema import canonicalize_annotation_result

coords = parse_and_normalize("/app/data/examples/example_coordinates.bed", fmt="bed")
annot = parse_and_normalize("/app/data/examples/example_annotations.gff3", fmt="gff")
assert len(coords) > 0 and len(annot) > 0, "example inputs must be non-empty"

results = {}
for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
    engine = cls(use_strand=False, mode="overlap")
    raw = engine.intersect(coords, annot, how="inner")
    results[key] = canonicalize_annotation_result(raw, coords, annot)
    print(f"{key}: {len(results[key])} canonical rows")

# Strict parity gate: exact columns, row count, row order, cells, dtypes.
assert_canonical_equal(results["bedtools"], results["polars-bio"],
                       label="docker-smoke")
print("canonical smoke annotation: parity verified")

# closest smoke: the shared canonical path must also work in the container
for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
    engine = cls(use_strand=False, mode="closest")
    raw = engine.intersect(coords, annot, how="inner")
    results[key + "_closest"] = canonicalize_annotation_result(
        raw, coords, annot, extra_columns=("distance",))
assert_canonical_equal(results["bedtools_closest"], results["polars-bio_closest"],
                       label="docker-smoke-closest")
print("closest smoke annotation: parity verified")

# Exact, hand-computed scientific assertions on a tiny inline fixture
# (0-based half-open): the bundled-data check above proves parity, this
# proves correctness on both engines.
tiny_q = pd.DataFrame({"chr": ["chr1", "chr1"], "start": [10, 100],
                       "end": [20, 110], "name": ["q_ovl", "q_gap"]})
tiny_a = pd.DataFrame({"chr": ["chr1", "chr1", "chr1"],
                       "start": [15, 20, 125], "end": [25, 30, 140],
                       "feature": ["a_ovl", "a_touch", "a_far"]})
for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
    got = canonicalize_annotation_result(
        cls(mode="overlap").intersect(tiny_q, tiny_a, how="inner"), tiny_q, tiny_a)
    # overlap: [10,20) x [15,25) matches; [10,20) x [20,30) only touches
    assert got["coord_name"].tolist() == ["q_ovl"], (key, got)
    assert got["annot_feature"].tolist() == ["a_ovl"], (key, got)
    assert got["annot_start"].tolist() == [15], (key, got)
    got = canonicalize_annotation_result(
        cls(mode="closest").intersect(tiny_q, tiny_a, how="inner"),
        tiny_q, tiny_a, extra_columns=("distance",))
    # closest: q_ovl -> a_ovl (overlap, 0) AND a_touch (touching, 0): a tie,
    # both returned in annotation order; q_gap [100,110) -> a_far [125,140):
    # gap 125 - 110 = 15
    assert got["annot_feature"].tolist() == ["a_ovl", "a_touch", "a_far"], (key, got)
    assert got["distance"].tolist() == [0, 0, 15], (key, got)
print("exact scientific smoke assertions: verified on both engines")
EOF

echo "SMOKE PASS"