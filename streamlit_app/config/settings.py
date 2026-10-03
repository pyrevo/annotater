"""
Application settings and configuration
"""

import os
from pathlib import Path


class Settings:
    """Application-wide settings"""
    
    # Application metadata
    APP_NAME = "AnnotateR"
    # Single source of truth for the application version; the footer and
    # streamlit_app.__version__ both derive from this value. Aligned with
    # pyproject.toml for the 0.1.0 pre-release housekeeping pass; the
    # actual v0.1.0 tag happens only after manual GUI acceptance.
    VERSION = "0.1.0"
    DESCRIPTION = "Genomic Coordinate Annotation Tool"
    
    # File handling
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 500))
    SUPPORTED_COORD_FORMATS = [".bed", ".vcf", ".txt", ".csv", ".tsv"]
    SUPPORTED_ANNOT_FORMATS = [".gff", ".gtf", ".gff3", ".bed", ".txt", ".csv", ".tsv"]
    
    # Performance settings
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 100000))
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", 4))
    ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"
    
    # Temporary files
    TEMP_DIR = Path(os.getenv("TEMP_DIR", "/tmp/annotator"))
    CLEANUP_AFTER_HOURS = int(os.getenv("CLEANUP_AFTER_HOURS", 24))
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Coordinate systems
    COORDINATE_SYSTEMS = {
        "0-based": {
            "description": "Half-open interval [start, end)",
            "formats": ["bed", "bam"],
            "example": "[100, 200) = positions 100-199"
        },
        "1-based": {
            "description": "Closed interval [start, end]",
            "formats": ["gff", "gtf", "vcf", "sam"],
            "example": "[101, 200] = positions 101-200"
        }
    }
    
    # Annotation modes. The descriptions are the normative short
    # user-facing contract (SPEC 8.2-8.6); do not imply backend
    # differences (both engines are contractually equivalent).
    ANNOTATION_MODES = {
        "overlap": {
            "description": "Return annotation intervals that overlap each query interval",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "contains": {
            # SPEC 8.4 (Task 6C): query contains annotation. Candidates come
            # from an ordinary overlap; the containment predicate is the
            # shared canonical contains_keep_mask post-filter, not a
            # backend fraction flag.
            "description": "Return annotations fully contained within each query interval",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "within": {
            # SPEC 8.5 (Task 6D): query contained within annotation. Candidates
            # come from an ordinary overlap; the containment predicate is the
            # shared canonical within_keep_mask post-filter, not a backend
            # fraction flag (bedtools -F 1.0 is the opposite direction).
            "description": "Return annotations that fully contain each query interval",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "closest": {
            "description": (
                "Return the nearest annotation interval(s); all equally "
                "nearest ties are retained. Overlapping or touching "
                "intervals have distance 0."
            )
        }
    }
    
    # Engine selection (Task 7): the single source for engine options,
    # the key -> engine-class mapping, and the default backend is
    # streamlit_app/core/engine_registry.py. The default is the historical
    # default (Bedtools), preserved by product decision (Task 7 §13).

    # UI settings
    THEME = {
        "primaryColor": "#006DAE",
        "backgroundColor": "#FFFFFF",
        "secondaryBackgroundColor": "#F0F2F6",
        "textColor": "#262730",
        "font": "sans serif"
    }
    
    @classmethod
    def ensure_temp_dir(cls):
        """Ensure temporary directory exists"""
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        return cls.TEMP_DIR
    
    @classmethod
    def get_max_file_size_bytes(cls):
        """Get maximum file size in bytes"""
        return cls.MAX_FILE_SIZE_MB * 1024 * 1024
