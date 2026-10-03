# AnnotateR

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/license/bsd-3-clause)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml/badge.svg)](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml)

AnnotateR is a web application for reproducible annotation of genomic
intervals. It maps a set of query coordinates (BED, VCF, or custom
CSV/TSV tables) against a gene or feature annotation set (GFF3, GTF,
BED, or custom CSV/TSV tables) and produces a canonical result table that can be exported as CSV, TSV,
Excel, or (for VCF queries) annotated VCF. Interval arithmetic runs on
Bedtools or Polars-Bio; the two are interchangeable execution backends
under AnnotateR's canonical semantics.

## Overview

AnnotateR takes two files: a query file of genomic coordinates and an
annotation file of genomic features. For each query it reports the
annotation features that satisfy the selected relation mode
(overlap, contains, within, or closest), with optional explicit
strand-aware matching and a minimum query-overlap fraction (overlap
mode only). Results are computed and exported in a
single canonical coordinate model (0-based half-open intervals), so
output is independent of the source format's coordinate convention.

The execution backend is a runtime choice, not a scientific one: for the
supported operations, Bedtools and Polars-Bio produce equivalent
canonical results for the same input and options, and this parity is
enforced by the test suite rather than assumed.

AnnotateR is available as a hosted web deployment on SciLifeLab Serve
(currently a project-restricted pre-release beta running the
`0.1.0-rc2` image; the latest published image is `0.1.0-rc2`), as a
containerized local application using the published Docker images, and
from source for development.

## Features

- Five input formats: BED, GFF3 and GTF (annotation-only in v0.1.0),
  VCF (query-only in v0.1.0), and custom CSV/TSV tables (a custom query
  table uses explicit column mapping).
- Four relation modes: overlap, contains, within, closest; optional
  modifiers: minimum query-overlap fraction (overlap mode only),
  same-strand matching, and left/inner join behavior.
- Assembly-aware chromosome naming: choose a genome assembly and a naming
  system (UCSC, Assembly, Ensembl, NCBI RefSeq or GenBank), and each
  chromosome identifier is looked up in that assembly's registry and
  renamed only to a verified name of the same sequence. 64 genome
  assemblies of 46 species are bundled offline with pinned, checked
  registries; identifiers that are unknown to the assembly, or that have
  no verified name in the chosen naming, are kept and reported, never
  guessed. For other assemblies, upload a custom chromosome mapping
  (structurally checked, not biologically verified). Only chromosome
  names change, never coordinates, and VCF `##contig` headers follow the
  same renaming.
- A single canonical coordinate model: 1-based formats (GFF3, GTF, VCF)
  are converted at parse time; every operation and export uses
  0-based half-open intervals.
- Interchangeable backends: Bedtools and Polars-Bio produce equivalent
  canonical results on the supported operations (parity is test-enforced).
- CSV, TSV, and Excel export of results; annotated VCF export for VCF
  queries (original record fields and `##` header lines are carried
  forward; `ANNOT_*` INFO fields are added).
- Streamlit web application, containerized with Docker for local use
  and deployment.

## Relation modes and modifiers

All relation modes are supported by both backends; the backend is an
execution choice and does not change the semantics:

| Relation mode | Canonical semantics |
|---|---|
| Overlap | positive half-open overlap |
| Contains | query contains annotation |
| Within | query within annotation |
| Closest | canonical gap distance; all tied-nearest annotations returned |

Modifiers are orthogonal options, not additional relation modes:
`min_overlap` (the minimum query-overlap fraction, overlap mode only),
strand-aware matching (every relation mode; it filters to the same
explicit strand, and a missing strand is never treated as a
wildcard), and left/inner join behavior (result visibility only).
The normative definition of each mode is in
[docs/engine-contract.md](docs/engine-contract.md).

## Getting started

AnnotateR can be used in three ways: the hosted SciLifeLab Serve
deployment (currently a project-restricted pre-release beta), a local
Docker container on your own machine, or from source for development.

### Local Docker container (no account or remote upload required)

SciLifeLab Serve is **not required** to use AnnotateR. Users who prefer
to keep their genomic files within their own computing environment can
run the same AnnotateR application from the published container image:

