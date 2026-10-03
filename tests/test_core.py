"""
Unit tests for core functionality

Run with: pytest tests/test_core.py -v
"""

import pytest
import pandas as pd
from streamlit_app.core import (
    CoordinateConverter,
    normalize_chromosomes,
    CoordinateNormalizer,
    BEDParser,
    GFFParser
)
from streamlit_app.core.schema import MalformedFileError


class TestChromosomeNormalization:
    """Registry-backed chromosome naming (replaces the hard-coded mapper)."""

    @staticmethod
    def _norm(chroms, target, assembly="GRCh38"):
        df = pd.DataFrame({
            'chr': chroms,
            'start': list(range(100, 100 + 100 * len(chroms), 100)),
            'end': list(range(200, 200 + 100 * len(chroms), 100)),
        })
        return normalize_chromosomes(df, assembly=assembly, target=target)

    def test_ucsc_to_ensembl_conversion(self):
        out = self._norm(["chr1", "chrX", "chrM"], "ensembl").dataframe
        assert out['chr'].tolist() == ["1", "X", "MT"]

    def test_ensembl_to_ucsc_conversion(self):
        out = self._norm(["1", "X", "MT"], "ucsc").dataframe
        assert out['chr'].tolist() == ["chr1", "chrX", "chrM"]

    def test_dataframe_standardization_keeps_coordinates(self):
        result = self._norm(['chr1', 'chr2', 'chr3'], 'ensembl')
        assert result.dataframe['chr'].tolist() == ['1', '2', '3']
        assert result.dataframe['start'].tolist() == [100, 200, 300]
        assert result.dataframe['end'].tolist() == [200, 300, 400]
        assert result.report.complete


class TestCoordinateConverter:
    """Test coordinate system conversion"""
    
    def test_zero_to_one_based(self):
        """Test 0-based to 1-based conversion"""
        start, end = CoordinateConverter.convert(100, 200, "0-based", "1-based")
        assert start == 101
        assert end == 200
    
    def test_one_to_zero_based(self):
        """Test 1-based to 0-based conversion"""
        start, end = CoordinateConverter.convert(101, 200, "1-based", "0-based")
        assert start == 100
        assert end == 200
    
    def test_same_system(self):
        """Test conversion within same system"""
        start, end = CoordinateConverter.convert(100, 200, "0-based", "0-based")
        assert start == 100
        assert end == 200
    
    def test_detect_system_from_format(self):
        """Test system detection from file format"""
        assert CoordinateConverter.detect_system("bed") == "0-based"
        assert CoordinateConverter.detect_system("gff") == "1-based"
        assert CoordinateConverter.detect_system("gtf") == "1-based"
        assert CoordinateConverter.detect_system("vcf") == "1-based"


class TestCoordinateNormalizer:
    """Test coordinate normalization"""
    
    def test_snp_normalization_zero_based(self):
        """Test SNP normalization in 0-based system"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 100, None, is_snp=True, coordinate_system="0-based"
        )
        assert chr == "chr1"
        assert start == 100
        assert end == 101
    
    def test_snp_normalization_one_based(self):
        """Test SNP normalization in 1-based system"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 101, None, is_snp=True, coordinate_system="1-based"
        )
        assert chr == "chr1"
        assert start == 101
        assert end == 101
    
    def test_interval_normalization(self):
        """Test interval normalization (no change)"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 100, 200, is_snp=False
        )
        assert chr == "chr1"
        assert start == 100
        assert end == 200
    
    def test_is_single_position_zero_based(self):
        """Test single position detection in 0-based"""
        assert CoordinateNormalizer.is_single_position(100, 101, "0-based") == True
        assert CoordinateNormalizer.is_single_position(100, 200, "0-based") == False
    
    def test_is_single_position_one_based(self):
        """Test single position detection in 1-based"""
        assert CoordinateNormalizer.is_single_position(100, 100, "1-based") == True
        assert CoordinateNormalizer.is_single_position(100, 200, "1-based") == False


class TestParsers:
    """Test file parsers"""
    
    def test_bed_parser(self, tmp_path):
        """
        Test BED file parsing with the canonical validation contract.

        The historical fixture mixed valid rows with a malformed line
        (``region1`` has a single field) and previously expected the
        malformed record to be silently dropped. Under the canonical
        contract (PLAN Task 2) invalid input MUST fail explicitly with a
        precise error instead of silently discarding records.
        """
        bed_file = tmp_path / "test.bed"
        bed_file.write_text("chr1\t100\t200\nregion1\nchr2\t300\t400\tregion2\n")

        with pytest.raises(MalformedFileError, match="line 2"):
            BEDParser.parse(str(bed_file))

    def test_bed_parser_valid_variable_width(self, tmp_path):
        """Valid variable-width BED rows parse to the canonical core columns."""
        bed_file = tmp_path / "test.bed"
        bed_file.write_text("chr1\t100\t200\nchr2\t300\t400\tregion2\n")

        df = BEDParser.parse(str(bed_file))

        assert len(df) == 2
        assert 'chr' in df.columns
        assert 'start' in df.columns
        assert 'end' in df.columns
        assert df['chr'].tolist() == ['chr1', 'chr2']
        assert df['start'].tolist() == [100, 300]
        assert df['end'].tolist() == [200, 400]
        assert pd.isna(df['name'].iloc[0])
        assert df['name'].iloc[1] == 'region2'
    
    def test_bed_validation(self):
        """Test BED format validation"""
        # Valid BED
        df = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [100, 200],
            'end': [200, 300]
        })
        
        is_valid, error = BEDParser.validate(df)
        assert is_valid == True
        assert error is None
        
        # Invalid BED (start >= end)
        df_invalid = pd.DataFrame({
            'chr': ['chr1'],
            'start': [200],
            'end': [100]
        })
        
        is_valid, error = BEDParser.validate(df_invalid)
        assert is_valid == False
        assert "start >= end" in error


# Integration test
class TestIntegration:
    """Integration tests"""
    
    def test_full_workflow(self):
        """Test complete annotation workflow"""
        # Create sample data
        coords = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [100, 150],
            'end': [200, 250]
        })
        
        annots = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [50, 140],
            'end': [150, 200],
            'feature': ['gene1', 'gene2']
        })
        
        # Standardize chromosomes
        coords_std = normalize_chromosomes(
            coords, assembly="GRCh38", target="ucsc").dataframe
        annots_std = normalize_chromosomes(
            annots, assembly="GRCh38", target="ucsc").dataframe
        
        # Verify standardization
        assert coords_std['chr'].tolist() == ['chr1', 'chr2']
        assert annots_std['chr'].tolist() == ['chr1', 'chr2']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
