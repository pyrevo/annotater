# Result columns and provenance

The result table has a **canonical column schema**. No backend column
names ever leak through: the same columns, with the same names, in the
same order, from both engines
([Technical Reference → scientific contract](../technical/scientific-contract.md)).

## The prefixes carry the provenance

| Prefix | Source |
|---|---|
| `coord_*` | **only** your query (coordinate) file |
| `annot_*` | **only** your annotation file |

This is how you can read a result even when both files use columns with
the same name (for example, both have a "gene" column): the prefixes
make every value's origin unambiguous.

## Fixed columns, in order

| Column | Source | Notes |
|---|---|---|
| `coord_chr` | query | after any configured chromosome normalization |
| `coord_start` | query | canonical **0-based** start |
| `coord_end` | query | canonical **half-open** end |
| `coord_strand` | query | present when the query carries strand; `+`/`-` or missing |
| `coord_name` | query | BED column 4 / a custom-table column named `name` (when present) |
| `coord_score` | query | score-like field (when present) |
| `annot_chr` | annotation | after standardization |
| `annot_start` | annotation | canonical 0-based start |
| `annot_end` | annotation | canonical half-open end |
| `annot_strand` | annotation | present when the annotation carries strand |
| `annot_source` | annotation | GFF/GTF source column (when present) |
| `annot_feature` | annotation | GFF/GTF feature type (when present) |
| `annot_score` / `annot_frame` | annotation | when present |
| `annot_attributes` | annotation | the **full raw GFF/GTF attribute string** — always preserved even though the extracted columns below are derived from it |
| `annot_ID` / `annot_Name` | annotation | extracted from the attribute string (key-exact) |
| `annot_gene_id` / `annot_gene_name` | annotation | extracted (key-exact) |
| `annot_transcript_id` | annotation | extracted (key-exact) |
| `annot_gene_type` / `annot_gene_biotype` | annotation | extracted (key-exact) |
| `annot_Parent` | annotation | extracted (key-exact) |
| `has_overlap` | computed | `True` / `False` — see [Matched vs unmatched rows](matched-unmatched.md) |
| `distance` | computed | **closest mode only**; the canonical gap to the attached annotation (≥ 0); missing on unmatched rows |

## Query metadata passes through

Beyond the fixed columns, **every metadata column of your query file**
appears as a `coord_`-prefixed column, in input order. A BED query with
columns 4–7 gets `coord_name`, `coord_score`, `coord_strand`,
`coord_col7`; a VCF query keeps `coord_id`, `coord_ref`, `coord_alt`,
`coord_qual`, `coord_filter`, `coord_info`, `coord_format` and one
column per declared sample (for example `coord_SAMPLE1`); a custom
query table keeps every column you did **not** map to chromosome,
start or end, as `coord_<column name>` in original column order (a
column named `strand` becomes `coord_strand`). A custom annotation
table's extra columns appear the same way with the `annot_` prefix
([Supported file formats](../preparing-your-data/supported-formats.md)).

## Attribute extraction is key-exact

For GFF/GTF annotations, the attribute string is parsed for the keys
`ID`, `Name`, `gene_id`, `gene_name`, `transcript_id`, `gene_type`,
`gene_biotype`, `Parent`. Extraction is **key-exact**: an attribute
spelled `GeneID` or `gene_ID` is *not* extracted into a column — but it
remains visible in `annot_attributes`, so nothing is ever lost. If a
column you expected is empty, check `annot_attributes` first: the
answer is there, under a different key.

## What is normalized, what is verbatim

| Value | Normalization |
|---|---|
| Coordinates (`*_start`, `*_end`) | converted to canonical 0-based half-open at parse time; **not** re-adjusted for display |
| Chromosomes (`*_chr`) | normalized at run time through the selected genome assembly (or custom mapping) when a chromosome naming is chosen (default: *Keep original names*, unchanged); unrecognized identifiers are kept as provided |
| Strands (`*_strand`) | **verbatim** `+`/`-`; missing stays missing — no case-folding, no guessing |
| Scores | passed through as-is |
| Attribute-derived columns | extracted verbatim from the raw attribute string |

So: if you export the result and compare `annot_start` to the number in
your GFF file, the export is in **0-based half-open** form, not GFF3's
1-based inclusive form ([Coordinate systems](../preparing-your-data/coordinate-systems.md)).

## Missing values are canonical

Unmatched rows (and optional columns that do not exist in your input)
carry a single canonical missing value, rendered as blank in the table
and as empty cells in CSV/Excel exports. VCF-format `.` sentinels are
normalized to this same missing state at parse time.

## Where to go next

- [Matched vs unmatched rows](matched-unmatched.md)
- [Downloading and exporting results](export.md)
- [Technical Reference → scientific contract](../technical/scientific-contract.md) —
  the binding SPEC sections.