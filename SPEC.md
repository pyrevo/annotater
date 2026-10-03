# AnnotateR Specification

**Status:** Release-candidate specification for v0.1.0 (normative scientific and backend contract)  
**Project:** AnnotateR  
**Canonical repository slug:** `annotater`  
**Last updated:** 2026-09-24

## 1. Purpose

AnnotateR is a Streamlit application for annotating genomic coordinates against genomic feature sets. The application supports multiple input formats and exposes interchangeable genomic interval backends.

The purpose of this contract is to make backend choice an implementation detail: for operations declared equivalent by this specification, the Bedtools and Polars-Bio engines must produce the same **AnnotateR canonical result**, independent of backend-specific schemas, suffixes, ordering, null sentinels, or dataframe implementation.

## 2. Normative language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative requirements.

This specification is the source of truth for backend and scientific behavior. `docs/references.md` records authoritative external manuals. When implementation behavior and this specification disagree, the discrepancy MUST be resolved explicitly; agents MUST NOT silently redefine the contract from whichever backend currently passes.

## 3. Scope

### 3.1 In scope

- deterministic parsing and normalization of supported genomic interval inputs;
- chromosome naming normalization;
- coordinate-system normalization;
- backend-independent annotation-engine interface;
- Bedtools and Polars-Bio backend parity;
- deterministic canonical output schema;
- differential/parity tests;
- Streamlit integration after backend parity is established;
- SciLifeLab Serve deployment compatibility.

### 3.2 Out of scope for the first parity milestone

- redesigning the user interface;
- adding new biological annotation sources;
- benchmarking as a substitute for correctness;
- replacing both backends with a third implementation;
- changing scientific semantics merely to match current accidental output;
- optimizing Polars-Bio parsing before engine parity is established.

## 4. Architectural invariants

1. **Parsing and annotation are separate concerns.** Backend selection MUST NOT silently select a different parser unless explicitly specified and tested.
2. **Canonical normalized input precedes backend execution.** Both engines MUST receive semantically equivalent normalized interval tables.
3. **Canonical output follows backend execution.** Backend-native column names and null conventions MUST NOT leak into user-visible output.
4. **Correctness precedes performance.** Optimization MUST NOT weaken parity tests.
5. **Bedtools is a reference implementation, not an infallible specification.** Boundary behavior and coordinate conversion MUST be validated against documented genomic interval semantics.
6. **Determinism is required.** Equivalent runs with identical inputs and options MUST produce equivalent canonical tables and deterministic row ordering.

## 5. Canonical interval model

Internally, interval operations MUST use one documented coordinate convention. The target convention for the backend contract is:

- chromosome: string;
- start: integer, **0-based inclusive**;
- end: integer, **0-based exclusive**;
- valid interval: `start >= 0` and `end > start`;
- strand: optional `+`, `-`, or missing;
- metadata: preserved separately from the interval keys.

Format-specific coordinates MUST be normalized before engine execution. BED already follows 0-based half-open semantics. GFF/GTF and ordinary VCF positions are 1-based in their source formats and MUST be converted according to their documented semantics before entering the canonical interval model.

The implementation MUST contain boundary tests capable of detecting one-base coordinate errors.

### 5.1 Chromosome identifier normalization

Chromosome identifier normalization is **alias resolution within an explicit genome assembly**. It is not string rewriting. Conceptually: an input identifier is resolved within one assembly to one sequence record, and a verified alias of that same record is rendered for the requested naming authority (for example UCSC, Ensembl, RefSeq, GenBank, assembly-native).

