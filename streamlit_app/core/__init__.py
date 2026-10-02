"""Core functionality modules"""

from .chromosome_normalization import (
    ChromosomeNormalizationReport,
    NormalizationResult,
    normalize_chromosomes,
)
from .coordinates import CoordinateConverter, CoordinateNormalizer
from .parsers import (
    FormatDetector,
    BEDParser,
    GFFParser,
    VCFParser,
    CustomParser
)
from .annotator import (
    AnnotationEngine,
    BedtoolsEngine,
    PolarsBioEngine,
)
from .schema import (
    CanonicalSchemaError,
    InvalidIntervalError,
    MalformedFileError,
    canonical_result_columns,
    canonicalize_annotation_result,
    validate_canonical_interval_table,
)
from .normalization import (
    FORMAT_COORDINATE_SYSTEMS,
    AUTHORITATIVE_FORMAT_EXTENSIONS,
    coordinate_system_for,
    extension_authoritative_for,
    normalize_intervals,
    parse_and_normalize,
)

__all__ = [
    "ChromosomeNormalizationReport",
    "NormalizationResult",
    "normalize_chromosomes",
    "CoordinateConverter",
    "CoordinateNormalizer",
    "FormatDetector",
    "BEDParser",
    "GFFParser",
    "VCFParser",
    "CustomParser",
    "AnnotationEngine",
    "BedtoolsEngine",
    "PolarsBioEngine",
    "CanonicalSchemaError",
    "InvalidIntervalError",
    "MalformedFileError",
    "canonical_result_columns",
    "canonicalize_annotation_result",
    "validate_canonical_interval_table",
    "FORMAT_COORDINATE_SYSTEMS",
    "AUTHORITATIVE_FORMAT_EXTENSIONS",
    "coordinate_system_for",
    "extension_authoritative_for",
    "normalize_intervals",
    "parse_and_normalize",
]
