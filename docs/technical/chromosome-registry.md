# Chromosome registries: provenance and audit

This page is for scientists and maintainers who want to know where the
chromosome registries come from, how they are checked, and why this
release bundles the assemblies it does. For using chromosome
normalization, see
[Chromosome identifiers and genome assemblies](../preparing-your-data/chromosome-identifiers.md).

## The model

Chromosome normalization is alias resolution inside one explicitly
selected registry: an identifier is resolved to one sequence record, and
a verified name of that same record is rendered for the chosen naming
system. A registry is either a bundled genome assembly or a user-supplied
custom mapping; both run through the same code. The normative contract is
SPEC §5.1 and §5.1.1 in the
[repository](https://github.com/pyrevo/annotater/blob/main/SPEC.md).

## Assembly identities

Every bundled assembly has one **canonical id** (the identity a loaded
registry reports), its **UCSC database id**, and accepted aliases. Both
the canonical id and the aliases load the same registry. All names are
globally unambiguous, also when compared case-insensitively, and the
catalog is rejected at generation and at load otherwise.

The canonical id is the UCSC database id unless a reviewed list names a
published assembly name (for example `GRCh38` for `hg38`, `GRCm38` for
`mm10`, `mRatBN7.2` for `rn7`). A name is accepted only if UCSC's own
description of that database contains it verbatim as its
`(<name>/<database>)` token, so no name is invented and no free text is
parsed. `hg19` deliberately keeps its UCSC identity rather than becoming
`GRCh37`: UCSC's hg19 main mitochondrial sequence (`chrM`,
NC_001807.4) is not the sequence Ensembl's GRCh37 calls `MT`
(NC_012920.1, which the hg19 registry holds as the separate record
`chrMT`).

## Where the registry data come from

- **UCSC `chromAlias` tables.** Each bundled registry is generated from
  the UCSC `chromAlias` database table of its assembly, which lists the
  alternative names of every sequence and the naming system of each.
- **Pinned evidence where the table is incomplete.** For hg19 and rn7
  the Ensembl names are added from pinned Ensembl database tables, joined
  only by exact versioned accession (never by name similarity). A small
  number of explicitly reviewed label corrections are recorded with their
  rationale.
- **Checksums and determinism.** Every source file is pinned by SHA-256,
  generation is deterministic, and the registry builder refuses
  conflicting or duplicate aliases rather than correcting them.
- **Independent verification.** A separate test-only oracle derives the
  expected aliases of every bundled assembly directly from the pinned
  sources, without using the generated registries or the runtime code,
  and the generated registries must match it exactly.

The registries ship with the application. The running application never
fetches anything: normalization is offline and reproducible. Only the
maintainers' update tooling, which regenerates registries from the pinned
sources, uses the network, and only when asked to refresh them.

## Catalog audit and what is bundled

Before choosing the bundle, every database of the UCSC genome catalog was
audited to find out how well the registry model can represent its
`chromAlias` source. The figures below are generated from the committed
audit.

<!-- BEGIN CATALOG: catalog_audit -->
Audit of 2026-10-02 against the UCSC genome catalog.

| | Count |
|---|---|
| UCSC genome databases audited | 238 |
| …with a database `chromAlias` source | 132 |
| …representable cleanly by the current architecture | 122 |
| …requiring review | 5 |
| …failing the current representation | 5 |
| …with no database `chromAlias` source | 106 |
| **Bundled in this release** | **64 assemblies, 46 species** |
| …selected by the bundling policy | 63 |
| …reviewed exception (`hg19`, one of the databases requiring review) | 1 |
| Clean assemblies not bundled (above the size limit) | 59 |

The bundling policy selects every cleanly representable assembly with at most 10,000 sequence records, plus the reviewed exception. Registries for all 122 clean assemblies would total about 530.1 MB of registry text (77.4 MB compressed); the bundled registries total about 13.7 MB.
<!-- END CATALOG: catalog_audit -->

Two numbers must not be confused:

- **Architecture audit coverage** says how many UCSC databases the
  registry model can represent cleanly. This is a statement about the
  design, not about what is installed.
- **Bundled runtime support** is the set of assemblies actually shipped in
  this release. Only those can be selected as a genome assembly.

The bundled set is smaller than the audited set because the release
applies a reproducible policy instead of shipping every compatible
registry. Highly fragmented assemblies can contain hundreds of thousands
of sequence records (the largest clean one lists over 600,000). Bundling
all of them would substantially increase the package size and the
memory a registry needs at run time, so this release bundles the cleanly
representable assemblies with at most 10,000 sequence records, plus
`hg19`, which was reviewed for inclusion. Databases that required review,
failed the current representation, or have no `chromAlias` source are not
imported automatically. For an assembly outside the bundle, use a
[custom chromosome mapping](../preparing-your-data/chromosome-identifiers.md#custom-chromosome-mapping).

The audit report and its method are in
[`audits/chrom_alias_catalog/`](https://github.com/pyrevo/annotater/tree/main/audits/chrom_alias_catalog)
in the repository.

## Naming-system coverage

UCSC names exist for every bundled registry; other naming systems depend
on what the source lists, so coverage is partial by design. A sequence
without a verified name in the requested naming system is reported as
having no verified target name; AnnotateR never fills the gap.

<!-- BEGIN CATALOG: authority_coverage -->
| Naming system | Bundled registries with at least one name |
|---|---|
| UCSC names | 64 of 64 |
| Assembly names | 10 of 64 |
| Ensembl names | 42 of 64 |
| NCBI RefSeq accessions | 49 of 64 |
| GenBank accessions | 50 of 64 |
<!-- END CATALOG: authority_coverage -->

## Narrow registries

A registry covers only the sequences its authoritative source lists. Some
UCSC databases list very few, so selecting such an assembly lets you
normalize those verified identifiers; every other identifier is reported
as not recognized. Such registries are correct but narrow.

## Worked examples

The chromosome examples in the user guide are generated from tested
fixtures. The fixtures, and how they are verified against the pinned
upstream data and the real normalization, are described in the
maintainer page
[`docs/semantic-examples.md`](https://github.com/pyrevo/annotater/blob/main/docs/semantic-examples.md)
in the repository.