1. **Assembly-aware identity.** Sequence identity is defined by the selected assembly's version-controlled alias registry. Two identifiers denote the same sequence only if the registry places them on the same record of that assembly. The same string MAY denote different sequences, or no sequence, in different assemblies. In particular, a mitochondrial sequence MUST NOT be assumed identical across assemblies or assembly-naming families merely because the names match (UCSC `hg19` `chrM` is not assumed equivalent to GRCh37 `MT`).
2. **No liftover.** Normalization MUST NOT change the genome assembly, perform liftover, or convert coordinates, and MUST NOT imply that a naming conversion changes biological coordinates.
3. **Coordinate invariant.** For normalization, only the chromosome identifier MAY change. `start`, `end`, `strand`, all other fields, row order, and row count MUST NOT change (unless another independently specified operation modifies them).
4. **No guessing.** Aliases MUST NOT be invented by syntactic rules such as `N` → `chrN` or `chrX` → `X`. A relationship exists only if it is verified in the selected assembly's registry.
5. **Exact resolution.** Identifier matching is exact (case-sensitive; no trimming beyond what parsers already specify). Accession versions are biologically meaningful: `NC_000001` MUST NOT resolve as `NC_000001.11`.
6. **Missing target alias.** A sequence MAY resolve while the registry holds no alias for the requested target authority. This MUST be reported distinctly from an unknown identifier (reason `no_alias_for_target`), and no replacement MAY be invented.
7. **Unknown identifiers.** Unknown or custom identifiers remain unresolved and MUST NOT be reported as validated.
8. **Partial resolution.** A dataset MAY contain resolvable and unresolvable identifiers. Resolved rows MAY be normalized while unresolved identifiers remain unchanged, provided the result carries structured unresolved status (identifier, reason, affected row count). Unresolved identifiers MUST NOT be indistinguishable from successfully normalized ones.
9. **Assembly requirement.** The assembly MUST NOT be silently defaulted (for example to GRCh38) or guessed. If the identifiers need no normalization, no assembly is required to run the rest of AnnotateR. If an alias conversion is requested or required, the assembly MUST be explicit.
10. **Runtime determinism.** Runtime normalization MUST NOT use the network. It MUST depend only on version-controlled registry resources whose upstream sources, checksums and provenance are recorded.
11. **Naming-style detection is advisory.** Any UCSC/Ensembl/NCBI-style detection is user-experience metadata only. It MUST NOT establish sequence identity or drive a conversion independently of the registry.
12. **Registry build-time integrity.** A registry builder MUST fail (not silently correct) on conflicting or duplicate aliases, on more than one alias per sequence per rendered authority in a representation that cannot hold them, and on upstream data whose checksum differs from the pinned value unless an explicit update is requested.
13. **Collapse.** If two or more distinct source identifiers are rendered to the same target identifier, normalization MUST report it (source identifiers per target). Exports that carry per-identifier metadata (for example VCF `##contig` declarations) MAY merge the colliding declarations only if all their attributes other than the identifier are identical; otherwise they MUST fail with the conflicting attributes identified, and MUST NOT silently keep one declaration or discard metadata.
14. **Bundled assembly identity.** Every bundled assembly has exactly one canonical id (the identity a loaded registry reports), its UCSC database id, and zero or more further accepted aliases. The canonical id is the UCSC database id unless a reviewed policy names a published assembly name that appears verbatim as the `(<name>/<db>)` token of UCSC's own description for that database; names MUST NOT be invented or parsed from other prose. Names (canonical ids and aliases) MUST be globally unambiguous, including case-insensitively; catalog generation and loading MUST fail otherwise. Loading by an alias MUST return the same registry, carrying the canonical id, as loading by the canonical id. Identifiers previously accepted MUST remain accepted (as canonical ids or aliases). A name is matched exactly (case-sensitive) and an unknown name is an error; no assembly is guessed from a near match.
15. **VCF contig declarations.** When chromosome naming normalization is active, every `##contig` declaration of the VCF header is resolved and rendered independently through the selected registry and target, exactly like a data-row identifier, including declarations for contigs that no row uses. Unknown identifiers and sequences without a verified target alias remain as declared and MUST NOT make the export fail. Declarations that normalize to the same identifier MAY merge only when all their remaining attributes are equivalent, whether or not any row uses them; otherwise export MUST fail explicitly (item 13). When names are kept as provided, the header is not touched.

#### 5.1.1 Custom chromosome mappings

A user MAY supply their own chromosome mapping instead of selecting a bundled assembly. A custom mapping is a source of chromosome identity, **not** a genome assembly. It MUST obey items 2 to 9 and 13 above and is resolved and rendered by the same runtime resolver and normalizer as a bundled registry; the normalization code MUST NOT branch on where a registry came from.

