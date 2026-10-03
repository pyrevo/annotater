# Troubleshooting

Diagnosis, in the order things usually break. Most problems are one of
these four.

## Zero matches

You ran the annotation (informational state: "No qualifying annotations
were found for the selected operation and options.") and no row has
`has_overlap = True` — or with an inner join, the result is empty.
Check in this order:

1. **Chromosome naming mismatch** — query says `1`, annotation says
   `chr1` (or accession names). Select the **Genome assembly** both files
   were made with and a **Chromosome naming** (not *Keep original
   names*), then re-run. Identifiers that are not recognized in the
   selected assembly, or that have no verified name in the chosen naming,
   are kept and listed on the results page; the app warns when the two
   tables share no chromosome identifier. The previews show names
   *before* normalization, so compare them to see the mismatch
   ([Chromosome identifiers and genome assemblies](preparing-your-data/chromosome-identifiers.md),
   including its list of common messages).
2. **Strand matching on, but the data has no (or one-sided) strand** —
   especially a **VCF query**: VCF has no strand, so with strand
   matching on, *every* query row is unmatchable. Also: your GFF's
   strand column is all `.`. Turn the strand checkbox off and re-run
   ([Strand information](preparing-your-data/strand-information.md)).
3. **Feature filter excludes everything relevant** — the default
   filter is `gene` only. If your annotation's relevant records are
   exons/transcripts (or use non-standard type names), widen or clear
   the filter ([Feature filtering](using/feature-filtering.md)).
4. **Wrong operation direction** — you asked "does my region *contain*
   the feature?" but the feature contains *your* region. Try
   `within`/`contains` the other way, or plain `overlap` to confirm the
   intervals intersect at all
   ([Choosing an operation](operations/choosing-an-operation.md)).
5. **Coordinate-system misdeclaration** — a custom table declared
   0-based that is actually 1-based (or numbers pre-adjusted by you):
   everything is shifted by one base and may sit in gaps. Re-declare
   the coordinate system; never pre-adjust source numbers
   ([Coordinate systems](preparing-your-data/coordinate-systems.md)).
6. **Touching intervals** — your intervals end exactly where the
   annotation begins. Touching is not overlap by design; use
   `closest` (distance 0) if you want those pairs
   ([Overlap → touching is not overlap](operations/overlap.md#touching-is-not-overlap)).

Also confirm the two files really describe the same reference (same
genome build/assembly).

## Upload failures

| Symptom | Usually | Fix |
|---|---|---|
| Uploader rejects the file | extension not in the accepted list (for example a GFF3/GTF file in the query uploader, or a VCF in the annotation uploader), or file larger than the upload limit (200 MB by default; 100 MB on SciLifeLab Serve) | use the other uploader or save with an accepted extension; split very large files |
| Zero-row preview, no error message | header-only, comment-only or empty file (there is no dedicated "empty file" message) | check the file has data rows |
| Error at line 1 of a `.bed` ("expected at least 3 tab-separated fields") | UCSC `track`/`browser` line (unsupported) or a header line | delete the `track`/`browser`/header line |
| Attribute value cut off in a GFF3/GTF | a `#` inside the attributes column starts a comment | remove or percent-encode (`%23`) the `#` |
| Parse error naming a line number | malformed row (fields, non-integer coordinates) | open the file at that line; the error tells you what is expected |
| VCF column layout error | records with `FORMAT`/sample columns but no `#CHROM` line, or a record whose field count differs from the `#CHROM` line | restore the VCF header ([Supported file formats → VCF](preparing-your-data/supported-formats.md)) |
| Preview looks off-by-one everywhere | coordinate system declared wrong (custom tables) | flip the declaration, never the file |
| Preview columns not what I expect | column mapping not applied (custom tables) | apply the mapping in the preview panel |

## Engine unavailable

An error naming the selected engine (typically Bedtools) means the
backend binary is missing in **this deployment** — e.g. a container
image without `bedtools` on PATH, or a restricted temporary directory.

- Switch the sidebar to **Polars-Bio** and re-run: same operations,
  same canonical result
  ([Choosing an annotation engine](using/engines.md)).
- For maintainers: install `bedtools` on the system PATH and ensure the
  process's `TMPDIR` is writable ([Deployment](deployment.md)).
- There is no silent fallback; a run with an unavailable engine always
  fails loudly.

## A run is very slow

- **Closest mode is the most expensive operation**, especially with
  large annotation sets — prefer it only when you actually need
  non-overlapping nearest features
  ([Closest](operations/closest.md)).
- Dense annotations × left join produce large result tables; the
  in-table rendering and exports scale with result size, not just input
  size.
- On the measured workloads, the **Polars-Bio** engine was faster for
  pair-producing operations (`overlap`, `contains`, `within`);
  `closest` runs the shared canonical implementation on both backends
  ([Backend parity and benchmark](benchmark.md)).
- There is no job queue: the run executes in your session. If a
  deployment imposes timeouts, reduce input size or change operation.

## Results look wrong

| Symptom | Usually |
|---|---|
| Result is the "mirror image" of what I expected | swapped `contains`/`within` direction ([Example 4](examples/contains-within.md)) |
| More result rows than input rows | expected: one row per matching annotation pair ([FAQ](faq.md)) |
| `annot_start` doesn't match my GFF number | the export is 0-based half-open, GFF3 is 1-based inclusive ([Coordinate systems](preparing-your-data/coordinate-systems.md)) |
| A gene column is empty but the info is "in there" | attribute key differs from the extracted keys; read `annot_attributes` ([Result columns](results/result-columns.md#attribute-extraction-is-key-exact)) |
| Two runs with the same files differ | a configuration option changed between runs (results invalidate on any change — check the provenance caption: engine · operation · join) |
| `min_overlap` seems to ignore long annotations | correct: the fraction is of the **query**, per pair, never summed ([Minimum overlap](operations/min-overlap.md)) |

## Still stuck?

Report the problem with: the two (small) input files, the exact
sidebar configuration (screenshot or values), the engine selected, and
the error message or a snippet of the unexpected rows. Zero-match
diagnosis is fastest when the two preview panels are included — they
show the parsed, coordinate-normalized tables, before the feature
filter and chromosome normalization that are applied at run time.