```bash
docker pull ghcr.io/pyrevo/annotater:0.1.0-rc2

docker run --rm \
  -p 8501:8501 \
  ghcr.io/pyrevo/annotater:0.1.0-rc2
```

`0.1.0-rc2` is the latest *published* pre-release image (source commit
`4edb362e9143286754a41dabeb81f58034f2debc`, digest
`sha256:a0b1b7e8941f0660208d90876a6e0aa3cd73ca9ec5e9704fdb2746c659d1f3f9`).
`main` may contain changes made after it, there is no `latest` tag, and
the final `v0.1.0` release does not exist yet. The earlier `0.1.0-rc1`
remains published as a historical release candidate. Always use an
explicit tag.

Then open <http://localhost:8501>. For local Docker execution, uploaded
files are processed by the AnnotateR container running on the user's own
machine; SciLifeLab Serve is not involved. The image is
`linux/amd64`; at the final `v0.1.0` release the immutable `0.1.0`
image tag replaces the release-candidate tag (image tags and container
deployment are documented in [docs/deployment.md](docs/deployment.md)).

### From source (development)

```bash
git clone https://github.com/pyrevo/annotater.git
cd annotater
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # fully pinned, generated from uv.lock
# or, to install exactly uv.lock: uv sync --frozen
streamlit run streamlit_app/streamlit_app.py
# -> http://localhost:8501
```

Python 3.12; the Bedtools backend additionally requires the `bedtools`
system binary, the Polars-Bio backend does not. A clone-based container
workflow (`docker-compose up --build`) is also provided. Then upload a
query file and an annotation file, choose an operation and options, run
the annotation, and export the result. Full local-installation and
container instructions: [QUICKSTART.md](QUICKSTART.md) (developers) and
the manual ([quick start](docs/getting-started/quick-start.md)).

## Documentation

The user manual is published at <https://pyrevo.github.io/annotater/>
(also in this repository, rooted at [docs/index.md](docs/index.md)).
Notable pages:

- [Quick start](docs/getting-started/quick-start.md)
- [Supported file formats](docs/preparing-your-data/supported-formats.md)
- [Choosing an operation](docs/operations/choosing-an-operation.md)
- [Coordinate systems](docs/preparing-your-data/coordinate-systems.md)
- [Result columns](docs/results/result-columns.md)
- [Limitations](docs/limitations.md)

Technical reference: [SPEC](SPEC.md) (normative contract),
[architecture](docs/architecture.md),
[engine contract](docs/engine-contract.md),
[deployment](docs/deployment.md) (Docker and SciLifeLab Serve).

## Reproducibility and testing

AnnotateR defines a canonical coordinate model and a canonical result
schema; every backend adapter must map its raw output onto that schema,
and the parity harness verifies that both backends return equivalent
canonical results for each supported operation. The full suite (unit,
integration, parity) runs with a single command from the repository
root:

```bash
pytest
```

Continuous integration (
[.github/workflows/python-tests.yml](.github/workflows/python-tests.yml))
runs the full suite on Ubuntu and macOS (Python 3.12), builds the
production image, runs an in-container smoke test, and runs a
deterministic, parity-gated benchmark smoke.

Backend runtime performance is workload-dependent. The benchmark
characterizes both backends under controlled synthetic workloads, with
row counts checked per repetition and strict canonical parity checked
on the final result:
[docs/benchmark.md](docs/benchmark.md) (methodology, environment,
results, reproduction) and `benchmarks/benchmark_engines.py`
(deterministic script).

## Citation

Citation metadata is maintained in [CITATION.cff](CITATION.cff) (version
and release date are recorded when the release is made).

## License

AnnotateR is licensed under the BSD 3-Clause License — see
[LICENSE](LICENSE).

## Authors and contact

- Jyotirmoy Das, Ph.D. — [jyotirmoy.das@liu.se](mailto:jyotirmoy.das@liu.se)
- Massimiliano Volpe, Ph.D. — [massimiliano.volpe@scilifelab.se](mailto:massimiliano.volpe@scilifelab.se)

Questions, bug reports, and feature requests: [GitHub Issues](https://github.com/pyrevo/annotater/issues).