1. **Schema.** A UTF-8 tab-separated file with exactly the header `assembly`, `ucsc`, `ensembl`, `genbank`, `refseq`, in that order. One row is one sequence; each cell is the name of that sequence in one naming system, or empty. Each row MUST carry at least one name.
2. **No user-facing sequence id.** The user supplies no `seq_id`. Records receive opaque, deterministic internal ids in file row order (`custom:000001`, ...) that are never parsed for meaning and never shown as a user concept.
3. **Exact identifiers.** Names are matched exactly and case-sensitively. They MUST NOT be trimmed, case-folded or inferred; a name with leading or trailing whitespace is rejected rather than repaired. Only a leading byte-order mark, CRLF line endings and a missing final newline are tolerated.
4. **Structural validation only.** The loader MUST reject: a wrong header, a wrong field count, an empty row, a row without a name, control characters, comment lines, duplicate rows, a name that identifies two different rows, invalid UTF-8, and input over the resource limits. It MUST report these with line numbers and columns, without silent repair. It MUST NOT impose accession-shape, naming-syntax, provenance or source-label rules, so non-model and non-standard identifiers are valid.
5. **No biological certification.** AnnotateR verifies that a custom mapping is structurally unambiguous. It does not, and MUST NOT claim to, verify that the names are biologically correct, and user interfaces MUST say so.
6. **Same semantics.** Unknown identifiers, `no_alias_for_target`, partial resolution and collapse are reported exactly as for bundled registries.
7. **Identity in reports.** A custom registry has no assembly id. Reports MUST identify it as "Custom chromosome mapping" and MUST NOT present any genome assembly identity for it.
8. **Resource limits.** Loading MUST refuse input above configurable limits before it is parsed (defaults: 500,000 sequences and 64 MiB).
9. **Offline and scoped.** Loading a custom mapping MUST NOT use the network. Custom data are scoped to the workflow or session that supplied them: they MUST NOT be persisted, shared between sessions, written to the bundled registry data, or listed in the bundled catalog. A change of the mapping content MUST invalidate every result derived from the previous content; the file name carries no meaning.
10. **Explicit source.** Selecting a custom mapping is an explicit chromosome source in the sense of item 9 above. As for a bundled assembly, no mapping is required, read or validated when names are kept as provided.

The former `ChromosomeMapper` (a fixed UCSC/Ensembl style converter) predated this contract and has been retired; the registry-backed implementation replaced it.

## 6. Canonical annotation result

For pair-producing operations, the public result MUST distinguish query (`coord_`) and annotation (`annot_`) fields explicitly.

Required core columns:

```text
coord_chr
coord_start
coord_end
annot_chr
annot_start
annot_end
has_overlap
```

Additional input metadata MUST be preserved deterministically as:

```text
coord_<original_name>
annot_<original_name>
```

Rules:

- `coord_*` columns originate only from the coordinate/query input.
- `annot_*` columns originate only from the annotation/reference input.
- suffixes generated by external libraries (for example `_1`, `_2`, `_right`) MUST NOT appear in canonical output.
- column order MUST be deterministic.
- row order MUST be deterministic and documented.
- duplicated input rows MUST not be accidentally collapsed.
- one query matching multiple annotation records MUST yield one canonical row per match unless an operation explicitly specifies distinct-query output.

## 7. Join semantics

### 7.1 Inner overlap

`how="inner"` MUST return only query/annotation pairs with a valid overlap under the selected options.

### 7.2 Left overlap

`how="left"` MUST preserve every input query row.

- A query with N annotation matches MUST produce N rows.
- A query with no annotation match MUST produce exactly one row with its `coord_*` values preserved, annotation fields represented using the canonical missing-value convention, and `has_overlap == False`.
- Rows with a match MUST have `has_overlap == True`.

This contract corresponds conceptually to the behavior required from a left outer genomic intersection and MUST NOT be approximated by “return only overlapping left rows”. In closest mode (SPEC 8.6), “match” means an attached nearest annotation (possibly separated); `has_overlap` there is the attachment flag, not an overlap predicate.

## 8. Operation semantics and milestone gating

