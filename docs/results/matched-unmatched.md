# Matched vs unmatched rows

The column **`has_overlap`** (`True` / `False`) separates the two kinds
of rows in a result table.

## Matched rows (`has_overlap = True`)

- The query interval **qualified** against the annotation interval
  under the selected operation and options.
- In closest mode, `has_overlap = True` means "an annotation was
  **attached**" — the `distance` column then tells you the gap; the
  intervals may be separated by many bases
  ([Closest → what the result looks like](../operations/closest.md#what-the-result-looks-like)).
- All `annot_*` columns carry the annotation's values.

## Unmatched rows (`has_overlap = False`)

These exist **only in left-join mode**. An unmatched row means: *this
query row had no qualifying annotation under the selected operation and
options.*

- `coord_*` columns carry the query's values.
- **All** `annot_*` columns are missing (canonical missing — blank in
  the table, empty cells in exports).
- In closest mode, `distance` is also missing.
- The row is a **real row**, present in the table *and* in every
  download — not a display placeholder.

## Reading the two together (left join)

```text
query rows in:   6            (normalized query input)
result rows:     6            (left join: one row per query here, because each matches 0 or 1 gene)
matched:         3            region1, region3, regionX   — annot_* filled
unmatched:       3            region2, region4, regionY   — annot_* missing
```

The unmatched rows are often the most important output: "these are the
regions that found no annotation" is itself the answer to many
biological questions.

## If you switched to inner join

Re-running the same analysis with **Matched rows only (inner join)**
removes the unmatched rows entirely — the result contains only
qualifying pairs ([Join behavior: left vs inner](../operations/join-behavior.md)).

## The Show filter

The **Show: All / Matched only / Unmatched only** radio in the results
section lets you *look at* one kind at a time ("Showing X of Y rows")
and narrow the download to it — but the underlying canonical result is
never changed, so switching back to **All** always restores the full
table.

## "Zero matches" is not an error

A left-join result where *every* row is unmatched is a **valid,
successful run** — the results section shows an information box
("No qualifying annotations were found for the selected operation and
options"), not an error. The usual causes (chromosome naming mismatch,
strand matching on strand-less files, the wrong operation direction)
are in [Troubleshooting → zero matches](../troubleshooting.md#zero-matches).