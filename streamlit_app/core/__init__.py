"""Core functionality modules"""

from .chromosome_normalization import (
    ChromosomeNormalizationReport,
    NormalizationResult,
    normalize_chromosomes,
    normalize_chromosomes_with_registry,
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
from .execution import (
    AnnotationError,
    AnnotationExecutionError,
    AnnotationOutcome,
    AnnotationRequest,
    AnnotationWarning,
    ChromosomeNormalizationOutcome,
    FeatureFilterReport,
    execute_annotation,
    expand_feature_types,
)
from .vcf_export import (
    VCF_FIXED_COORD_COLUMNS,
    VCF_NONINFO_ANNOT_COLUMNS,
    UnrecoverableVCFError,
    VCFExportError,
    VCFInfoDeclarationConflict,
    build_annotated_vcf,
    derive_vcf_contig_renames,
    deterministic_date_stamp,
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
    "AnnotationError",
    "AnnotationExecutionError",
    "AnnotationOutcome",
    "AnnotationRequest",
    "AnnotationWarning",
    "ChromosomeNormalizationOutcome",
    "FeatureFilterReport",
    "execute_annotation",
    "expand_feature_types",
    "VCF_FIXED_COORD_COLUMNS",
    "VCF_NONINFO_ANNOT_COLUMNS",
    "UnrecoverableVCFError",
    "VCFExportError",
    "VCFInfoDeclarationConflict",
    "build_annotated_vcf",
    "derive_vcf_contig_renames",
    "deterministic_date_stamp",
]
