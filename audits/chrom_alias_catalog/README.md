# UCSC chromAlias catalog audit

Diagnostic snapshot; it does not add anything to the runtime catalog.
`report.json` is the machine-readable result, `SUMMARY.md` its short
rendering. Both are produced by `scripts/audit_chrom_alias_catalog.py`
(classification rules and reason codes are in its docstring and in the
report's `audit` block).

Reproduce offline from a populated cache:

    python scripts/audit_chrom_alias_catalog.py --cache-dir CACHE \
        --out-json report.json --out-summary SUMMARY.md

Populate or extend the cache (the only networked mode):

    python scripts/audit_chrom_alias_catalog.py --cache-dir CACHE --fetch ...

The report pins the catalog SHA-256 and every source's SHA-256; the same
cache gives a byte-identical report. Nothing in the application or the
tests uses the network.
