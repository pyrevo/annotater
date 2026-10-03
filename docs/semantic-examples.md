# Semantic interval examples (developer guide)

The small interval diagrams in the user manual are generated from
declarative fixtures so they cannot drift from the scientific contract.
This page is for maintainers; it is excluded from the published site.

## Three separate concerns

| Concern | Where it lives | Rule |
|---|---|---|
| Scientific truth | `tests/oracle/test_semantic_examples_oracle.py` against `tests/oracle/reference.py` | The only layer that evaluates expected values. |
| Rendering contract | `scripts/generate_semantic_examples.py` (`KINDS`, `MAX_WIDTH`, labels, legend, grammar) and `tests/test_semantic_examples_rendering.py` | Presentation only. The renderer displays declared values and never computes or infers them. |
| Human prose | The Markdown pages around the blocks | Hand-written. Never generated. |

## Adding or changing an example

1. Add an entry to `tests/fixtures/semantic_examples.json` with a `kind`
   (`overlap`, `one_base_overlap`, `touching`, `closest`, `closest_tie`,
   `contains`, `within`, `min_overlap`, `strand`, or `chromosome_naming`,
   described at the end of this page). The kind fixes which
   facts must be declared and the order they are shown in; a missing
   required fact fails validation.
2. Declare every expected value in the fixture (including per-candidate
   distances for `closest_tie`). The oracle test checks them.
3. Place a pair of marker lines in a docs page: a line
   `<!-- BEGIN GENERATED: <name> -->` followed by a line
   `<!-- END GENERATED: <name> -->`, with the name of the fixture.
   Each name may appear once per page.
4. Run `python scripts/generate_semantic_examples.py`, then
   `python scripts/generate_semantic_examples.py --check`.

Only text between the marker lines is ever replaced. Generated lines must
stay within `MAX_WIDTH` characters; a wider fixture fails instead of
wrapping, so choose a more compact one.

## When manual visual review is still expected

- a new `kind` or a new diagram layout is introduced;
- the renderer's layout rules, labels, legend or `MAX_WIDTH` change;
- the docs theme or CSS changes (`mkdocs.yml`, `docs/assets`).

Routine fixture additions that pass the rendering-contract tests do not
need a full manual review of every page. Preview with `mkdocs serve`
when a review is required.

## Chromosome-naming examples

Kind `chromosome_naming` declares chromosome-name normalization facts
(assembly, target naming, identifiers, per-identifier outcome and output)
instead of intervals. Its facts are verified against pinned upstream data
(`tests/oracle/test_chromosome_semantic_examples.py`) and the real
normalization (`tests/test_chromosome_semantic_examples.py`). These blocks
are shown on this maintainer page and in the user guide
(`docs/preparing-your-data/chromosome-identifiers.md`), which embeds the
same generated blocks between the same markers.

Exact accession identity (GRCh38, UCSC names):

<!-- BEGIN GENERATED: chromosome_accession_identity -->
```text
genome assembly: GRCh38
chromosome naming: UCSC names
only chromosome names can change; coordinates and assembly are unchanged

input         output  result
NC_000001.11  chr1    renamed
```
<!-- END GENERATED: chromosome_accession_identity -->

hg19 `chrM` and `chrMT` are different sequences (Ensembl names):

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

Non-human naming (dm6, Ensembl names):

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

Identifiers that belong to another assembly are not recognized:

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

Two input names can share one output name (informational):

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

Only the chromosome name changes; coordinates, strand and metadata do not:

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
