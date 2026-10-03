# Chromosome identifiers and genome assemblies

The same chromosome goes by many names. GRCh38 chromosome 1 is `chr1` at
UCSC, `1` at Ensembl, `NC_000001.11` at NCBI RefSeq and `CM000663.2` at
GenBank. If your query file uses one of these and your annotation file
another, **no interval will match**, because AnnotateR compares
chromosome identifiers as exact strings.

AnnotateR can put both files into one naming system for you. It does this
by **looking each identifier up in a registry of the genome assembly you
select**, never by rewriting text.

## How chromosome normalization works

```text
input chromosome identifier
        ↓
resolve it inside the genome assembly you selected
        ↓
identify one sequence record of that assembly
        ↓
render that record's verified name in the naming system you chose
```

- It is **identifier normalization**, not liftover. Only the chromosome
  identifier can change. `start`, `end`, `strand`, every other column,
  the row order and the row count stay exactly as they were, and the
  genome assembly is not changed.
- **Nothing is guessed.** There is no `chr` prefix rule, no style
  detection and no matching by similarity. An identifier is recognized
  only if the selected assembly's registry lists it, and it is renamed
  only to a name the registry lists for that same sequence.
- Matching is **exact and case-sensitive**. `NC_000001.11` is not
  `NC_000001.10`, and `Chr1` is not `chr1`.
- The same string can mean different sequences in different assemblies,
  or nothing at all. That is why the assembly must be chosen explicitly.

Chromosome normalization runs once, before the interval operation, so
Bedtools and Polars-Bio receive exactly the same normalized tables.

## Step 1 — choose the genome assembly

In the sidebar, **Genome assembly** starts on *Select genome assembly*
and nothing is preselected. Choose the assembly your input files were
made with. It is not inferred from your files and is never defaulted.

- The selector is a searchable list. Click it and type: the filter
  matches the text of the displayed option, which contains the organism
  (for example *Human*, *Mouse*), the assembly name and the UCSC
  database id (for example `hg38`, `mm10`, `canFam3`). Scientific names
  such as *Homo sapiens* are only found where they are part of the label.
- This release bundles **64 genome assemblies of 46 species**. The
  complete list is in [Bundled genome assemblies](bundled-assemblies.md).
- Each bundled assembly has one canonical AnnotateR id and accepts its
  UCSC database id as an alias: for example `GRCh38` / `hg38`, `GRCm38` /
  `mm10`, `GRCm39` / `mm39`, `mRatBN7.2` / `rn7`. They are the same
  assembly under two names, not different assemblies. In the application
  you simply pick the labelled option.
