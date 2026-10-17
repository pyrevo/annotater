# AnnotateR

**AnnotateR** is a free web application that maps genomic coordinates to
gene features. Upload your genomic coordinates and annotate them against
gene annotation files, gaining insights into genomic regions of interest
through a web interface.

- **File formats:** BED · GFF3 · GTF · VCF · CSV/TSV (custom tables)
- **Relation modes:** overlap, contains, within, closest —
  with optional minimum query-overlap fraction and strand-aware
  matching
- **Backends:** Bedtools (command-line) and Polars-Bio (dataframe),
  interchangeable and producing the same canonical result
- **Runs locally or as a deployed service** — uploaded files are
  processed by the running AnnotateR server; temporary parsing files are
  deleted immediately after parsing, and parsed data and results remain
  only in application memory for the active session
  ([data handling](limitations.md#data-handling))

## Where to start

- **New here?** Read [What is AnnotateR?](getting-started/what-is-annotater.md)
  and then the [Quick start](getting-started/quick-start.md).
- **Running it locally?** Developers should follow
  [QUICKSTART.md](https://github.com/pyrevo/annotater/blob/main/QUICKSTART.md)
  in the repository.

## The three topics users land on most

| You want to… | Go to |
|---|---|
| Know which files you can upload | [Supported file formats](preparing-your-data/supported-formats.md) |
| Pick the right annotation operation | [Choosing an operation](operations/choosing-an-operation.md) |
| Read the result table | [Understanding the results page](results/results-page.md) |

## Example

The repository ships tiny example files you can use to try the app:

- [`data/examples/example_coordinates.bed`](https://github.com/pyrevo/annotater/blob/main/data/examples/example_coordinates.bed)
  (query regions) and
  [`data/examples/example_annotations.gff3`](https://github.com/pyrevo/annotater/blob/main/data/examples/example_annotations.gff3)
  (gene/exon annotations).

See the [Examples](examples/bed-vs-gff3.md) section for five complete,
deterministic walkthroughs.

## Documentation

This site is the user manual for the upcoming AnnotateR v0.1.0 release
(currently in beta testing; the latest published pre-release image is
`0.1.0-rc3`, and these pages describe the current `main`, which may be
ahead of it).
Technical and developer material (architecture, engine contract,
benchmark, deployment) lives in the
[Technical Reference](technical/scientific-contract.md) section and in
the [repository](https://github.com/pyrevo/annotater).

## Citing AnnotateR

If AnnotateR supports your work, please cite it. The project is archived
on Zenodo; the Concept DOI always resolves to the latest published
release:

> Das, J., & Volpe, M. (2026). AnnotateR [Computer software]. Zenodo.
> <https://doi.org/10.5281/zenodo.23415801>

To cite the current release candidate specifically, use the version DOI
`10.5281/zenodo.23415802`
(<https://doi.org/10.5281/zenodo.23415802>). The in-app **Cite
AnnotateR** button copies the Concept DOI form. Machine-readable metadata
is maintained in
[`CITATION.cff`](https://github.com/pyrevo/annotater/blob/main/CITATION.cff).