# Quick Start Guide - AnnotateR

> This guide is for **developers** who install and run the code.
> If you have a running app (locally or deployed) and want to use it —
> upload files, choose an operation, read and export results — follow
> the **user manual** instead:
> [docs/getting-started/quick-start.md](docs/getting-started/quick-start.md)
> (or online at `https://pyrevo.github.io/annotater/`).

## 🚀 Get Started in 5 Minutes

### Option 1: Docker (Recommended)

```bash
# 1. Navigate to the repository root
cd /path/to/annotater

# 2. Build and start the application
docker-compose up --build

# 3. Open your browser
# Go to: http://localhost:8501

# 4. Stop the application
# Press Ctrl+C
```

Note: `docker-compose.yml` mounts your local `streamlit_app/` and `data/`
directories into the container, so local edits are picked up without
rebuilding. (For an exact production-like run, build and run the image
instead — see [docs/deployment.md](docs/deployment.md).)

### Option 2: Local Installation

```bash
# 1. Install bedtools (only if you want the Bedtools backend)
brew install bedtools

# 2. Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run the application
streamlit run streamlit_app/streamlit_app.py

# 5. Open your browser
# Go to: http://localhost:8501
```

---

## 📝 Try It Out

### Using Example Files

The project includes example files in `data/examples/`:
- `example_coordinates.bed` - 6 genomic regions
- `example_annotations.gff3` - Gene and exon annotations

**Steps:**
1. Open the app (http://localhost:8501)
2. Upload `example_coordinates.bed` as **Coordinate File**
3. Upload `example_annotations.gff3` as **Annotation File**
4. Click **"Run Annotation"**
5. View and download results!

---

## 🧪 Development Environment and Tests

### System dependencies (external binaries, separate from Python packages)

| Dependency | Why it is needed | macOS | Linux (Debian/Ubuntu) |
| --- | --- | --- | --- |
| `bedtools` (v2.x) | `BedtoolsEngine` (via `pybedtools`) shells out to the `bedtools` binary; without it, Bedtools-backed tests cannot run | `brew install bedtools` | `sudo apt-get install bedtools` |

`PolarsBioEngine` needs **no** external binary — the Polars-Bio engine is distributed inside the Python package. Install `bedtools` only if you use (or test) the Bedtools backend.

### Python dependencies

```bash
# 1. Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install Python dependencies (runtime only)
pip install -r requirements.txt

# For development (adds pytest, pytest-cov, black, ruff — as used by CI):
pip install -r requirements-dev.txt
```

`requirements*.txt` are generated from `uv.lock` (fully pinned, including
transitive dependencies); do not edit them by hand. Alternatively,
`uv sync --frozen --extra dev` installs exactly `uv.lock`. See
`docs/deployment.md` (Dependency management).

### Run the test suite (single documented command, from the repository root)

```bash
pytest
```

- Collection and imports are independent of the working directory and of `PYTHONPATH` (`pytest.ini` pins `testpaths = tests` and `pythonpath = .`). Do not launch Python from inside `streamlit_app/`.
- Verbose: `pytest tests/ -v`
- Coverage: `pytest --cov=streamlit_app --cov-report=html` (report in `htmlcov/index.html`)
- Smoke tests (core imports + engine construction, no interval operations): `pytest tests/test_smoke.py -v`

---

## 📂 Using Your Own Files

### Coordinate File (Required)
Upload one of:
- BED file (`.bed`)
- VCF file (`.vcf`)
- Custom CSV/TSV table: after upload you map the chromosome, start and
  (optionally) end columns in the app

### Annotation File (Required)
Upload one of:
- GFF/GTF file (`.gff`, `.gtf`, `.gff3`)
- BED file as annotations
- Custom CSV/TSV annotation table. It is **not** read directly from an
  arbitrary export: it must already have columns named exactly `chr`,
  `start` and `end` (other columns are kept as metadata), so rename the
  columns of a BioMart or UCSC Table Browser export first, and drop
  `track`/`browser` lines. Set **Annotation coordinates** to the
  coordinate system of the source data; the default for custom tables
  is 0-based half-open, and no system is guessed for you. A UCSC export
  that is BED-shaped (`.bed`, tab-separated, no header) is read as BED.

---

## ⚙️ Configuration Options

### Annotation Engine
- **Bedtools** (default): the reference implementation; requires the `bedtools` system binary
- **Polars-Bio**: the in-process implementation; ships inside the Python package (no external binary)

Both engines are interchangeable execution backends: the same input and options produce the same canonical result, schema, and exports on either. Selecting an unavailable backend shows a clear error instead of silently falling back to the other.

### Coordinate Systems
- **Auto-detect**: keeps the format's own system for known formats;
  custom tables are treated as 0-based half-open, so declare 1-based
  explicitly if your table is 1-based
- **0-based (BED)**: For BED, BAM files
- **1-based (GFF/GTF/VCF)**: For GFF, GTF, VCF, SAM files

### Chromosome naming
- **Genome assembly**: choose the assembly your files were made with (a bundled one, or *Custom chromosome mapping…* to upload your own `.tsv`); nothing is preselected or guessed
- **Chromosome naming**: *Keep original names* (default; no assembly needed), or UCSC, Assembly, Ensembl, NCBI RefSeq or GenBank names
- Identifiers the assembly does not know, or that have no verified name in the chosen naming, are kept as provided and reported; coordinates never change

### Annotation Modes
- **Overlap**: Find any overlapping annotations (default); optional minimum overlap fraction (0 = any positive overlap)
- **Contains**: Return annotations fully contained within each query interval (query contains annotation)
- **Within**: Return annotations that fully contain each query interval (query is contained within annotation)
- **Closest**: Return the nearest annotation interval(s); tied nearest annotations are all returned, with a canonical `distance` column (0 for overlapping/touching intervals)

### Strand
- **Off (default)**: strand is not required for a match
- **On**: a pair qualifies only if both intervals carry an explicit strand (+ or -) and the strands are equal; missing strand values do not act as wildcards

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Kill process on port 8501
lsof -ti:8501 | xargs kill -9

# Or use different port
streamlit run streamlit_app/streamlit_app.py --server.port=8502
```

### Import Errors
```bash
# Make sure you're in the repository root
# (the directory that contains requirements.txt)

# Install dependencies again
pip install -r requirements.txt

# Run from the repository root
streamlit run streamlit_app/streamlit_app.py
```

### Docker Issues
```bash
# Rebuild without cache
docker-compose build --no-cache

# Check logs
docker-compose logs

# Remove all containers and rebuild
docker-compose down
docker-compose up --build
```

---

## 📚 Next Steps

1. **Read the Specification**: See [SPEC.md](SPEC.md) (normative product/scientific contract)
2. **Understand the Architecture**: See [docs/architecture.md](docs/architecture.md) and [docs/engine-contract.md](docs/engine-contract.md)
3. **Deploy it**: See [docs/deployment.md](docs/deployment.md)
4. **Compare the backends**: See [docs/benchmark.md](docs/benchmark.md)

---

## 💬 Need Help?

- **Email**: jyotirmoy.das@liu.se
- **Documentation**: See README.md
- **Issues**: Check troubleshooting section

---

**Happy Annotating! 🧬**