### 8.1 Overlap

Overlap is the first parity target. A positive-width intersection of at least one base is required unless a stricter overlap threshold is requested.

### 8.2 Minimum overlap

`min_overlap` is the **minimum fraction of the canonical query interval covered by a single annotation interval** for that query/annotation pair to qualify as a match. The definition is backend-independent; backend-specific fraction options (for example bedtools `-f`/`-F`/`-r`/`-e`) MUST NOT redefine it.

For a query interval `Q=[q_start, q_end)` and an annotation interval `A=[a_start, a_end)` (canonical 0-based half-open):

```text
overlap_length = max(0, min(q_end, a_end) - max(q_start, a_start))
query_length   = q_end - q_start
query_overlap_fraction = overlap_length / query_length
```

The pair qualifies iff:

```text
overlap_length > 0
AND query_overlap_fraction >= min_overlap
```

- The denominator is the **query** interval length. The parameter is NOT the annotation fraction, NOT reciprocal overlap, and NOT "either side" overlap; annotation coverage is never measured. A small annotation fully covering a large query scores against the query length, not its own.
- The threshold comparison is inclusive (`>=`).
- Each query/annotation pair is evaluated independently; coverage accumulated across multiple annotation rows MUST NOT be summed to satisfy the threshold.
- Valid values: `None` (no fractional threshold; ordinary positive overlap) or a numeric value in `[0, 1]` (int or float; integers `0`/`1` are valid numeric equivalents). `0` is equivalent to ordinary positive overlap: touching intervals (overlap 0) never match at any threshold. Negative values, values above 1, NaN, infinities, booleans, and non-numeric types MUST be rejected with an explicit validation error before backend execution and MUST NOT be clamped or forwarded to a backend.
- The threshold participates in match determination: in left mode, a query whose annotation matches all fail the threshold is unmatched (exactly one unmatched row, `has_overlap=False`, no failing match row), and a query with at least one qualifying match emits only its qualifying matches.

### 8.3 Strand

`use_strand` is a boolean with one normative, backend-independent meaning (fixed in Task 6B):

- `use_strand=False`: strand MUST NOT participate in match qualification. A query/annotation pair may match based solely on the selected interval predicate and other active options.
- `use_strand=True`: a pair qualifies only if the interval predicate qualifies AND
  1. both rows have an explicit canonical strand;
  2. the query strand is `"+"` or `"-"`;
  3. the annotation strand is `"+"` or `"-"`;
  4. the query strand equals the annotation strand.

Missing/unknown strand — canonical missing, a source `"."` after normalization, or an absent strand column on either input — is NOT a wildcard and NOT a strand: a row with unknown/missing strand can never form a stranded match, and unknown-vs-unknown is NOT a match. This behavior MUST be identical for both engines and MUST NOT be defined by any backend-native option (for example bedtools `-s`).

`use_strand` composes with `min_overlap` by logical AND; neither option bypasses the other. In left mode, a query whose geometrical overlaps all fail the strand predicate is unmatched exactly once per SPEC 7.2; a query with at least one qualifying match emits only its qualifying matches.

Canonical strand values other than `"+"`, `"-"`, or missing MUST be rejected with an explicit validation error before backend execution.

### 8.4 Contains (fixed in Task 6C)

`mode="contains"` means **the query interval fully contains the annotation interval**.

For canonical half-open intervals:

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)

contains(Q, A) =
    q_start <= a_start
    AND
    q_end >= a_end
