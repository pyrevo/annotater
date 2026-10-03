# Future Features Roadmap

> **Status: pre-release draft (not user documentation).** This roadmap
> predates the v0.1.0 release; several items listed below (VCF support,
> Polars-Bio engine, charts and gene list) have since been implemented
> and are part of the released product (see the user manual and
> `SPEC.md`). Items here are not commitments and are not normative.

This document outlines planned features and improvements for AnnotateR. Features are organized by priority and complexity.

---

## ✅ Recently Implemented

- [x] Feature type filter (gene, exon, CDS, etc.)
- [x] Summary pie chart (feature distribution)
- [x] Chromosome distribution bar chart
- [x] Top 10 genes visualization
- [x] Gene list export for pathway analysis tools
- [x] Basic VCF support (0-based coordinate fix & valid export) [New]

---

## 🎯 High Priority (Next Release)

### 1. Merge VCF Support & Enhance Annotations
**Problem:** VCF support is currently basic and on a separate feature branch. Annotations are dumped into a single INFO string.

**Solution:**
- Merge `feature/vcf-support` into main.
- Parse GFF attributes (biotype, etc.) and add as structured VCF annotations (ANN field).
- Optimize for large VCFs (streaming output).

**Effort:** Medium

### 2. Polars-Bio Engine Integration
**Problem:** Need a high-performance alternative to `bedtools` for large datasets or pure Python/Rust environments.

**Solution:**
- Evaluate `polars-bio` (Rust-backed, high performance).
- Compare `overlap`, `nearest`, and `coverage` functions with `bedtools`.
- Implement as selectable "Fast Engine" or fallback.

**Effort:** High (new dependency & logic)

### 3. Genome Assembly Detector & Warning
**Problem:** Users often don't know if their coordinates are from hg19 vs hg38, or mm10 vs mm39.

**Solution:**
- Detect assembly from chromosome lengths or signature coordinates
- Show warning when coordinate/annotation assemblies don't match
- Suggest using LiftOver before proceeding

```
⚠️ Your coordinates appear to be from hg19 (GRCh37)
   but your annotation file is hg38 (GRCh38).
   Results may be incorrect!
```

**Effort:** Medium

---

### 2. Input Validation Report
**Problem:** Users upload files without knowing if they contain errors.

**Solution:** Before running, show detailed validation:
- ✅ 1,234 valid coordinates
- ⚠️ 5 coordinates on unknown chromosomes (chrUn_...)
- ⚠️ 2 coordinates with start > end (skipped)
- ℹ️ Detected format: BED6

**Effort:** Low

---

### 3. Promoter Region Definition
**Problem:** "Promoter" means different things to different researchers.

**Solution:** Let users define their own promoter regions:
```
Promoter: [____] bp upstream to [____] bp downstream of TSS
         Default: 2000 bp upstream, 500 bp downstream
```

Then categorize results as "in promoter", "in gene body", "intergenic".

**Effort:** Medium

---

### 4. Distance to Nearest Gene
**Problem:** When coordinates don't overlap anything, users want to know what's nearby.

**Solution:** For non-overlapping coordinates, show:
```
chr1:12345-12400  →  No overlap
                     Nearest: TP53 (upstream, 2.3 kb)
```

**Effort:** Low (already have "closest" mode)

---

### 5. BED Column Preservation  
**Problem:** Original BED columns (name, score, strand) are lost in output.

**Solution:** Keep all original input columns in the output:
```
Input:  chr1  100  200  peak_001  500  +
Output: chr1  100  200  peak_001  500  +  GENE1  exon  protein_coding
```

**Effort:** Low

---

## 📊 Medium Priority

### 6. Preset Annotation Databases
**Problem:** Users repeatedly upload the same large annotation files.

**Solution:** Pre-loaded annotation options:
```
📥 Quick Load Annotations:
[GENCODE v44 (hg38)] [RefSeq (hg38)] [Ensembl 110 (mm39)]
```

Cache popular annotations on server (~100-200 MB each).

**Effort:** Medium (storage/download considerations)

---

### 7. Batch Processing Mode
**Problem:** Users want to annotate multiple files with the same annotations.

**Solution:**
- Upload multiple coordinate files
- Select single annotation file
- Process all, download as ZIP

**Effort:** Medium

---

### 8. LiftOver Integration
**Problem:** Users have coordinates from old assemblies.

**Solution:** 
- Option A: Link to UCSC LiftOver tool
- Option B: Integrate liftOver binary (chain files required)
- Convert hg19 ↔ hg38, mm10 ↔ mm39, etc.

**Effort:** High (chain files are large)

---

### 9. Session History
**Problem:** Users want to redo or modify previous analyses.

**Solution:** Remember last 5 analyses in session:
- Previous uploads
- Settings used
- Quick "re-run with different settings"

**Effort:** Low

---

### 10. Annotation Statistics Dashboard
**Problem:** Users want to understand their annotation file before running.

**Solution:** Show annotation file stats:
- Total features by type
- Coverage per chromosome
- Average feature length
- Strand distribution

**Effort:** Low

---

## 🔬 Advanced Features

### 11. Overlap Visualization
**Problem:** Users want to see WHERE overlaps occur.

