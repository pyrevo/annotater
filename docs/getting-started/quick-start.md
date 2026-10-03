# Quick start

Get from files to results in about five minutes. This page assumes the
app is open in your browser (locally or as a deployed service).
Developers who need to install and run the code should follow
[QUICKSTART.md](https://github.com/pyrevo/annotater/blob/main/QUICKSTART.md)
in the repository instead.

## Step 1 — Upload two example files

Download the bundled example files from the repository:

- Query:
  [example_coordinates.bed](https://github.com/pyrevo/annotater/raw/main/data/examples/example_coordinates.bed)
- Annotation:
  [example_annotations.gff3](https://github.com/pyrevo/annotater/raw/main/data/examples/example_annotations.gff3)

In the app, use the two uploaders in the **1. Upload** section:

1. **Query coordinates** → choose `example_coordinates.bed`
2. **Annotation features** → choose `example_annotations.gff3`

Each file shows a preview below its uploader (first rows, detected
format, row count) so you can verify AnnotateR understood it.

## Step 2 — Choose the operation (or accept the default)

In the sidebar, the default **Operation** is **Overlap** with
**Keep all query rows (left join)** — leave both as they are for the
first run. Note the **Filter by feature type** box: by default it
contains `gene` only, so this first run annotates against gene features
only. The full sidebar tour, including the collapsed **Advanced
options** group, is in [Configuring the analysis](../using/configuring.md).

## Step 3 — Run

Click **Run annotation**. The results section appears below the
uploaders with a provenance caption (engine · operation · join), four
metrics, and the result table.

## Step 4 — Look at the results

For these example files with the default settings, six query regions
are annotated against the gene features: three regions match a gene
(`region1`, `region3`, `regionX`) and three do not (`region2`,
`region4`, `regionY`). With the left join, all six query regions appear
in the table — unmatched ones once, with every `annot_*` column
missing and `has_overlap=False`.

A complete walkthrough of this exact run — including changing the
feature filter to also include exons — is
[Example 1: BED query against GFF3 annotations](../examples/bed-vs-gff3.md).

## Step 5 — Download

In the **Download results** section, choose **CSV** (or TSV / Excel) to
download exactly the rows currently shown. See
[Downloading and exporting results](../results/export.md) for file
naming and the VCF export.

## Where to go next

- [The AnnotateR workflow](workflow.md) — what happens between upload
  and results.
- [Choosing an operation](../operations/choosing-an-operation.md) — the
  decision aid for overlap / min_overlap / contains / within / closest.
- [Troubleshooting](../troubleshooting.md) — if nothing matches, start
  here.