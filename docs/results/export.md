# Downloading and exporting results

The **"Download results"** section exports **exactly the rows
currently shown** above it: if you use the Show filter to narrow the
table, the download is narrowed to the same rows ("Exports the rows
currently shown above (use the display filter to narrow the export)").
The canonical result itself is never mutated by filtering.

## The four export buttons

| Button | Format | File name |
|---|---|---|
| **CSV** | comma-separated | `annotated_coordinates.csv` |
| **TSV** | tab-separated | `annotated_coordinates.tsv` |
| **Excel** | XLSX, sheet "Annotations" (requires openpyxl) | `annotated_coordinates.xlsx` |
| **Annotated VCF** | reconstructed VCF with annotations added to the INFO field | `annotated_variants.vcf` — **shown only when the query input was VCF** |

The file names are fixed by the app.

## What coordinates are in the exports

All exports carry the **canonical 0-based half-open** values
(`coord_start/coord_end`, `annot_start/annot_end`) — the same numbers
you saw in the table. If you are putting these next to numbers from a
GFF3 file, remember the GFF3 numbers are 1-based inclusive and the
export is *not*; see
[Coordinate systems](../preparing-your-data/coordinate-systems.md).

Missing values (unmatched `annot_*` columns, absent optional fields)
export as empty cells.

## The Annotated VCF export

When the **query** file is VCF, a fifth button appears:
"Reconstructed VCF: original record fields (ID/REF/ALT/QUAL/FILTER,
INFO, FORMAT and samples) are preserved, and annotations are appended
to INFO as declared ANNOT_* entries. One record per query-annotation
pair. Shown only when the coordinate input is VCF."

It reconstructs a VCF from the *displayed* rows:

- `CHROM` and `POS` use VCF conventions — `POS = coord_start + 1`
  (1-based, the first base of the query interval);
- the original record fields are preserved verbatim from the preserved
  `coord_*` metadata: ID, REF, ALT, FILTER, the raw **INFO** field
  (including `END` for symbolic variants), and, when present, the
  **FORMAT** column and the sample columns in their original order;
- matched rows gain annotation information in the **INFO** field as
  `ANNOT_<field>` entries — the original INFO content is never
  replaced or rewritten, and every `ANNOT_*` key is declared by a
  generated `##INFO` line in the exported header;
- one output record per result row: a variant matching N annotations
  is written N times, with identical original fields and different
  `ANNOT_*` payloads;
- unmatched rows are written with their original fields intact and
  without `ANNOT_*` entries (INFO is the original INFO, or `.` when
  that was missing too);
- rows are in the original query record order, with ties in
  annotation input order;
- `QUAL` is exported as stored: integer values without a fractional
  part (`50`, not `50.0`); missing values stay `.`.

**Header metadata.** The original `##...` metadata lines from the query
VCF — for example `##contig`, `##INFO`, `##FORMAT` and `##FILTER`
declarations, plus any other metadata — are preserved verbatim and in
source order, once per source file (not per result row), together with
the source file's `##fileformat` version. The exporter adds its own
`##source=AnnotateR <version>` and `##date` lines (additions, not
replacements), the `##INFO` declarations for the `ANNOT_*` keys it
emits, and — if the source had no `##fileformat` line at all — a
fallback one. If the source header already declares an `ANNOT_*` INFO
key: a `Type=String` declaration is kept as-is (no duplicate is
generated), while a declaration with any other type is refused with an
explicit error rather than silently overwritten. Original definitions
are never re-synthesized — no types or descriptions are invented.

**Chromosome identifiers and `##contig`.** The exported `CHROM` values
are the chromosome identifiers of the AnnotateR result. When chromosome
normalization is active, every `##contig` declaration of the header is
looked up in the same genome assembly (or custom mapping) and chromosome
naming as the records — including contigs that no record uses — and its
ID is renamed when the registry has a verified name (for example `1` →
`chr1` for GRCh38 with UCSC names). Its other attributes (`length`,
`assembly`, `md5` and so on) are kept, so `CHROM` values and `##contig`
declarations agree. Contigs the assembly does not know, or that have no
verified name in the chosen naming, keep their original lines; a source
with no `##contig` lines gets none, and no `##contig` line is added for
an identifier the source never declared. If several declarations are
renamed to one identifier they are merged only when their remaining
attributes are equivalent; otherwise the export is refused with a
message naming the contigs and the conflicting attributes. With *Keep
original names* the header is left as provided.

**What this export does not claim.** It is not a byte-for-byte
round trip of the input VCF. Original metadata are carried forward as
text; AnnotateR does not semantically reinterpret or regenerate
arbitrary original VCF metadata, and the output contains additional
`##source`, `##date` and `ANNOT_*` `##INFO` lines. Because there is one
record per result row, the record count can exceed the number of input
variants when a variant matches several annotations.

This is the one place where a format convention is deliberately
reconstructed for the output format.

## Excel export

The Excel button requires `openpyxl` in the app's environment. If it is
not installed you will see the caption "Excel export requires openpyxl"
and should use CSV/TSV instead — all columns are identical across
formats.

## Practical tips

- Use **CSV** for spreadsheet work and **TSV** for tabular text
  pipelines; use **TSV** if any of your metadata columns contain commas.
- To export *all* rows (not just the filtered view), set the Show
  filter to **All** first.
- Download both engines' outputs for the same configuration and diff
  them if you want to sanity-check a run — they are contractually
  identical ([Choosing an annotation engine](../using/engines.md)).