**Solution:** Simple genome browser-style view:
```
chr1:100000-101000
├── Your region:    ████████████
├── GENE1 (exon):      ████
└── GENE1 (intron): ██      ██████
```

**Effort:** High (complex visualization)

---

### 12. REST API
**Problem:** Programmatic access for pipelines.

**Solution:** FastAPI endpoint:
```bash
curl -X POST http://server/api/annotate \
  -F "coords=@peaks.bed" \
  -F "annots=@genes.gtf"
```

**Effort:** Medium

---

### 13. Command-Line Interface (CLI)
**Problem:** Users want to run annotations in scripts/pipelines.

**Solution:**
```bash
annotater -i peaks.bed -a genes.gtf -o output.tsv
```

**Effort:** Medium

---

## 🦎 Features for Non-Model Organisms

Working with non-model organisms presents unique challenges. These features address common pain points:

### N1. Custom Chromosome Name Mapping
**Status:** the TSV upload is implemented (assembly-aware chromosome naming, `Custom chromosome mapping…`; see
`docs/preparing-your-data/chromosome-identifiers.md`). The interactive mapping interface and saving mappings for reuse
below are not.

**Problem:** Non-model organisms often have inconsistent chromosome naming (scaffold_1, LG01, Chr01, etc.)

**Solution:**
- Upload custom chromosome name mapping file (TSV)
- Or interactive mapping interface:
  ```
  Your file          Annotation file
  scaffold_1    →    Chr1
  scaffold_2    →    Chr2
  LG_X          →    ChrX
  ```
- Save mappings for reuse

**Effort:** Medium

---

### N2. Flexible ID Matching
**Problem:** Gene IDs may differ between annotation sources (transcriptome assemblies vs genome annotations).

**Solution:**
- Allow fuzzy matching option
- "Best match" mode using sequence similarity scores
- Support for custom ID mapping tables (e.g., from OrthoFinder, eggNOG)

**Effort:** Medium

---

### N3. User-Uploaded Genome Annotations
**Problem:** No presets exist for non-model species.

**Solution:**
- "My Organisms" section
- Upload and save custom annotations
- Persistent storage (optional account system)
- Share annotations within lab/group

**Effort:** High

---

### N4. De Novo Transcriptome Support
**Problem:** Many non-model studies use de novo transcriptomes, not reference genomes.

**Solution:**
- Support transcript-level coordinates
- Handle Trinity-style IDs (TRINITY_DN1234_c0_g1_i1)
- Parse attributes from transcriptome GFF (TransDecoder output)

**Effort:** Medium

---

### N5. BUSCO/OrthoDB Integration
**Problem:** Need to identify conserved genes in non-model organisms.

**Solution:**
- Input BUSCO results
- Annotate with ortholog information
- Show which coordinates overlap universal single-copy orthologs

**Effort:** Medium

---

### N6. Multi-Species Comparison Mode
**Problem:** Comparative genomics with non-model species.

**Solution:**
- Side-by-side annotation of homologous regions
- Synteny-aware annotation
- Support for whole-genome alignments (MAF format)

**Effort:** High

---

### N7. Scaffold/Contig Assembly Support
**Problem:** Non-model genomes are often fragmented (thousands of scaffolds).

**Solution:**
- Handle very long chromosome lists gracefully (don't show all in charts)
- "Unknown scaffold" category
- N50/assembly quality warning if many small scaffolds

**Effort:** Low

---

### N8. Custom Feature Types
**Problem:** Non-standard annotations have custom feature types (ORF, pseudogene, transposon, etc.)

**Solution:**
- Dynamic feature type detection from GFF
- Allow filtering by ANY feature type found
- "Other" category for rare types

**Effort:** Low (partially done - just need dynamic detection)

---

### N9. Repeat/Transposon Annotation
**Problem:** Many studies focus on transposable elements in non-model organisms.

**Solution:**
- Support RepeatMasker output format
- TE family categorization
- TE density calculation around features

**Effort:** Medium

---

### N10. Alternative Splicing Awareness
**Problem:** Need to distinguish which transcript variant a coordinate overlaps.

**Solution:**
- Show all overlapping transcripts, not just gene
- Filter by transcript support level (if available)
- Show isoform-specific results

**Effort:** Medium

---

## 🗓️ Implementation Timeline (Suggested)

### Phase 1 (v1.1) - Quick Wins
1. Input validation report
2. BED column preservation
3. Distance to nearest gene
4. Custom feature type detection (N8)

### Phase 2 (v1.2) - Core Improvements  
1. Genome assembly detection
2. Promoter region definition
3. Session history
4. Custom chromosome mapping (N1)

### Phase 3 (v1.3) - Advanced
1. Preset annotation databases
2. Batch processing
3. REST API
4. User-uploaded genomes (N3)

### Phase 4 (v2.0) - Major Features
1. LiftOver integration
2. Overlap visualization
3. CLI tool
4. Multi-species comparison (N6)

---

## 💡 Contributing

Have a feature idea? Open an issue on GitHub or contact:
- massimiliano.volpe@scilifelab.se
- jyotirmoy.das@liu.se

---

*Last updated: 2025-12-05*
