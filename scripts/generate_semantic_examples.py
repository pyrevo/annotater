#!/usr/bin/env python3
"""Render the factual interval-example blocks in the docs from fixtures.

Source of truth: tests/fixtures/semantic_examples.json (declarative).
The renderer never computes scientific results; it only displays the
expected facts declared in the fixture. Interval facts are verified against
the independent oracle by tests/oracle/test_semantic_examples_oracle.py;
chromosome-naming facts by tests/oracle/test_chromosome_semantic_examples.py
(upstream data) and tests/test_chromosome_semantic_examples.py (the real
normalization).

    python scripts/generate_semantic_examples.py          regenerate blocks
    python scripts/generate_semantic_examples.py --check  fail if docs are stale

Only text between these markers is ever replaced:

    <!-- BEGIN GENERATED: <example name> -->
    <!-- END GENERATED: <example name> -->
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "semantic_examples.json"
DOCS_DIR = ROOT / "docs"

CELL = 3  # characters per genomic base in the occupancy diagram

BEGIN_RE = re.compile(r"^<!-- BEGIN GENERATED: ([A-Za-z0-9_]+) -->$")
END_RE = re.compile(r"^<!-- END GENERATED: ([A-Za-z0-9_]+) -->$")

# Rendering contract -------------------------------------------------------
#
# MAX_WIDTH is the widest line a generated block may have (the docs content
# column fits ~90 monospace characters without horizontal scrolling).
MAX_WIDTH = 90

LEGEND = ("cells are genomic bases: # = included base, . = outside interval")

# Declared expected facts and their value types.
FACT_TYPES = {
    "overlap": bool,
    "overlap_length": int,
    "query_length": int,
    "overlap_fraction": float,
    "min_overlap_pass": bool,
    "contains": bool,
    "within": bool,
    "stranded_match": bool,
    "closest_distance": int,
    "closest_ties": list,
    "candidate_distances": dict,
}

# Summary tokens: the declared fact keys above plus tokens displayed from
# other declared fixture fields (threshold <- min_overlap, strand_matching
# <- use_strand, query_strand / annotation_strand <- interval strands).
DERIVED_TOKENS = {"threshold", "strand_matching", "query_strand",
                  "annotation_strand"}

_OVERLAP_LIKE = ["overlap", "overlap_length", "query_length", "overlap_fraction"]
_CLOSEST = ["overlap", "overlap_length", "closest_distance"]
_CONTAINMENT = ["overlap", "overlap_length", "contains", "within"]

# kind -> (summary order, required tokens, annotation count rule).
# The order IS the teaching order; JSON key order never matters. A fixture
# must declare every required one (the renderer never infers a missing
# scientific value). Extra valid facts are allowed and simply not displayed;
# the oracle still verifies them.
KINDS = {
    "overlap": (_OVERLAP_LIKE, _OVERLAP_LIKE, "one"),
    "one_base_overlap": (_OVERLAP_LIKE, _OVERLAP_LIKE, "one"),
    "touching": (_CLOSEST, _CLOSEST, "one"),
    "closest": (_CLOSEST, _CLOSEST, "one"),
    "closest_tie": (
        ["candidate_distances", "closest_distance", "closest_ties"],
        ["candidate_distances", "closest_distance", "closest_ties"], "many"),
    "contains": (_CONTAINMENT, _CONTAINMENT, "one"),
    "within": (_CONTAINMENT, _CONTAINMENT, "one"),
    "min_overlap": (
        ["overlap", "query_length", "overlap_length", "overlap_fraction",
         "threshold", "min_overlap_pass"],
        ["query_length", "overlap_length", "overlap_fraction", "threshold",
         "min_overlap_pass"], "one"),
    "strand": (
        ["overlap", "strand_matching", "query_strand", "annotation_strand",
         "stranded_match"],
        ["strand_matching", "query_strand", "annotation_strand",
         "stranded_match"], "one"),
}


# Chromosome-naming examples (kind "chromosome_naming") declare one genome
# assembly, one target naming, the identifiers fed to normalization and, per
# identifier, the expected outcome and output. They are verified against
# pinned upstream data and the real normalization, never by this renderer.
CHROMOSOME_KIND = "chromosome_naming"
SOURCES_FILE = (ROOT / "streamlit_app" / "core" / "chrom_registry"
                / "sources.json")
# Target naming -> label (the wording of the app's "Chromosome naming" menu).
TARGET_LABELS = {
    "ucsc": "UCSC names",
    "ensembl": "Ensembl names",
    "refseq": "NCBI RefSeq accessions",
    "genbank": "GenBank accessions",
    "assembly": "Assembly names",
}
# Target naming -> short noun used inside a result phrase.
TARGET_SHORT = {"ucsc": "UCSC", "ensembl": "Ensembl", "refseq": "RefSeq",
                "genbank": "GenBank", "assembly": "assembly"}
# Per-identifier outcome vocabulary. "unknown" (identifier not found in the
# selected assembly) and "no_alias_for_target" (sequence found, no verified
# name in the target naming) are deliberately different outcomes.
OUTCOMES = ("renamed", "unchanged", "unknown", "no_alias_for_target")
ROW_COLUMNS = ("chr", "start", "end", "strand", "name")
CHROMOSOME_FACTS = {"outcomes", "outputs", "distinct_sequences", "collapses",
                    "recognized_in_other_assembly", "rows_after"}


def known_assemblies(path=SOURCES_FILE):
    return [a["assembly_id"] for a in json.loads(Path(path).read_text())["assemblies"]]


class FixtureError(ValueError):
    pass


class MarkerError(ValueError):
    pass


class RenderError(ValueError):
    pass


# --------------------------------------------------------------------------
# Fixture loading / schema
# --------------------------------------------------------------------------


def _check_interval(where, iv, *, annotation):
    if not isinstance(iv, dict):
        raise FixtureError(f"{where}: interval must be an object")
    allowed = {"chr", "start", "end", "strand"} | ({"id"} if annotation else set())
    required = {"chr", "start", "end"} | ({"id"} if annotation else set())
    missing = required - iv.keys()
    if missing:
        raise FixtureError(f"{where}: missing {sorted(missing)}")
    extra = iv.keys() - allowed
    if extra:
        raise FixtureError(f"{where}: unexpected keys {sorted(extra)}")
    for key in ("start", "end"):
        if type(iv[key]) is not int:
            raise FixtureError(f"{where}: {key} must be an integer")
    if iv["start"] < 0 or iv["start"] >= iv["end"]:
        raise FixtureError(f"{where}: need 0 <= start < end (half-open)")
    if not isinstance(iv["chr"], str) or not iv["chr"]:
        raise FixtureError(f"{where}: chr must be a non-empty string")
    if "strand" in iv and iv["strand"] not in ("+", "-"):
        raise FixtureError(f"{where}: strand must be '+' or '-' (omit if missing)")


def _token_present(token, ex):
    if token == "threshold":
        return "min_overlap" in ex
    if token == "strand_matching":
        return "use_strand" in ex
    if token in DERIVED_TOKENS:
        return True
    return token in ex["expected"]


def _check_kind(where, ex, exp, n_annotations):
    order, required, count = KINDS[ex["kind"]]
    if count == "one" and n_annotations != 1:
        raise FixtureError(f"{where}: kind {ex['kind']!r} needs exactly one "
                           "annotation")
    if count == "many" and n_annotations < 2:
        raise FixtureError(f"{where}: kind {ex['kind']!r} needs 2+ annotations")
    missing = [tok for tok in required if not _token_present(tok, ex)]
    if missing:
        raise FixtureError(f"{where}: kind {ex['kind']!r} requires "
                           f"{missing}")


def _check_rows(where, key, rows):
    if not isinstance(rows, list) or not rows:
        raise FixtureError(f"{where}: {key} must be a non-empty list")
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(ROW_COLUMNS):
            raise FixtureError(f"{where}: each {key} row needs exactly "
                               f"{list(ROW_COLUMNS)}")
        for col in ("start", "end"):
            if type(row[col]) is not int or row[col] < 0:
                raise FixtureError(f"{where}: {key} {col} must be a "
                                   "non-negative integer")
        if row["start"] >= row["end"]:
            raise FixtureError(f"{where}: {key} needs start < end")
        if row["strand"] not in ("+", "-"):
            raise FixtureError(f"{where}: {key} strand must be '+' or '-'")
        for col in ("chr", "name"):
            if not isinstance(row[col], str) or not row[col]:
                raise FixtureError(f"{where}: {key} {col} must be a "
                                   "non-empty string")


def _validate_chromosome_example(where, ex):
    """Schema and internal consistency only; scientific truth is tested."""
    extra = ex.keys() - {"name", "kind", "assembly", "target", "inputs",
                         "rows", "expected"}
    if extra:
        raise FixtureError(f"{where}: unexpected keys {sorted(extra)}")
    if ex.get("assembly") not in known_assemblies():
        raise FixtureError(f"{where}: assembly must be one of "
                           f"{known_assemblies()}")
    if ex.get("target") not in TARGET_LABELS:
        raise FixtureError(f"{where}: target must be one of "
                           f"{sorted(TARGET_LABELS)}")
    inputs = ex.get("inputs")
    if (not isinstance(inputs, list) or not inputs
            or any(not isinstance(i, str) or not i for i in inputs)
            or len(set(inputs)) != len(inputs)):
        raise FixtureError(f"{where}: inputs must be a non-empty list of "
                           "distinct non-empty strings")
    exp = ex.get("expected")
    if not isinstance(exp, dict):
        raise FixtureError(f"{where}: 'expected' must be an object")
    unknown_facts = exp.keys() - CHROMOSOME_FACTS
    if unknown_facts:
        raise FixtureError(f"{where}: unknown expected fact "
                           f"{sorted(unknown_facts)}")
    for key in ("outcomes", "outputs"):
        value = exp.get(key)
        if not isinstance(value, dict) or set(value) != set(inputs):
            raise FixtureError(f"{where}: expected {key!r} needs exactly "
                               "one entry per input")
    for ident in inputs:
        outcome, output = exp["outcomes"][ident], exp["outputs"][ident]
        if outcome not in OUTCOMES:
            raise FixtureError(f"{where}: outcome of {ident!r} must be one "
                               f"of {list(OUTCOMES)}")
        if not isinstance(output, str) or not output:
            raise FixtureError(f"{where}: output of {ident!r} must be a "
                               "non-empty string")
        if (outcome == "renamed") != (output != ident):
            raise FixtureError(f"{where}: {ident!r} output must differ from "
                               "the input exactly when it is 'renamed'")
    for group in exp.get("distinct_sequences", []):
        if (not isinstance(group, list) or len(group) < 2
                or not set(group) <= set(inputs)):
            raise FixtureError(f"{where}: distinct_sequences groups need 2+ "
                               "declared inputs")
    for item in exp.get("collapses", []):
        if (not isinstance(item, dict) or set(item) != {"inputs", "output"}
                or len(item["inputs"]) < 2
                or not set(item["inputs"]) <= set(inputs)
                or any(exp["outputs"][i] != item["output"]
                       for i in item["inputs"])
                or any(exp["outcomes"][i] not in ("renamed", "unchanged")
                       for i in item["inputs"])):
            raise FixtureError(f"{where}: a collapse needs 2+ resolved "
                               "inputs that share the declared output")
    other = exp.get("recognized_in_other_assembly", {})
    for ident, assembly in other.items():
        if (exp["outcomes"].get(ident) != "unknown"
                or assembly not in known_assemblies()
                or assembly == ex["assembly"]):
            raise FixtureError(f"{where}: recognized_in_other_assembly needs "
                               "an unknown input and a different assembly")
    if "rows_after" in exp:
        _check_rows(where, "rows", ex.get("rows"))
        _check_rows(where, "rows_after", exp["rows_after"])
        rows, after = ex["rows"], exp["rows_after"]
        if len(rows) != len(after) or not {r["chr"] for r in rows} <= set(inputs):
            raise FixtureError(f"{where}: rows_after needs one row per row "
                               "and rows must use declared inputs")
        for before, now in zip(rows, after):
            if now["chr"] != exp["outputs"][before["chr"]] or any(
                    before[c] != now[c] for c in ROW_COLUMNS if c != "chr"):
                raise FixtureError(f"{where}: rows_after may differ from rows "
                                   "only in the declared output chr")
    elif "rows" in ex:
        raise FixtureError(f"{where}: rows needs expected rows_after")


def validate_examples(data):
    """Raise FixtureError unless ``data`` matches the fixture schema."""
    if not isinstance(data, dict) or not isinstance(data.get("examples"), list):
        raise FixtureError("top level must be an object with an 'examples' list")
    seen = set()
    for ex in data["examples"]:
        if not isinstance(ex, dict):
            raise FixtureError("each example must be an object")
        name = ex.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise FixtureError(f"invalid example name {name!r}")
        if name in seen:
            raise FixtureError(f"duplicate example name {name!r}")
        seen.add(name)
        where = f"example {name!r}"
        if ex.get("kind") == CHROMOSOME_KIND:
            _validate_chromosome_example(where, ex)
            continue
        extra = ex.keys() - {"name", "kind", "query", "annotations",
                             "min_overlap", "use_strand", "expected"}
        if extra:
            raise FixtureError(f"{where}: unexpected keys {sorted(extra)}")
        if ex.get("kind") not in KINDS:
            raise FixtureError(f"{where}: kind must be one of "
                               f"{sorted([*KINDS, CHROMOSOME_KIND])}")
        if "query" not in ex:
            raise FixtureError(f"{where}: missing 'query'")
        _check_interval(f"{where} query", ex["query"], annotation=False)
        anns = ex.get("annotations")
        if not isinstance(anns, list) or not anns:
            raise FixtureError(f"{where}: 'annotations' must be a non-empty list")
        ids = []
        for ann in anns:
            _check_interval(f"{where} annotation", ann, annotation=True)
            ids.append(ann["id"])
        if len(set(ids)) != len(ids):
            raise FixtureError(f"{where}: duplicate annotation ids")
        if "min_overlap" in ex:
            v = ex["min_overlap"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not 0 <= v <= 1:
                raise FixtureError(f"{where}: min_overlap must be in [0, 1]")
        if "use_strand" in ex and type(ex["use_strand"]) is not bool:
            raise FixtureError(f"{where}: use_strand must be a boolean")
        exp = ex.get("expected")
        if not isinstance(exp, dict) or not exp:
            raise FixtureError(f"{where}: 'expected' must be a non-empty object")
        for key, value in exp.items():
            if key not in FACT_TYPES:
                raise FixtureError(f"{where}: unknown expected fact {key!r}")
            want = FACT_TYPES[key]
            if want is float:
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            else:
                ok = type(value) is want
            if not ok:
                raise FixtureError(f"{where}: {key} must be {want.__name__}")
        if "closest_ties" in exp and not set(exp["closest_ties"]) <= set(ids):
            raise FixtureError(f"{where}: closest_ties names unknown annotations")
        if "candidate_distances" in exp:
            cd = exp["candidate_distances"]
            if set(cd) != set(ids) or any(type(v) is not int or v < 0
                                          for v in cd.values()):
                raise FixtureError(f"{where}: candidate_distances needs one "
                                   "non-negative integer per annotation id")
        _check_kind(where, ex, exp, len(anns))
        if "min_overlap_pass" in exp and "min_overlap" not in ex:
            raise FixtureError(f"{where}: min_overlap_pass needs min_overlap")
        if "stranded_match" in exp and not ex.get("use_strand"):
            raise FixtureError(f"{where}: stranded_match needs use_strand")
    return data


def load_examples(path=FIXTURE):
    """Return ``{name: example}`` (fixture order) after schema validation."""
    data = validate_examples(json.loads(Path(path).read_text()))
    return {ex["name"]: ex for ex in data["examples"]}


# --------------------------------------------------------------------------
# Rendering (display of declared values only)
# --------------------------------------------------------------------------


def _yn(value):
    return "yes" if value else "no"


def plural(n, noun):
    """'1 base', '2 bases', '1 annotation', '2 annotations'."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def base_span(start, end):
    """Bases covered by half-open [start, end): 'base 19' / 'bases 19–20'."""
    if end - start == 1:
        return f"base {start}"
    return f"bases {start}–{end - 1}"