```

- Directionality is fixed: the query is the containing interval and the annotation is the contained interval. The reverse relation (annotation contains query) MUST NOT qualify; it belongs to `within`.
- Boundary equality counts: identical intervals qualify, as do shared left/right boundaries (`q_start == a_start` with a strictly larger query end, or `q_end == a_end` with a strictly smaller query start).
- Partial overlaps and boundary-touching (non-overlapping) intervals MUST NOT qualify. Canonical intervals are valid and non-empty, so full containment already implies a positive overlap; no additional overlap condition is required.
- Chromosome identity is part of candidate generation: pairs on different chromosomes never qualify.
- `contains` is explicitly NOT `min_overlap = 1.0` (8.2). `min_overlap` measures the fraction of the query interval covered by a single annotation and is defined only for the overlap method; containment constrains both annotation boundaries against the query. Neither predicate implies the other:

```text
Q [10,20), A [0,100):  overlap + min_overlap = 1.0 qualifies; contains does NOT
Q [0,100), A [10,20):  contains qualifies; overlap + min_overlap = 1.0 does NOT
```

- `min_overlap` MUST NOT be applied in `contains` mode. A `mode="contains"` query uses the containment predicate plus orthogonal filters (strand, 8.3) only.
- `use_strand` composes with `contains` by logical AND (8.3): a contained pair must also satisfy the strand predicate when `use_strand=True`, and missing/unknown strand is not a wildcard.
- `how="inner"` emits one canonical row for every qualifying query/annotation pair (zero rows when none qualify). `how="left"` follows 7.2: every query row survives, a query with qualifying annotations emits exactly one row per qualifying annotation, and a query with zero qualifying annotations emits exactly one unmatched row (`has_overlap == False`, annotation fields canonical missing). Overlapping-but-not-contained annotations and annotations that contain the query do not count as matches.
- The predicate is evaluated after canonicalization on both engines; `contains` MUST NOT be implemented as unfiltered ordinary overlap, and MUST NOT be delegated to a backend-native containment/fraction option whose direction is backend-defined.

### 8.5 Within (fixed in Task 6D)

`mode="within"` means **the query interval is fully contained within the annotation interval**.

For canonical half-open intervals:

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)

within(Q, A) =
    a_start <= q_start
    AND
    a_end >= q_end
```

- Directionality is fixed: the **annotation** is the containing interval and the **query** is the contained interval. The reverse relation (query contains annotation) MUST NOT qualify; it belongs to `contains` (8.4). `within` MUST NOT be treated as an alias of `contains`.
- `contains` and `within` are directional inverses with respect to the query/annotation roles: `within(Q, A) == contains(A, Q)`. Equivalently, `contains(Q, A)` constrains `q_start <= a_start AND q_end >= a_end`, while `within(Q, A)` constrains the opposite way. Identical intervals satisfy BOTH relations, because equal intervals contain each other.
- Boundary equality counts: identical intervals qualify, as do shared left/right boundaries (`a_start == q_start` with a strictly larger annotation end, or `a_end == q_end` with a strictly smaller annotation start).
- Partial overlaps and boundary-touching (non-overlapping) intervals MUST NOT qualify. Canonical intervals are valid and non-empty, so full containment already implies a positive overlap; no additional overlap condition is required.
- Chromosome identity is part of candidate generation: pairs on different chromosomes never qualify.
- `within` is explicitly NOT `min_overlap` (8.2). `min_overlap` is a query-relative coverage threshold defined for the overlap method; `within` is a positional containment predicate constraining both annotation boundaries against the query. The predicates are distinct, and a query-fraction threshold can pass while `within` fails:

```text
Q [10,20), A [5,15):  overlap + min_overlap=0.5 qualifies; within does NOT
Q [10,20), A [0,100): within qualifies; and (for the same pair) min_overlap=1.0 also qualifies
Q [0,100), A [10,20): contains qualifies; within does NOT
```

  `within` MUST NOT be inferred from any overlap percentage (nor from a backend fraction option), and MUST NOT be implemented as `min_overlap` with a particular threshold.
- `min_overlap` MUST NOT be applied in `within` mode. A `mode="within"` query uses the containment predicate plus orthogonal filters (strand, 8.3) only. (For a genuine `within` pair the query coverage is exactly 100%, so the exemption is not observable in the result set; the rule is nevertheless normative and preserved from 8.2.)
- `use_strand` composes with `within` by logical AND (8.3): a contained pair must also satisfy the strand predicate when `use_strand=True`, and missing/unknown strand is not a wildcard.
- `how="inner"` emits one canonical row for every qualifying query/annotation pair (zero rows when none qualify), preserving query order then annotation input order. `how="left"` follows 7.2: every query row survives, a query with qualifying annotations emits exactly one row per qualifying annotation, and a query with zero qualifying annotations emits exactly one unmatched row (`has_overlap == False`, annotation fields canonical missing). Overlapping-but-not-contained annotations and annotations contained by the query do not count as matches.
- The predicate is evaluated after canonicalization on both engines; `within` MUST NOT be implemented as unfiltered ordinary overlap, and MUST NOT be delegated to a backend-native containment/fraction option whose direction is backend-defined. In particular bedtools `-F` is a minimum overlap as a fraction of B (here the annotation), so a native `-F 1.0` mapping expresses the opposite (`contains`) relation and MUST NOT define `within`.

