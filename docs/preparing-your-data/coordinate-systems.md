# Coordinate systems (0-based / 1-based)

AnnotateR computes and exports in one single coordinate model:

> **Canonical model: 0-based half-open intervals `[start, end)`, on
> non-negative integer bases.** An interval covers bases
> `start, start+1, …, end−1`. A valid interval has `start ≥ 0` and
> `end > start` — it always covers at least one base.

Every input format is converted to this model at upload time, and every
export carries it (with one deliberate exception for VCF, below).
You never have to convert anything yourself — but you do need to know
what your numbers mean before you upload.

## The conventions per format

| Format | Source convention | What AnnotateR does |
|---|---|---|
| BED | 0-based half-open | nothing — already canonical |
| GFF3 | 1-based inclusive `start–end` | `start := start − 1`; `end` unchanged |
| GTF | 1-based inclusive `start–end` | `start := start − 1`; `end` unchanged |
| VCF | `POS` 1-based, first base of the reference interval | span from `INFO/END` or `REF` length, then `start = POS − 1`, `end = POS + span − 1` |
| Custom table (CSV/TSV) | **you declare it** | 0-based: nothing; 1-based: `start := start − 1` |

## One-base worked examples

The same biological interval, written in each format's native
convention and shown after normalization:

| Interval (biological) | BED (canonical) | GFF3/GTF (source) | After GFF/GTF conversion | VCF (source) | After VCF conversion |
|---|---|---|---|---|---|
| bases 101–200 | `[100, 200)` | `101 200` | `[100, 200)` | — | — |
| bases 100–100 (1 bp) | `[99, 100)` | `100 100` | `[99, 100)` | `POS=100, REF=A` | `[99, 100)` |
| bases 100–103 (4 bp reference) | `[99, 103)` | `100 103` | `[99, 103)` | `POS=100, REF=ACGT` | `[99, 103)` |

The one-base case is the one that catches people: a GFF3 line
`101 101` and a BED line `100 101` describe the **same single base**.

## "Auto-detect" in the sidebar — what it actually does

The "Query coordinates" and "Annotation coordinates" selectors offer
Auto-detect, `0-based (BED)`, and `1-based (GFF/GTF/VCF)`:

- **Known format by extension** (`.bed`, `.gff`, `.gff3`, `.gtf`,
  `.vcf`): the coordinate system is **fixed by the format
  specification**, and Auto-detect (and any explicit choice) does not
  reinterpret the file: a GFF3 file is always read as 1-based
  inclusive, a BED file always as 0-based half-open.
- **Extension-neutral tables** (`.tsv`, `.txt`, `.csv`, and other
  custom tabular inputs): Auto-detect may infer a known format from the
  content (a BED-like `.tsv` may be read as BED, 0-based). An **explicit
  coordinate declaration takes precedence over that content sniffing**:
  a BED-like `.tsv` declared `1-based (GFF/GTF/VCF)` is shifted as a
  1-based table.
- **Custom tables after column mapping:** the selector *declares* the
  coordinate system, because there is no format to ask. The default
  declaration is **0-based half-open** — if your custom file is 1-based
  (for example a BED-like export from a browser), select
  `1-based (GFF/GTF/VCF)` so the shift is applied.

In short: for ambiguous/custom files, **explicit user intent > heuristic
content detection**; for known format extensions, **format
specification > user coordinate override**. No explicit user
declaration is silently ignored.

## Why touching intervals are not overlaps

Half-open intervals that touch at the same boundary coordinate share no
genomic base:

<!-- BEGIN GENERATED: touching_intervals -->
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query         #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
annotation    .  .  .  .  .  .  .  .  .  .  #  #  #  #  #  [20, 25)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  bases 20–24 (5 bases); boundary coordinates 20 and 25

overlap: no
overlap length: 0
closest distance: 0
```
<!-- END GENERATED: touching_intervals -->

`[10, 20)` covers bases 10–19. `[20, 25)` covers bases 20–24. **No base
belongs to both intervals**, so under the overlap operation they do not
match ([Overlap](../operations/overlap.md)). This is deliberate and
consistent with how BED tools define intersection.

But note the consequence for [closest](../operations/closest.md): the
distance between touching intervals is **0** — there is no base between
them. "Touching is not an overlap" and "touching has distance 0" are
both true at the same time.

## Coordinates in your results and exports

- **CSV / TSV / Excel** exports carry canonical **0-based half-open**
  values in `coord_start/coord_end` and `annot_start/annot_end`. If you
  put GFF3 numbers next to your exported numbers, remember the export
  is *not* in GFF3 convention.
- **Annotated VCF** export is the one place where a format convention is
  reconstructed: `POS = coord_start + 1` (1-based), with matched
  annotations written into `INFO`
  ([Downloading and exporting results](../results/export.md)).

!!! warning "Do not pre-adjust your source coordinates"

    Do not subtract one from GFF numbers (or add one to BED numbers)
    "to make them match" before uploading. AnnotateR applies exactly one
    documented conversion per format at parse time; pre-adjusting your
    file produces a silent off-by-one that no error will catch. Upload
    the file as its format specifies it — and for custom tables, simply
    *declare* the correct coordinate system.

## Where to go next

- [Chromosome identifiers and genome assemblies](chromosome-identifiers.md)
  — assembly-aware chromosome naming, which changes identifiers only,
  never coordinates.
- [Coordinate behavior per format](supported-formats.md) in the format
  reference.
- [Overlap](../operations/overlap.md) and
  [Closest (nearest)](../operations/closest.md) for what the canonical
  model implies for matching.