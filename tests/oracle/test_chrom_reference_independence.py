"""The chromosome oracle must not import the code it checks.

Enforced structurally by parsing the module's imports: no production
package, no registry builder/loader, no dataframe or interval library.
"""

from __future__ import annotations

import ast
from pathlib import Path

import tests.oracle.chrom_reference as reference

FORBIDDEN_ROOTS = {
    "streamlit_app", "tests", "pandas", "polars", "polars_bio", "pybedtools",
    "numpy",
}


def test_chrom_reference_imports_only_the_standard_library():
    tree = ast.parse(Path(reference.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add("<relative>" if node.level
                         else node.module.split(".")[0])
    imported.discard("__future__")
    assert imported.isdisjoint(FORBIDDEN_ROOTS | {"<relative>"}), imported
    assert imported <= {"csv", "gzip", "hashlib", "io", "json", "dataclasses",
                        "pathlib"}


def test_chrom_reference_does_not_read_generated_registry_data():
    """Expectations come from upstream/, never from data/*.tsv."""
    source = Path(reference.__file__).read_text()
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith(("#", '"', "'")))
    assert "registry_file" not in code
    assert '"data"' not in code and "data/" not in code.replace(
        "data/*.tsv", "")
