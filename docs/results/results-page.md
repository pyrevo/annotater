# Understanding the results page

After a run, the **"3. Results"** section appears at the bottom of the
page. Everything in it is derived from the **canonical result table**
produced by the engine — nothing else.

## From top to bottom

### Provenance caption

A compact one-line caption above the metrics identifies the run that
produced the table, e.g.:

```text
Bedtools · Overlap · Left join
```

For closest runs it additionally states that the **distance** column is
included. If the table you are looking at came from a different engine,
operation, or join than you think, this caption tells you exactly which
configuration produced it.

### Four summary metrics

| Metric | Meaning |
|---|---|
| **Query rows** | number of rows in your *normalized* query input |
| **Result rows** | number of rows in the current result table |
| **Matched rows** | result rows with an attached annotation (`has_overlap = True`) |
| **Unmatched rows** | query rows kept by the left join without a qualifying annotation |

Sanity checks:

- left join ⇒ `Result rows = Matched rows + Unmatched rows` and
  `Unmatched rows ≤ Query rows`;
- inner join ⇒ `Unmatched rows = 0` always;
- `Matched rows` can exceed `Query rows` (one query, several
  annotations) — see
  [FAQ → Why is my result table bigger than my input?](../faq.md).

### Show filter

**All / Matched only / Unmatched only**, with a caption "Showing X of Y
rows". The filter **narrows what is displayed and downloaded** — it
never modifies the underlying result; switching it back restores the
full table, and the canonical data is never mutated
([Downloading and exporting results](export.md)).

### The result table

The first columns of the canonical schema, in order: `coord_chr`,
`coord_start`, `coord_end`, (strand and query metadata when present),
then `annot_chr`, `annot_start`, `annot_end`, (strand and annotation
metadata when present), and finally `has_overlap` — plus `distance` in
closest mode. The complete column reference is
[Result columns and provenance](result-columns.md); unmatched rows are
explained in [Matched vs unmatched rows](matched-unmatched.md).

### "Charts and gene list" (collapsed)

Summary charts and a gene list built from the *displayed* rows
([Charts and gene list](charts-gene-list.md)).

### "Download results"

CSV / TSV / Excel buttons (and, for VCF queries, Annotated VCF) —
[Downloading and exporting results](export.md).

## Informational states (not errors)

| What you see | Meaning |
|---|---|
| "No results yet. Upload both files, configure the operation, and run the annotation." | nothing has been run for the current configuration (any configuration change invalidates stored results) |
| "No qualifying annotations were found for the selected operation and options." | a **valid zero-match state**: the run succeeded, nothing qualified. Diagnose in [Troubleshooting → zero matches](../troubleshooting.md#zero-matches) |
| "No qualifying annotations were found for the selected operation and options (inner join keeps matched rows only)." | inner join and nothing qualified — the table is empty by definition |
| "No results to display — the query table contained no intervals." | the (normalized) query input was empty |
| An error naming the selected engine | the engine is unavailable in this deployment — see [Troubleshooting → engine unavailable](../troubleshooting.md#engine-unavailable) |

A zero-match *information* state is fundamentally different from an
*error*: the former means "the analysis ran and found nothing"; the
latter means "the analysis could not run".