- If your assembly is not in the list, supply your own table instead:
  choose **Custom chromosome mapping…** (see
  [below](#custom-chromosome-mapping)).

!!! note "`hg19` is its own assembly entry"
    The `hg19` entry is not presented as a generic *GRCh37*. UCSC's main
    hg19 mitochondrial sequence (`chrM`) is not the sequence that
    Ensembl's GRCh37 calls `MT` (see
    [the example below](#why-the-assembly-matters-hg19-mitochondria)),
    so AnnotateR keeps UCSC's own `hg19` identity rather than implying
    that the two sequence sets are identical.

## Step 2 — choose the naming system

**Chromosome naming** decides which names the results use:

| Option | Names it produces |
|---|---|
| **Keep original names** | none: identifiers are not normalized (see [below](#keep-original-names)) |
| **UCSC names** | UCSC identifiers, for example `chr1`, `chrM` |
| **Assembly names** | the assembly's own sequence names, where the registry has them |
| **Ensembl names** | Ensembl identifiers, for example `1`, `MT` |
| **NCBI RefSeq accessions** | RefSeq accessions, for example `NC_000001.11` |
| **GenBank accessions** | GenBank / INSDC accessions, for example `CM000663.2` |

Not every sequence of every assembly has a name in every naming system.
UCSC names are available for every bundled assembly; names in the other
systems are available only where the registry holds a verified name (see
[the coverage figures](../technical/chromosome-registry.md#naming-system-coverage)).
AnnotateR never claims complete Ensembl, RefSeq or GenBank coverage.

### Keep original names

With **Keep original names** AnnotateR does not normalize chromosome
identifiers. No genome assembly and no mapping file is required for this,
and none is read. Identifiers and coordinates stay as you supplied them.
This option does **not** check that your identifiers are valid for any
assembly; if the two files name chromosomes differently, rows on
differently named chromosomes will not match.

## What happens to each identifier

Every distinct identifier in each file ends in exactly one of these
outcomes, and the results page reports the ones that need your attention:

| Outcome | What happens | Example |
|---|---|---|
| **Resolved, name available** | renamed to the chosen naming system | `NC_000001.11` → `chr1` (GRCh38, UCSC names) |
| **Already in the chosen naming** | kept; counted as recognized | `chr1` → `chr1` |
| **Recognized, but no verified name in the chosen naming** | **kept as provided** and reported as having *no verified target name* | hg19 `chrM` with Ensembl names |
| **Unknown to the selected assembly** | **kept as provided** and reported as *not recognized* in that assembly | `NC_000001.10` in GRCh38 |

The last two are different situations and are reported separately:

- *Unknown* means the selected assembly's registry does not contain this
  identifier at all. Usually the identifier belongs to another assembly,
  or to a sequence the registry does not cover.
- *Recognized but no target name* means AnnotateR knows exactly which
  sequence this is, but holds no verified name for it in the naming
  system you asked for. It does not invent one.

In both cases the original identifier is left in place, and rows that
carry it can still only match rows with the identical identifier. If
only part of a file is normalized, the result says so; it never presents
unresolved identifiers as normalized.

The examples below are generated from the tested fixtures; they show the
actual behavior of the bundled registries.

Exact accession identity:

<!-- BEGIN GENERATED: chromosome_accession_identity -->
```text
genome assembly: GRCh38
chromosome naming: UCSC names
only chromosome names can change; coordinates and assembly are unchanged

input         output  result
NC_000001.11  chr1    renamed
```
<!-- END GENERATED: chromosome_accession_identity -->

Identifiers of another assembly are not recognized:

<!-- BEGIN GENERATED: chromosome_wrong_assembly -->
```text
genome assembly: GRCh38
chromosome naming: UCSC names
only chromosome names can change; coordinates and assembly are unchanged

input         output        result
NC_000001.10  NC_000001.10  not recognized in GRCh38; kept as provided
chr2L         chr2L         not recognized in GRCh38; kept as provided

recognized in another assembly: NC_000001.10 (hg19), chr2L (dm6)
```
<!-- END GENERATED: chromosome_wrong_assembly -->

### Why the assembly matters: hg19 mitochondria

In UCSC's hg19, `chrM` and `chrMT` are **two different sequence
records**: `chrM` is NC_001807.4 (16,571 bp), and `chrMT` is
NC_012920.1 (16,569 bp), the mitochondrial sequence that Ensembl's
GRCh37 names `MT` (the UCSC alias table lists it as `MT` too). They are
never renamed into each other because their names look alike. With Ensembl names, the pinned
Ensembl evidence identifies `chrMT` as Ensembl's `MT`, so it is renamed;
the hg19 `chrM` has **no verified Ensembl name** and stays unchanged:

<!-- BEGIN GENERATED: chromosome_hg19_mitochondria -->
```text
genome assembly: hg19
chromosome naming: Ensembl names
only chromosome names can change; coordinates and assembly are unchanged

input  output  result
chrM   chrM    recognized; no verified Ensembl name; kept as provided
chrMT  MT      renamed

different sequences: chrM, chrMT
```
<!-- END GENERATED: chromosome_hg19_mitochondria -->

A rule such as "`chrM` is `MT`" would silently merge two different
sequences here. Resolving inside the selected assembly's registry is what
prevents it.

### Not only human

Chromosome names are not always numbers, and not all organisms have
`chr1…chr22`. Each assembly's registry holds its own sequences; for
*Drosophila melanogaster* (dm6) `chr2L` is `2L` in Ensembl naming, and the
mitochondrial `chrM` has no verified Ensembl name:

<!-- BEGIN GENERATED: chromosome_dm6_non_human -->
```text
genome assembly: dm6
chromosome naming: Ensembl names
only chromosome names can change; coordinates and assembly are unchanged

input  output  result
chr2L  2L      renamed
chrM   chrM    recognized; no verified Ensembl name; kept as provided
```
<!-- END GENERATED: chromosome_dm6_non_human -->

Likewise, zebrafish (GRCz11) has chromosomes `1` to `25` and no `X`;
every bundled registry lists only the sequences of its own assembly.

### Several names for one sequence

If two or more different input identifiers are renamed to the same
output identifier, the result reports it instead of hiding it. For an
ordinary annotation table this is informational:

<!-- BEGIN GENERATED: chromosome_many_to_one -->
```text
genome assembly: GRCh38
chromosome naming: UCSC names
only chromosome names can change; coordinates and assembly are unchanged

input  output  result
1      chr1    renamed
chr1   chr1    recognized; already in UCSC naming

merged output name (informational): 1, chr1 → chr1
```
<!-- END GENERATED: chromosome_many_to_one -->

For VCF `##contig` declarations a merge is only allowed when the rest of
the metadata agrees (see [VCF files](#vcf-files)).

### Only the identifier changes

<!-- BEGIN GENERATED: chromosome_coordinates_preserved -->
```text
genome assembly: GRCh38
chromosome naming: UCSC names
only chromosome names can change; coordinates and assembly are unchanged

input         output  result
NC_000001.11  chr1    renamed
NC_000002.12  chr2    renamed

rows before
chr           start  end  strand  name
NC_000001.11  100    200  +       peak1
NC_000002.12  0      50   -       peak2

rows after
chr   start  end  strand  name
chr1  100    200  +       peak1
chr2  0      50   -       peak2
```
<!-- END GENERATED: chromosome_coordinates_preserved -->

## Custom chromosome mapping

If your assembly is not bundled, or your files use names the bundled
registry does not know, choose **Custom chromosome mapping…** in the
**Genome assembly** selector. A single uploader, **Chromosome mapping
file**, appears beneath it and accepts a `.tsv` file. A custom mapping is
a source of chromosome identity; it is **not a genome assembly**, and
reports show it as *Custom chromosome mapping* rather than as an
assembly.

### File format

A plain UTF-8, tab-separated file whose first line is exactly this
header, in this order:

```text
assembly	ucsc	ensembl	genbank	refseq
```

Each following row describes **one sequence**; each column is one naming
system for that sequence. Example (columns are separated by tabs):

```tsv
assembly	ucsc	ensembl	genbank	refseq
1	chr1	1	CM012345.1	NC_012345.1
2	chr2	2	CM012346.1	NC_012346.1
MT	chrM	MT	JX123456.1	NC_099999.1
scaffold_1	scaffold_1		ABCD01000001.1	NW_012345678.1
```

The five columns are the five naming systems of the **Chromosome
naming** control: `assembly` is *Assembly names*, `ucsc` is *UCSC names*,
and so on.

### Rules

- One row is one sequence. There is no sequence id column.
- Cells may be empty (the last row above has no Ensembl name), but every
  row needs at least one name.
- Names are matched **exactly and case-sensitively**, and are never
  trimmed: a name with leading or trailing whitespace is rejected rather
  than silently repaired.
- A name cannot identify two different rows. The same text may appear in
  several columns of the **same** row, as `scaffold_1` does above.
- Identical rows, empty lines, comment lines and control characters are
  rejected. A leading byte-order mark, Windows line endings and a missing
  final newline are accepted.
- No naming convention is imposed: accession-like names, scaffold names
  and any other text are accepted as written.
- The file name means nothing: it is never used to guess an organism,
  assembly or naming system.

### What AnnotateR does and does not check

!!! warning "Structural checks only"
    AnnotateR checks custom mappings for structural consistency, but does
    not independently verify that the supplied biological mappings are
    correct. Whether the names really belong together is your
    responsibility.

Problems that make a file structurally invalid are listed with line
numbers and columns; the file is never repaired.

Once loaded, a custom mapping behaves exactly like a bundled registry:
the same outcomes (renamed, already in the chosen naming, *not
recognized*, *no verified target name*), the same many-to-one reporting
and the same VCF handling. All naming options stay available even when
your file has no names for some of them; sequences without a name in the
chosen naming are reported, not dropped.

### Limits and privacy

- At most **500,000 rows** and **64 MiB** per file. Larger files are
  refused with a message.
- The mapping is held in memory for your session only. It is not saved,
  not shared with other sessions and not added to the bundled data.
- A loaded registry costs memory in proportion to its rows: a synthetic
  stress test with 500,000 rows and all five naming columns kept about
  0.6 GB in memory. That is a worst case, not typical use; realistic
  mappings with hundreds to thousands of rows are tiny.
- Uploads are also subject to the deployment's own per-file upload limit
  (Streamlit's default is 200 MB).

If you selected **Custom chromosome mapping…** and leave the naming on
**Keep original names**, no file is needed and an uploaded file is not
read.

## VCF files

For a VCF query, chromosome normalization applies consistently to the
record `CHROM` values and to the `##contig` header declarations, including
contigs that no record uses. Each declared contig identifier is looked up
in the same registry, with the same naming system, as the records:

| Declared contig | Result |
|---|---|
| resolved, name available | renamed (`##contig=<ID=1,…>` → `##contig=<ID=chr1,…>` for GRCh38 with UCSC names) |
| unknown to the assembly | kept as declared |
| recognized, no verified name in the chosen naming | kept as declared |

The other attributes of a declaration (`length`, `md5`, …) are carried
over unchanged, and the header is never re-sorted.

If several declarations are renamed to the **same** identifier:

- all their remaining metadata are equivalent: they are merged into one
  declaration;
- their metadata conflict (for example different `length` values): the
  annotated VCF export is **blocked with an explicit message** naming the
  contigs and the conflicting attributes. AnnotateR does not choose one
  silently.

With **Keep original names** the VCF header is left exactly as provided.

## Reproducibility and offline use

Chromosome normalization **never contacts the network**. The registries
of the bundled assemblies ship inside AnnotateR, so the same assembly,
naming and input give the same result at any time, offline or in a
closed deployment, and a custom mapping is read only from the file you
upload. AnnotateR's own tooling that *builds* the registries needs
network access when maintainers refresh the sources; the application you
run does not. Where the registries come from and how they are checked is
described in [Chromosome registries: provenance and audit](../technical/chromosome-registry.md).

## What the bundled registries cover

A bundled registry lets AnnotateR normalize the **verified identifiers
present in that registry**. It does not mean that every possible sequence
name for the species is known: some UCSC databases list only a few
sequences in the authoritative alias source, and sequences of an
assembly that the source does not list are reported as not recognized.
That is deliberate: AnnotateR reports what it can verify.

## Common messages

| What you see | Meaning and fix |
|---|---|
| "Select the genome assembly before normalizing chromosome names." | a naming other than **Keep original names** needs an assembly (or a custom mapping). Choose one, or keep the original names. |
| "Upload a chromosome mapping file before normalizing chromosome names." | **Custom chromosome mapping…** is selected but no file is uploaded. |
| "The chromosome mapping file is not valid…" with a list | the file failed the structural checks. Each entry names the line and column; fix the file and upload it again. |
| "Not recognized in *assembly*: …" | those identifiers are not in the selected assembly. Check the assembly choice, or use a custom mapping. |
| "Recognized, but no verified name is available in *naming*: …" | the sequence is known, but the registry has no name for it in that naming system. Choose another naming, or supply a custom mapping. |
| "Annotated VCF export is unavailable…" | contig declarations that were renamed to one identifier disagree. Fix the VCF header. |
| "No shared chromosome identifiers remain between query and annotation data." | after normalization the two files still share no identifier. Check the assembly and naming. |

See also [Troubleshooting](../troubleshooting.md#zero-matches).