def interval_labels(example):
    """Standard labels: 'query', then 'annotation' or 'annotation A1..An'."""
    anns = example["annotations"]
    if len(anns) == 1:
        return ["query", "annotation"]
    return ["query"] + [f"annotation A{i}" for i in range(1, len(anns) + 1)]


def _diagram(rows):
    lo = min(iv["start"] for _, iv in rows)
    hi = max(iv["end"] for _, iv in rows)
    label_w = max(len("bases"), *(len(label) for label, _ in rows)) + 2
    lines = ["bases".ljust(label_w)
             + "".join(f"{b:>{CELL}}" for b in range(lo, hi))]
    for label, iv in rows:
        cells = "".join(
            f"{'#':>{CELL}}" if iv["start"] <= b < iv["end"] else f"{'.':>{CELL}}"
            for b in range(lo, hi))
        lines.append(f"{label:<{label_w}}{cells}  [{iv['start']}, {iv['end']})")
    lines.append("")
    for label, iv in rows:
        n = iv["end"] - iv["start"]
        lines.append(f"{label:<{label_w}}{base_span(iv['start'], iv['end'])} "
                     f"({plural(n, 'base')}); "
                     f"boundary coordinates {iv['start']} and {iv['end']}")
    return lines


def _summary(example, labels):
    """Summary lines in the kind's teaching order (declared values only)."""
    exp = example["expected"]
    ids = [a["id"] for a in example["annotations"]]
    label_of = dict(zip(ids, labels[1:]))
    strand = lambda iv: iv.get("strand", "missing")  # noqa: E731
    simple = {
        "overlap": ("overlap", lambda: _yn(exp["overlap"])),
        "overlap_length": ("overlap length", lambda: str(exp["overlap_length"])),
        "query_length": ("query length", lambda: str(exp["query_length"])),
        "overlap_fraction": ("overlap fraction (query-relative)",
                             lambda: f"{exp['overlap_fraction']:g}"),
        "min_overlap_pass": ("passes min_overlap",
                             lambda: _yn(exp["min_overlap_pass"])),
        "contains": ("query contains annotation", lambda: _yn(exp["contains"])),
        "within": ("query within annotation", lambda: _yn(exp["within"])),
        "closest_distance": ("closest distance",
                             lambda: str(exp["closest_distance"])),
        "stranded_match": ("stranded match", lambda: _yn(exp["stranded_match"])),
        "threshold": ("min_overlap threshold",
                      lambda: f"{example['min_overlap']:g}"),
        "strand_matching": ("strand matching",
                            lambda: "on" if example["use_strand"] else "off"),
        "query_strand": ("query strand", lambda: strand(example["query"])),
        "annotation_strand": ("annotation strand",
                              lambda: strand(example["annotations"][0])),
    }
    lines = []
    for token in KINDS[example["kind"]][0]:
        if not _token_present(token, example):
            continue  # optional token not declared
        if token == "candidate_distances":
            width = max(len(label_of[i]) for i in ids)
            retained = set(exp["closest_ties"])
            lines.append("candidate distances:")
            for i in ids:
                state = "retained" if i in retained else "excluded"
                lines.append(f"  {label_of[i]:<{width}}  "
                             f"{exp['candidate_distances'][i]:>3}  {state}")
        elif token == "closest_ties":
            ties = exp["closest_ties"]
            lines.append(f"retained: {plural(len(ties), 'annotation')}, in "
                         f"annotation order: "
                         + ", ".join(label_of[i] for i in ties))
        else:
            label, value = simple[token]
            lines.append(f"{label}: {value()}")
    return lines