### 8.6 Closest (fixed in Task 6E)

`mode="closest"` has ONE normative, backend-independent meaning. Both
engines MUST implement it with identical behavior and identical canonical
distance values for the same input, and neither backend-native
closest/nearest call (bedtools `closest`, polars-bio `nearest`) MAY be
used for the selection or the distance.

**Candidate set.** For each query, the candidate annotations are the
rows of the SAME chromosome only. Distance is never defined across
chromosomes. When `use_strand = True`, SPEC 8.3 strand eligibility
applies to the candidate set BEFORE nearest selection: a query and
annotation qualify as candidates only when both carry known strand
metadata and the strands match exactly; missing/unknown strand never
qualifies as a wildcard. When `use_strand = False`, strand is ignored
entirely. This is strand-BEFORE-nearest, not a post-filter on the
winning rows: an ineligible annotation (e.g. opposite strand) MUST NOT
suppress a farther eligible one.

**Distance.** For a query interval `Q = [q_start, q_end)` and a candidate
annotation `A = [a_start, a_end)` (canonical 0-based half-open
integers), the distance is the exact integer

    distance(Q, A) = max(0, a_start - q_end, q_start - a_end)

the number of genomic bases in the gap between the two intervals:

- overlapping intervals have distance 0;
- touching (bookended) intervals (`a_start == q_end` or `a_end ==
  q_start`) have distance 0;
- a one-base gap has distance 1;
- a larger gap is the exact number of intervening bases.

The computation MUST be exact integer arithmetic; floating point MUST
NOT be used (large genomic coordinates would silently corrupt beyond
2**53). Backend-native distances are non-normative and MUST NOT
surface: on bedtools 2.31.1, `closest -d` reports gap + 1 for separated
pairs (76 where the canonical gap is 75; 1 for touching pairs), and
polars-bio `nearest.distance` reports the gap itself (75; 0 for
overlapping/touching).

**Selection and ties.** Per query, every candidate at the minimum
distance is returned — ALL tied-nearest annotations, with no arbitrary
one-tie selection and no deduplication of duplicate-valued annotations.
Row order is query input order, then annotation input order among the
ties — never genomic sort order. Distance does not affect WHICH rows
are emitted (it is an annotation of the selected rows), so ties never
break by distance.

**`how="inner"`.** A query with no eligible candidate (no same-
chromosome annotation, or no same-strand annotation in stranded mode)
contributes ZERO rows.

**`how="left"`.** Every query with no eligible candidate MUST appear
exactly once with `has_overlap = False`, canonical missing values for
every `annot_*` field, and canonical missing (`pd.NA`) `distance`; a
query with at least one tied-nearest annotation appears once per
qualifying annotation (the selection rule above), consistent with the
left-mode wording of 8.4/8.5. In closest mode `has_overlap` is
interpreted as "an annotation was attached" — `True` for every matched
row (including overlapping, touching, and separated rows) and `False`
for unmatched left rows; it is NOT an overlap predicate.

**Result columns.** The result MUST carry an extra `distance` column
with a canonical missing-aware integer type (nullable Int64): matched
rows carry an integer >= 0; unmatched left rows carry canonical missing
(`pd.NA`), never 0. No other closest-specific column is normative.

**Exclusions.** `min_overlap` (SPEC 8.2), `contains` (SPEC 8.4), and
`within` (SPEC 8.5) do NOT participate in closest mode: closest is
neither an overlap-qualification, containment, nor boundary predicate
(it only ranks candidate annotations by gap distance). In particular,
touching intervals have distance 0 in closest even though they do NOT
overlap under SPEC 8.2.

