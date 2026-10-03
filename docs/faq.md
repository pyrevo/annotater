# FAQ

## General

### What file formats does AnnotateR accept?

BED, GFF3, GTF, VCF, and custom CSV/TSV tables with column mapping.
Roles are fixed by the uploader: VCF is **query-only**, and GFF3/GTF are
**annotation-only**, in v0.1.0. Details:
[Supported file formats](preparing-your-data/supported-formats.md).

### Do my files stay on my computer?

Not by themselves. Uploaded files are processed by the running
AnnotateR server. Temporary parsing files are deleted immediately after
parsing; parsed data and results remain only in application memory for
the active session. AnnotateR has no account system and no upload
history, and does not intentionally persist uploaded files or results
after that lifecycle.

Local Docker execution processes uploads in the AnnotateR container
running on your own machine; SciLifeLab Serve is not involved. See
[Limitations → Data handling](limitations.md#data-handling).

### Can I annotate more than two files at once?

No — one query file and one annotation file per run. Run separate
analyses and combine the exports downstream.

### Does AnnotateR modify my files?

No. Your uploads are only parsed. All normalization (coordinate
conversion, chromosome naming) happens on in-memory copies.
Coordinate conversion is visible in the preview panels; the feature
filter and chromosome normalization are applied when you press
**Run annotation**, after the preview.

### Does AnnotateR change my coordinates or my genome assembly when it renames chromosomes?

No. Chromosome normalization changes only the chromosome identifier.
Start, end, strand and every other column stay as they were, and it is
not liftover ([Chromosome identifiers and genome assemblies](preparing-your-data/chromosome-identifiers.md)).

### Why do I have to choose a genome assembly?

The same chromosome name can denote different sequences in different
assemblies, so AnnotateR resolves each identifier inside the assembly you
select instead of guessing from its shape. If you keep the original
names, no assembly is needed.

### My organism or assembly is not in the list. What can I do?

Choose **Custom chromosome mapping…** and upload a `.tsv` table with your
own names. AnnotateR checks its structure but does not verify that the
names are biologically correct
([custom mappings](preparing-your-data/chromosome-identifiers.md#custom-chromosome-mapping)).

## Semantics

### Why is my result table bigger than my input?

A query matching N annotations produces **N rows** — AnnotateR never
picks one feature for you. Combined with left-join unmatched rows,
result size grows with *matches per query*, not with input size. This
is by design: which gene "wins" is a biological decision that belongs
in your downstream analysis.

### Can I switch engines mid-analysis?

Yes — and results are identical by contract. Changing the engine
invalidates the stored result like any other configuration change;
press **Run annotation** again. Re-running the same configuration on
both engines and diffing the downloads is a legitimate sanity check.

### Why does closest return several annotations for one query?

An **exact tie**: several annotations are equally nearest, and all ties
are returned (in annotation input order). AnnotateR never breaks ties
arbitrarily. See [Example 5](examples/closest.md).

### Why is `has_overlap = True` even though `distance` is 250?

In **closest** mode `has_overlap` means "an annotation was attached",
not "the intervals overlap". Read the gap from the `distance` column.
In the other modes `has_overlap=True` genuinely means overlap.

### Does min_overlap add up coverage from several annotations?

No. Each query/annotation pair is judged **alone** on how much of the
*query* that single annotation covers; the threshold is inclusive; no
summing, no merging. See [Minimum overlap](operations/min-overlap.md).

### Is `min_overlap = 1` the same as `contains`?

No — and not the same as `within` either. `min_overlap = 1` means "the
query is 100% covered by one annotation" (any direction, any size
difference); `contains`/`within` assert a geometric direction with
inclusive boundaries. Both pages carry counterexamples.

### Why don't my touching intervals match?

Half-open intervals that touch at the same boundary coordinate share no
genomic base, so touching is not an overlap. If you need those pairs, use `closest` — touching
intervals have distance 0. See
[Coordinate systems](preparing-your-data/coordinate-systems.md).

### Why did enabling strand matching remove matches?

By design: strand matching keeps only pairs where *both* rows carry an
explicit, equal strand. Missing strand is **not** a wildcard — a VCF
query (which has no strand) can never match with strand matching on.
See [Strand information](preparing-your-data/strand-information.md).

### My GFF numbers don't match the exported numbers — which is right?

Both, in their own conventions. The app computes and exports in
**canonical 0-based half-open**; GFF3/GTF are 1-based inclusive
(`start − 1`). The Annotated VCF export reconstructs 1-based `POS`.
See [Coordinate systems](preparing-your-data/coordinate-systems.md).

## Export

### Which export should I use?

CSV for spreadsheets, TSV for pipelines (and for metadata containing
commas), Excel for .xlsx consumers (requires openpyxl), Annotated VCF
only when your query was VCF and you want annotations back in VCF form.
CSV, TSV and Excel carry the same rows and canonical 0-based
coordinates; the Annotated VCF carries one record per result row with
VCF's 1-based `POS`.
[Downloading and exporting results](results/export.md).

### Does the Annotated VCF reproduce my input VCF?

It preserves the original record-level fields (ID, REF, ALT, QUAL,
FILTER, INFO including `END`, FORMAT and sample columns) and carries
the original `##` header lines forward, then adds `ANNOT_*` INFO entries
that are declared in the header. It writes one record per result row, so
a variant matching several annotations appears several times. It is not
a byte-for-byte round trip: AnnotateR does not reinterpret or regenerate
original VCF metadata, and adds its own `##source` and `##date` lines.
See [Downloading and exporting results](results/export.md).

### Do the exported coordinates match my input GFF's coordinates?

No — the export is canonical **0-based half-open**, not GFF3's
1-based inclusive. `annot_start` is always `gff_start − 1`.

## Limits and environment

### What are the file size limits?

Two files per run, **200 MB per file** by default (Streamlit's
`server.maxUploadSize`). SciLifeLab Serve documents a lower platform
limit of 100 MB for Streamlit apps, which applies there
([Uploading files](using/uploading-files.md#file-limits)).

### Why is Excel export missing?

The Excel button needs `openpyxl` in the app environment; without it
you will see "Excel export requires openpyxl". Use CSV/TSV — the data
is identical.

### Why is the Bedtools engine not available?

Bedtools needs a `bedtools` binary on the deployment's system PATH. If
it is absent, use Polars-Bio (same operations, same canonical
result). There is never a silent engine fallback.
[Choosing an annotation engine](using/engines.md).