def _table(header, rows):
    """Left-aligned text table: header line, then one line per row."""
    cells = [list(map(str, header))] + [list(map(str, r)) for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
            for r in cells]


def _result_text(example, ident):
    outcome = example["expected"]["outcomes"][ident]
    short = TARGET_SHORT[example["target"]]
    return {
        "renamed": "renamed",
        "unchanged": f"recognized; already in {short} naming",
        "unknown": f"not recognized in {example['assembly']}; kept as provided",
        "no_alias_for_target": (f"recognized; no verified {short} name; "
                                "kept as provided"),
    }[outcome]


def _render_chromosome(example):
    """Chromosome-naming block: declared facts only, one row per identifier.

    Identifiers are shown as table rows (never arrows between rows), so the
    page cannot suggest that one distinct identifier maps to another.
    """
    exp = example["expected"]
    lines = [f"genome assembly: {example['assembly']}",
             f"chromosome naming: {TARGET_LABELS[example['target']]}",
             ("only chromosome names can change; coordinates and assembly "
              "are unchanged"), ""]
    lines += _table(("input", "output", "result"),
                    [(i, exp["outputs"][i], _result_text(example, i))
                     for i in example["inputs"]])
    summary = []
    for group in exp.get("distinct_sequences", []):
        summary.append("different sequences: " + ", ".join(group))
    other = exp.get("recognized_in_other_assembly", {})
    if other:
        summary.append("recognized in another assembly: " + ", ".join(
            f"{i} ({a})" for i, a in other.items()))
    for item in exp.get("collapses", []):
        summary.append("merged output name (informational): "
                       + ", ".join(item["inputs"]) + " \u2192 " + item["output"])
    if summary:
        lines += [""] + summary
    if "rows_after" in exp:
        header = list(ROW_COLUMNS)
        for title, rows in (("rows before", example["rows"]),
                            ("rows after", exp["rows_after"])):
            lines += ["", title]
            lines += _table(header, [[r[c] for c in header] for r in rows])
    return lines


