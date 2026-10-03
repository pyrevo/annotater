# Charts and gene list

The **"Charts and gene list"** expander in the results section adds a
light summary layer on top of the table. **Everything here is built
from the rows currently shown** — so the Show filter affects it exactly
as it affects the table and the downloads. It is a convenience view,
never a replacement for the result table or its exports.

## The three parts

### Feature type distribution (pie chart)

Counts of the annotation `feature` values (`annot_feature`) among the
displayed rows — e.g. how many matched rows are genes vs exons. Shown
only when the results carry a feature column with valid values
(otherwise: "No feature type data available for the chart.").

### Annotations per chromosome (bar chart)

The **top 15** `coord_chr` values among the displayed rows, by row
count. This is a quick look at where your matches (or unmatched query
rows, depending on the filter) sit genomically.

### Gene list and top-10 chart

The app looks for a gene/feature name column in the displayed results
(best effort: `annot_Name` and other name/id columns, in a fixed
priority). If one is found:

- a horizontal bar chart of the **top 10 genes by annotation count**;
- a full **gene list** (unique names, sorted) that you can download:
  - **Gene list (.txt)** — one gene per line, `gene_list.txt`
  - **Gene list (comma-separated)** — `gene_list.csv`

If no suitable column exists: "No gene/feature name column found in the
results." If the column exists but holds no valid names: "No valid gene
names found in the results."

## What the gene list does and does not do

- It is a **unique list of the names present in the displayed rows** —
  duplicates collapsed, in sorted order.
- It is **best-effort by column name**, not by biology: the column
  picked is the first candidate that holds values (for a typical GFF3
  gene run that is `annot_Name`, e.g. `GENE1`).
- It does **not** merge, rank by significance, or otherwise curate the
  names.
- If your annotation's meaningful identifier lives under a different
  key, it is still in the result table — use the export instead of the
  gene list for downstream use.
