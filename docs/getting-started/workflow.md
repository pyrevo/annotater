# The AnnotateR workflow

This page is the map the rest of the manual hangs on: what happens to
your files between **Upload** and **Download**, and which UI region
shows you each stage.

```text
   1. UPLOAD              2. PARSE + NORMALIZE          3. ANNOTATE             4. RESULT
 ┌──────────────┐      ┌─────────────────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ Query        │      │ detect format           │   │ at Run:          │   │ canonical result │
 │ coordinates  ├─────▶│ parse                   ├──▶│ feature filter   ├──▶│ (coord_* /       │
 │ file         │      │ convert to the canonical│   │ (GFF/GTF),       │   │  annot_* rows,   │
 │              │      │ 0-based half-open model │   │ chromosome       │   │  has_overlap[,   │
 │ Annotation   │      │                         │   │ standardization, │   │  distance])      │
 │ features     │      │ (previews show this     │   │ interval         │   │                  │
 │ file         │      │  table)                 │   │ operation        │   │ display + export │
 └──────────────┘      └─────────────────────────┘   └──────────────────┘   └──────────────────┘
   "1. Upload"            previews below each        sidebar chooses       results section:
   section, both          uploader ("1. Upload")     stage 3; invalidates  metrics, Show filter,
   uploaders              show the parsed table      stale results on      table, charts,
                          before stage 3 steps       every configuration   downloads
                                                      change
```

## Stage 1 — Upload (UI: "1. Upload")

You upload exactly two files: **Query coordinates** and **Annotation
features**. The accepted file extensions and size limits are documented
in [Uploading files](../using/uploading-files.md).

## Stage 2 — Parse and normalize (UI: the preview panels)

Each uploaded file is immediately:

1. **Detected** — the format is determined from the file (BED, GFF3,
   GTF, VCF, or custom table);
2. **Parsed** — intervals and metadata columns are extracted
   ([Supported file formats](../preparing-your-data/supported-formats.md));
3. **Normalized to the canonical model** — all coordinates become
   **0-based half-open** `[start, end)` intervals, regardless of the
   source format's convention ([Coordinate systems](../preparing-your-data/coordinate-systems.md)).
   Custom query tables are normalized once you apply the column mapping.

The preview panel under each uploader shows the first 10 rows of this
parsed, coordinate-normalized table. It is shown **before** two later
steps that are applied when you press **Run annotation**:

- **Feature filtering** — for GFF/GTF annotation files, only the
  selected feature types are kept ([Feature filtering](../using/feature-filtering.md));
- **Chromosome normalization** — if you select a genome assembly (or a
  custom mapping) and a chromosome naming, each chromosome identifier of
  both files is looked up in that assembly and renamed to the chosen
  naming system; with *Keep original names* nothing is changed
  ([Chromosome identifiers and genome assemblies](../preparing-your-data/chromosome-identifiers.md)).

So the previews do not show filtered rows or renamed chromosome
identifiers.

## Stage 3 — Annotate (UI: the sidebar)

The sidebar selects the execution of stage 3:

- **Annotation engine** — Bedtools or Polars-Bio
  ([Choosing an annotation engine](../using/engines.md));
- **Operation** — overlap, contains, within, or closest
  ([Choosing an operation](../operations/choosing-an-operation.md));
- **Join behavior** — keep all query rows (left) or matched rows only
  (inner) ([Join behavior: left vs inner](../operations/join-behavior.md));
- **Input options** — coordinate-system declaration (custom files and
  extension-neutral tables), genome assembly and chromosome naming;
- **Advanced options** — strand matching and the `min_overlap` slider
  (overlap mode only);
- **Feature filter** — which GFF/GTF feature types participate.

Pressing **Run annotation** executes the interval operation. Changing
any configuration option *invalidates* stored results: you never see a
stale table ([Running the annotation](../using/running.md)).

## Stage 4 — Result and export (UI: the results section)

The engine always produces the same **canonical result**: one row per
qualifying query/annotation pair (plus one row per unmatched query in
left-join mode), with `coord_*` and `annot_*` columns, `has_overlap`,
and — in closest mode — `distance`
([Result columns and provenance](../results/result-columns.md)).

From the results section you can filter what is displayed (which also
narrows the download), explore summary charts, and download CSV / TSV /
Excel / annotated VCF
([Downloading and exporting results](../results/export.md)).

## What does *not* happen

- No intentional persistence: temporary parsing files are deleted
  immediately after parsing, and parsed data and results remain only in
  application memory for the active session
  ([Limitations → Data handling](../limitations.md#data-handling)).
- No silent engine fallback: if the selected engine is unavailable, the
  run fails with an explicit message
  ([Troubleshooting](../troubleshooting.md)).
- No guessing: malformed files, invalid intervals, and unrecognized
  coordinates fail with a message instead of producing a partial
  result.