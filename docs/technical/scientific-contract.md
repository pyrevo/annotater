# Scientific semantics and engine contract

*Documents the upcoming v0.1.0 release (currently in beta testing; the latest
published pre-release image is `0.1.0-rc2`).*

This page is the **user-facing entry point** to the binding technical
documentation. For developers, scientists reviewing semantics, and CI
maintainers, the authoritative documents live in the
[repository](https://github.com/pyrevo/annotater) — they are linked
here, deliberately *not* republished on this site, so there is exactly
one copy of the truth.

## What binds the product

| Document | What it fixes |
|---|---|
| [`SPEC.md`](https://github.com/pyrevo/annotater/blob/main/SPEC.md) | The normative scientific contract: §4 architectural invariants (canonical input before and canonical output after backend execution, determinism), §5 canonical interval model (0-based half-open, valid intervals, strand, normalization of 1-based source formats), §6 canonical annotation result (`coord_`/`annot_` columns, metadata preservation, deterministic row and column order), §7 join semantics (inner and left; missing-value handling for unmatched rows), §8 operation semantics (overlap, minimum overlap, strand, contains, within, and closest with the canonical distance `max(0, a_start − q_end, q_start − a_end)`), §9 backend requirements (BedtoolsEngine and PolarsBioEngine), §10 testing contract (parity fixtures and comparison) |
| [`docs/engine-contract.md`](https://github.com/pyrevo/annotater/blob/main/docs/engine-contract.md) | The detailed engine-level contract both backends must satisfy, and the allowed/forbidden backend-specific behavior |
| [`docs/architecture.md`](https://github.com/pyrevo/annotater/blob/main/docs/architecture.md) | The result-adapter boundary: why no backend column names leak into the canonical result |

The user-facing pages of this site paraphrase these documents; where
they ever seem to disagree, **the SPEC wins** (see
[AGENTS.md](https://github.com/pyrevo/annotater/blob/main/AGENTS.md)
for the repository's source-of-truth priority order).

## The invariants, in one paragraph

AnnotateR normalizes every input to a canonical 0-based half-open
model at parse time; executes exactly one interval operation on the
selected engine; and returns a canonical result whose columns are
prefixed by provenance (`coord_*` / `annot_*`) with a single canonical
missing value. Both engines — Bedtools and Polars-Bio — are
**contractually required to return identical results** for every
supported operation and option (SPEC §4 and §9, tested under SPEC §10);
that parity is enforced by the test suite, not by hope
([Backend parity and benchmark](../benchmark.md)).

## Where each technical topic lives

- **Interval semantics and operations** → SPEC §5 (interval model) and
  §8 (operations) (paraphrased with diagrams in the
  [Annotation Operations](../operations/choosing-an-operation.md)
  section).
- **Chromosome identity and naming** → SPEC §5.1 and §5.1.1 (assembly
  identity, aliases, custom mappings, VCF `##contig` declarations),
  explained in [Chromosome registries: provenance and audit](chromosome-registry.md)
  and, for users,
  [Chromosome identifiers and genome assemblies](../preparing-your-data/chromosome-identifiers.md).
- **Canonical schema, metadata preservation, missing values** →
  SPEC §6 (result schema) and §7 (join semantics) (paraphrased in
  [Result columns and provenance](../results/result-columns.md)).
- **Parity and performance** → [Backend parity and benchmark](../benchmark.md)
  (the full benchmark methodology is in `docs/benchmark.md` in the
  repo).
- **Deployment, Bedtools availability, TMPDIR, Serve packaging** →
  [Deployment](../deployment.md) (`docs/deployment.md`).
- **External format specifications** (UCSC BED, GFF3, GTF, VCF) →
  [External references](../references.md) (`docs/references.md`).
- **Legacy R implementation and license provenance** →
  [`docs/legacy.md`](https://github.com/pyrevo/annotater/blob/main/docs/legacy.md)
  in the repository (not part of this site).
- **Implementation notes and open items** →
  [`docs/implementation-notes.md`](https://github.com/pyrevo/annotater/blob/main/docs/implementation-notes.md)
  in the repository (a development history, not part of this site).

## How the contract is validated

Backend parity alone is not the only validation: two engines can agree
on the same wrong answer. AnnotateR therefore supplements backend-parity
tests with a test-only brute-force reference implementation of the
documented interval contract on deterministic small fixtures
(`tests/oracle/` in the repository). The reference implementation
imports nothing from the production package; it is plain Python with
explicit loops and the contract formulas written out literally. Both
engines are compared with it row by row (coordinates, metadata, strand,
`has_overlap`, `distance`, null placement, multiplicity and order) on:

- fixed-seed random fixtures (1-8 queries, 1-10 annotations, duplicate
  rows, missing strands, chromosomes without annotations, closest ties)
  across overlap, `min_overlap`, contains, within and closest, inner and
  left, strand off and on;
- hand-computed boundary cases (touching, one-base gaps, exact
  `min_overlap` thresholds, ties, opposite and missing strand);
- parser-to-engine scenarios that start from real BED, GFF3, GTF, VCF and
  custom-table text.

A further test swaps deliberately wrong semantics into the reference
implementation (for example touching counted as overlap) to show that
this comparison can fail. This is empirical validation on small
fixtures; it is not a formal verification and does not claim exhaustive
correctness.

## Documentation governance

- The plan that shaped this site (audiences, sitemap, review record) is
  [`docs/manual-plan.md`](https://github.com/pyrevo/annotater/blob/main/docs/manual-plan.md)
  in the repo — a process document, intentionally excluded from the
  site.
- Semantic changes to any of the linked documents must change the
  application (and its tests) in the same task; the docs in this site
  are updated to follow, never to lead.