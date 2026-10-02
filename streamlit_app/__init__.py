"""
AnnotateR - Genomic Coordinate Annotation Tool

A web-based tool for annotating genomic coordinates with support for:
- Multiple file formats (BED, GFF, GTF, VCF, custom)
- Chromosome name normalization
- Coordinate system conversion (0-based vs 1-based)
- Fast intersection using bedtools
"""

from .config.settings import Settings as _Settings

# Derived from the single version source of truth (Settings.VERSION);
# keep pyproject.toml aligned when bumping.
__version__ = _Settings.VERSION
__author__ = "Jyotirmoy Das, Ph.D. & Massimiliano Volpe, Ph.D."
__email__ = "jyotirmoy.das@liu.se, massimiliano.volpe@scilifelab.se"
