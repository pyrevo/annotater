# Configuring the analysis

This is the complete tour of the sidebar ("Configure"). The **Run
annotation** button sits at the very top of the page — every option in
the sidebar feeds that one run.

## Sidebar, top to bottom

### Annotation

- **Annotation engine** (radio) — **Bedtools** (default) or
  **Polars-Bio**. Caption: "Bedtools — established command-line
  backend. Polars-Bio — dataframe-based backend." If the selected
  engine is not available in this deployment, a warning names the
  backend and what to do — the app never silently switches engines.
  See [Choosing an annotation engine](engines.md).
- **Operation** (dropdown) — **Overlap** (default), **Contains**,
  **Within**, **Closest**. The caption under the dropdown spells out
  the predicate:
  - Overlap — "Return annotation intervals that overlap each query
    interval"
  - Contains — "Return annotations fully contained within each query
    interval"
  - Within — "Return annotations that fully contain each query
    interval"
  - Closest — "Return the nearest annotation interval(s); all equally
    nearest ties are retained. Overlapping or touching intervals have
    distance 0."
  Full definitions and diagrams:
  [Choosing an operation](../operations/choosing-an-operation.md) and
  the per-operation pages.
- **Join behavior** (radio) — **Keep all query rows (left join)**
  (default) or **Matched rows only (inner join)**. See
  [Join behavior: left vs inner](../operations/join-behavior.md).

### Input options

- **Query coordinates** / **Annotation coordinates** (dropdowns) —
  **Auto-detect** (default), `0-based (BED)`, `1-based (GFF/GTF/VCF)`.
  For files with a known extension (`.bed`, `.gff`, `.gff3`, `.gtf`,
  `.vcf`) the coordinate system is fixed by the format specification
  and the dropdown does not change it. For custom tables and
  extension-neutral files (`.tsv`, `.txt`, `.csv`) an explicit choice
  *declares* the coordinate system and takes precedence over content
  detection; Auto-detect may infer a known format from the content, and
  otherwise a custom table is read as 0-based half-open. The declaration
  is applied exactly once. See [Coordinate systems](../preparing-your-data/coordinate-systems.md).
- **Genome assembly** (searchable dropdown) — starts on *Select genome
  assembly*; nothing is preselected. Choose one of the
  [bundled genome assemblies](../preparing-your-data/bundled-assemblies.md),
  or **Custom chromosome mapping…**, which shows one **Chromosome mapping
  file** uploader for your own `.tsv` table. It is needed only when
  chromosome names are normalized.
- **Chromosome naming** (dropdown) — **Keep original names** (default;
  identifiers are not normalized and no assembly is needed), **UCSC
  names**, **Ensembl names**, **NCBI RefSeq accessions**, **GenBank
  accessions** or **Assembly names**. Each identifier is looked up in the
  selected assembly and renamed only to a verified name of the same
  sequence; coordinates are never changed. See
  [Chromosome identifiers and genome assemblies](../preparing-your-data/chromosome-identifiers.md).

### Feature filter

- **Filter by feature type** (multiselect) — applies to GFF/GTF
  annotation files only. **Default: `gene` only.** Selecting *no*
  feature types includes **all** features ("No feature types selected —
  all features will be included"). See
  [Feature filtering](feature-filtering.md).

### Advanced options (collapsed group)

- **Require query and annotation to have the same explicit strand**
  (checkbox, off by default). When checked, the group label changes to
  **"Advanced options (strand required)"** so the active non-default
  state stays visible even while the group is collapsed. See
  [Strand-aware annotation](../operations/strand-aware.md).
- **Minimum overlap fraction** (slider 0–1, step 0.1, default 0) —
  shown **only when Operation is Overlap**. Help: "Minimum fraction of
  each query interval that must overlap a single annotation interval.
  0 = any positive overlap. Applies to the overlap mode only." See
  [Minimum overlap](../operations/min-overlap.md).

## Options that do not exist in v0.1.0

If you have used other interval tools, note that *none* of these are
available: no operation chaining, no output of non-matching annotation
features, no strand-flip / reverse-complement options, no distance
limit for closest, no merging of duplicate annotations. See
[Limitations](../limitations.md).