def render_block(example):
    """Deterministic text for one example (without the HTML markers).

    Raises RenderError if any line would exceed MAX_WIDTH.
    """
    if example["kind"] == CHROMOSOME_KIND:
        lines = _render_chromosome(example)
        too_wide = [l for l in lines if len(l) > MAX_WIDTH]
        if too_wide:
            raise RenderError(
                f"example {example['name']!r}: line of {len(too_wide[0])} "
                f"characters exceeds MAX_WIDTH={MAX_WIDTH}; use a more "
                "compact fixture")
        return "```text\n" + "\n".join(lines) + "\n```"
    query = example["query"]
    labels = interval_labels(example)
    rows = list(zip(labels, [query] + list(example["annotations"])))
    lines = [f"chromosome {query['chr']}; 0-based half-open coordinates",
             LEGEND, ""]
    lines += _diagram(rows)
    lines.append("")
    lines += _summary(example, labels)
    too_wide = [l for l in lines if len(l) > MAX_WIDTH]
    if too_wide:
        raise RenderError(
            f"example {example['name']!r}: line of {len(too_wide[0])} "
            f"characters exceeds MAX_WIDTH={MAX_WIDTH}; use a more compact "
            "fixture")
    return "```text\n" + "\n".join(lines) + "\n```"


# --------------------------------------------------------------------------
# Marker replacement
# --------------------------------------------------------------------------