The distance formula, candidate rules, tie behavior, ordering, and
missing-candidate behavior above are the normative contract; any engine
implementation that reproduces backend-native closest/nearest behavior
instead of this definition is a defect.

## 9. Backend requirements

### 9.1 BedtoolsEngine

The Bedtools backend MAY use pybedtools/bedtools-native output internally. It MUST adapt that output to the canonical result contract.

Bedtools-specific null sentinels such as `.`, `-1`, or equivalent MUST NOT leak into canonical output unless deliberately chosen as the canonical public representation.

### 9.2 PolarsBioEngine

The Polars-Bio backend SHOULD use the current documented API rather than assumptions about historical output suffixes.

It MUST NOT:

- assume Polars-Bio uses `_right` suffixes;
- classify provenance using suffix heuristics when source schemas are known;
- silently downgrade requested left-join semantics to inner overlap;
- silently return unfiltered ordinary overlaps for `contains` or `within`;
- swallow backend exceptions and convert them into scientifically plausible empty results.

Expected operational errors MUST be raised or represented through an explicit application error path.

## 10. Testing contract

### 10.1 Baseline

The repository MUST have a reproducible documented test command that collects and runs from the repository root without relying on an implicit developer `PYTHONPATH`.

### 10.2 Parity fixtures

The parity suite MUST include minimal fixtures for at least:

- exact interval match;
- one-base overlap;
- boundary-touching but non-overlapping intervals;
- query with no match;
- one query matching multiple annotations;
- duplicate query rows;
- duplicate annotation rows;
- different chromosomes;
- mixed input metadata columns;
- chromosome naming normalization;
- coordinate-system boundary conversion.

Registry-backed chromosome naming normalization (SPEC 5.1) is parity-relevant: once it is connected to the runtime, it MUST be covered by representative parity and oracle tests (resolution, rendering, unresolved and partial-resolution reporting, and the coordinate invariant), independent of backend selection. Those tests are not yet present; the current parity and oracle suites do not exercise chromosome normalization.

Minimum-overlap fixtures were added in Task 6A (`tests/parity/test_min_overlap_parity.py`); strand fixtures were added in Task 6B (`tests/parity/test_strand_parity.py`); contains fixtures were added in Task 6C (`tests/parity/test_contains_parity.py`); within fixtures were added in Task 6D (`tests/parity/test_within_parity.py`); closest fixtures were added in Task 6E (`tests/parity/test_closest_parity.py`), including representative closest cases in the differential layer.

### 10.3 Comparison

Parity MUST be evaluated after canonicalization. Tests SHOULD compare values, data types where contractually relevant, column order, row multiplicity, missing-value representation, and deterministic row order.

“Same number of hits”, “similar BED files”, or manual visual inspection is NOT sufficient evidence of parity.

## 11. UI and deployment constraints

The Streamlit UI MUST select the annotation backend without changing scientific input semantics.

AnnotateR MUST retain containerized deployment compatibility with SciLifeLab Serve. Deployment-specific changes are deferred until backend correctness is protected by tests.

## 12. Repository naming

The product name is **AnnotateR**. The preferred repository slug is **`annotater`**.

Generic implementation nouns MAY remain `annotator` where they describe a role rather than the product brand, for example `annotator.py` or `ProgressiveAnnotator`. Repository renaming MUST NOT trigger unnecessary package/module renames.

## 13. Definition of done for the parity initiative

The initiative is complete when:

1. the baseline test suite runs reproducibly;
2. parser/normalization behavior is backend-independent;
3. a canonical interval and output contract is implemented;
4. Bedtools and Polars-Bio satisfy the same parameterized parity tests for every supported operation claimed by the UI;
5. unsupported semantics fail explicitly rather than silently returning approximate results;
6. Streamlit selects either backend without changing canonical scientific results;
7. documentation and SciLifeLab Serve deployment instructions reflect the final architecture;
8. a correctness-first benchmark documents any performance difference without changing the semantic contract.

## 14. External references

External manuals and version-sensitive behavior are indexed in [`docs/references.md`](docs/references.md). Agents MUST consult the relevant primary documentation before changing backend behavior.
