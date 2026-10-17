#!/usr/bin/env python
"""Network-disabled scientific-runtime smoke test (Task 14.6).

Run inside the production image with the container network turned off:

    docker run --rm --network none --entrypoint python \
        annotater:ci /app/scripts/offline_smoke.py

It proves the scientific runtime is self-contained: the bundled chromosome
catalog loads, a custom chromosome mapping loads, Bedtools and Polars-Bio
annotation (with strict canonical parity) both complete, and VCF export
works -- all with no external chromosome data (UCSC/Ensembl) and no
network. Network access is additionally hard-blocked at the socket layer so
any accidental fetch fails the script instead of silently succeeding.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

# The production image ships the package as source under /app (it is not
# installed), so make the repository root importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class _NetworkBlocked(RuntimeError):
    """Raised if the offline smoke test attempts any network connection."""


def _blocked(*_args, **_kwargs):
    raise _NetworkBlocked("network access attempted in the offline smoke test")


# Hard network block: any outbound connection raises instead of resolving.
socket.socket.connect = _blocked  # type: ignore[assignment]
socket.socket.connect_ex = _blocked  # type: ignore[assignment]
socket.create_connection = _blocked  # type: ignore[assignment]

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine  # noqa: E402
from streamlit_app.core.chrom_registry import (  # noqa: E402
    CUSTOM_HEADER,
    load_catalog,
    load_custom_registry,
)
from streamlit_app.core.comparison import assert_canonical_equal  # noqa: E402
from streamlit_app.core.normalization import parse_and_normalize  # noqa: E402
from streamlit_app.core.schema import canonicalize_annotation_result  # noqa: E402
from streamlit_app.core.vcf_export import build_annotated_vcf  # noqa: E402

_here = Path(__file__).resolve()
_candidates = [_here.parent.parent / "data" / "examples", Path("/app/data/examples")]
EXAMPLES = next((p for p in _candidates if p.is_dir()), _candidates[0])


def main() -> int:
    # 1. Bundled chromosome catalog loads with no network.
    catalog = load_catalog()
    assert len(catalog) > 0, "bundled assembly catalog is empty"
    print(f"chromosome catalog: {len(catalog)} assemblies (offline)")

    # 2. Custom chromosome mapping loads with no network.
    # Each row maps one sequence's names across authorities (the ``assembly``
    # column is that sequence's assembly-specific name, not the assembly id).
    header = "\t".join(CUSTOM_HEADER)
    custom = (
        f"{header}\n"
        "1\tchr1\t1\tCM000663.2\tNC_000001.11\n"
        "2\tchr2\t2\tCM000664.1\tNC_000002.12\n"
    ).encode()
    registry = load_custom_registry(custom)
    assert registry is not None
    print("custom chromosome mapping: loaded (offline)")

    # 3 + 4. Both engines annotate the bundled examples, strict canonical parity.
    coords = parse_and_normalize(str(EXAMPLES / "example_coordinates.bed"), fmt="bed")
    annot = parse_and_normalize(str(EXAMPLES / "example_annotations.gff3"), fmt="gff")
    results = {}
    for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
        raw = cls(use_strand=False, mode="overlap").intersect(coords, annot, how="inner")
        results[key] = canonicalize_annotation_result(raw, coords, annot)
        print(f"{key}: {len(results[key])} canonical rows (offline)")
    assert_canonical_equal(results["bedtools"], results["polars-bio"], label="offline-smoke")

    # 5. VCF export from a bundled VCF query, offline.
    vcf_query = parse_and_normalize(str(EXAMPLES / "example_closest_variants.vcf"), fmt="vcf")
    vcf_annot = parse_and_normalize(str(EXAMPLES / "example_closest_annotations.gff3"), fmt="gff")
    raw = BedtoolsEngine(use_strand=False, mode="overlap").intersect(vcf_query, vcf_annot, how="inner")
    result = canonicalize_annotation_result(raw, vcf_query, vcf_annot)
    vcf_text = build_annotated_vcf(
        result, original_header_lines=vcf_query.attrs.get("vcf_header_lines")
    )
    assert vcf_text.startswith("##fileformat=VCF"), "VCF export did not produce a VCF header"
    print("VCF export: offline")

    print("OFFLINE SMOKE PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _NetworkBlocked as exc:
        print(f"OFFLINE SMOKE FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