def replace_blocks(text, rendered, source="<text>"):
    """Replace only the content between markers; return (new_text, names).

    Everything outside the BEGIN/END marker lines is preserved byte for
    byte. Raises MarkerError for unknown names or malformed markers.
    """
    out = []
    names = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m_end = END_RE.match(line)
        if m_end:
            raise MarkerError(f"{source}:{i + 1}: END without BEGIN")
        m = BEGIN_RE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        name = m.group(1)
        if name not in rendered:
            raise MarkerError(f"{source}:{i + 1}: unknown example {name!r}")
        if name in names:
            raise MarkerError(f"{source}:{i + 1}: duplicate block {name!r}")
        j = i + 1
        while j < len(lines) and not END_RE.match(lines[j]):
            if BEGIN_RE.match(lines[j]):
                raise MarkerError(f"{source}:{j + 1}: nested BEGIN")
            j += 1
        if j == len(lines):
            raise MarkerError(f"{source}:{i + 1}: BEGIN {name!r} without END")
        if END_RE.match(lines[j]).group(1) != name:
            raise MarkerError(f"{source}:{j + 1}: END does not match BEGIN {name!r}")
        out.append(line)
        out.extend(rendered[name].split("\n"))
        out.append(lines[j])
        names.append(name)
        i = j + 1
    return "\n".join(out), names


def markdown_files(docs_dir=DOCS_DIR):
    return sorted(Path(docs_dir).rglob("*.md"))


def run(*, check=False, fixture=FIXTURE, docs_dir=DOCS_DIR, out=sys.stdout):
    """Process every docs page; return the process exit status."""
    examples = load_examples(fixture)
    rendered = {name: render_block(ex) for name, ex in examples.items()}
    stale = []
    for path in markdown_files(docs_dir):
        old = path.read_text()
        if "GENERATED:" not in old:
            continue
        new, _ = replace_blocks(old, rendered, source=str(path))
        if new != old:
            stale.append(path)
            if not check:
                path.write_text(new)
    for path in stale:
        verb = "stale" if check else "updated"
        print(f"{verb}: {path}", file=out)
    if check and stale:
        print("Generated example blocks are out of date; run "
              "`python scripts/generate_semantic_examples.py`.", file=out)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if docs differ; write nothing")
    args = parser.parse_args(argv)
    try:
        return run(check=args.check)
    except (FixtureError, MarkerError, RenderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
