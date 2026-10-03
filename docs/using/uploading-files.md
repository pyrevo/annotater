# Uploading files

## The two uploaders

The **"1. Upload"** section holds exactly two uploaders:

- **Query coordinates** — accepts `.bed`, `.txt`, `.tsv`, `.csv`, `.vcf`
- **Annotation features** — accepts `.gtf`, `.gff`, `.gff3`, `.bed`,
  `.txt`, `.tsv`, `.csv` (no `.vcf` — VCF is a query-only input in
  v0.1.0)

GFF3 and GTF files are therefore **annotation-only**: the query
uploader does not accept `.gff`, `.gff3` or `.gtf`.

You need both files before a run is possible.

## File limits

| Constraint | Value |
|---|---|
| Maximum file size | **200 MB per file** by default (Streamlit's `server.maxUploadSize`; the AnnotateR image does not override it) |
| Maximum number of files | **2** (one per role) |
| Acceptance | determined by **file extension** (the formats are documented in [Supported file formats](../preparing-your-data/supported-formats.md)) |

A file that exceeds the size limit or has an unrecognized extension is
rejected by the uploader with an error message.

The limit is a Streamlit server setting, not an AnnotateR setting; an
operator can change it with `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (in MB)
([Deployment](../deployment.md#environment-configuration)). On
SciLifeLab Serve the platform documents a lower limit of **100 MB** for
Streamlit apps, which then applies instead.

Uploaded files are processed by the running AnnotateR server; a
temporary copy used for parsing is deleted immediately afterwards
([Limitations → Data handling](../limitations.md#data-handling)).

## What happens after you choose a file

Immediately (no button to press):

1. the file is parsed and **normalized** — you see the first 10 rows of
   the parsed, coordinate-normalized table under the uploader, with the
   detected format and row count;
2. changing a **coordinate-system declaration** re-parses a file whose
   interpretation depends on it (custom tables and extension-neutral
   `.tsv`/`.txt`/`.csv` files); any configuration change invalidates
   stored results — see [Running the annotation](running.md).

The preview shows the table **before** the feature filter and chromosome
normalization, which are applied when you press **Run annotation**.
It therefore does not show filtered rows or renamed chromosome identifiers
([The AnnotateR workflow](../getting-started/workflow.md)).

## Replacing a file

Choosing a different file for an uploader replaces the previous one
and re-runs parsing. There is no multi-file list and no queue.

## Custom tables (CSV/TSV) — column mapping and coordinate declaration

A **custom query table** (a file AnnotateR cannot recognize as a standard
format) shows a "Map coordinate columns" panel. You choose which column
is the chromosome, which is the start, and optionally which is the end
("None (single positions)" for point data), then **apply the mapping**
before the file can be used. Every unmapped column is kept as query
metadata and appears in the results with the `coord_` prefix. The
coordinate system is declared in the sidebar ("Query coordinates":
0-based half-open — the default — or 1-based inclusive) and is applied
exactly once, when the mapping is applied; a single 1-based position
becomes one base.

A **custom annotation table** has no mapping panel: it must already
contain `chr`, `start` and `end` columns, and the coordinate system
declared in the sidebar ("Annotation coordinates") is applied to it
once when it is parsed. Other columns, including an optional `strand`
column, are kept as annotation metadata.

Raw BioMart or UCSC Table Browser exports are **not** accepted as
annotation tables as they are: their column names (for example
`Chromosome/scaffold name`, `Gene start (bp)`, `chrom`, `txStart`) are
not `chr`/`start`/`end`, so rename the columns first and choose the
"Annotation coordinates" setting that matches the source data. For a
custom *query* table you map the columns in the panel instead.

See
[Supported file formats → CSV/TSV and custom tables](../preparing-your-data/supported-formats.md)
and [Coordinate systems](../preparing-your-data/coordinate-systems.md).

## Upload errors you can expect

| Symptom | Usually means |
|---|---|
| Uploader rejects the file before parsing | wrong extension, or file > 200 MB |
| Zero-row preview, with no "empty file" message | header-only, comment-only or empty file; the parsers return a table with no rows and AnnotateR shows no dedicated error for it |
| Error mentioning a `track` line or "expected at least 3 tab-separated fields" at line 1 | UCSC `track`/`browser` lines are not supported; remove them |
| Parsing error with a line number | malformed row — see the format-specific "Common errors" in [Supported file formats](../preparing-your-data/supported-formats.md) |
| Preview looks wrong (off-by-one everywhere) | wrong **coordinate-system declaration** for a custom table, or pre-adjusted source coordinates |
| Preview shows chromosome names different from the other file | expected: the preview is shown before chromosome normalization; check the **Genome assembly** and **Chromosome naming** options, which are applied at run time |

Full diagnosis: [Troubleshooting](../troubleshooting.md).