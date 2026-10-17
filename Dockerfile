# AnnotateR production image.
#
# Multi-stage build:
# Stage 1: Build the modern React frontend with Node 22
# Stage 2: Production Python image with FastAPI backend, bedtools, and Polars-Bio
#
# Platform: pinned to linux/amd64 by default (ARG PLATFORM). The pinned
# polars-bio release provides manylinux x86_64 wheels only (no
# linux/aarch64 wheel).
ARG PLATFORM=linux/amd64

# --- Stage 1: Frontend Build ---
FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Production Python Image ---
FROM --platform=${PLATFORM} python:3.12-slim

# System dependencies:
#   bedtools - required by BedtoolsEngine (2.31.1 in Debian)
#   curl     - required by container health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    bedtools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies: installed from the committed uv.lock (the single source of
# truth for the resolved graph, including transitive dependencies), never
# re-resolved by pip. `uv export --frozen` fails instead of updating the lock,
# and `uv pip install --require-hashes` makes the install verify every artifact
# against the hashes recorded in uv.lock. Runtime dependencies only (no dev
# extra). uv is pinned and removed again after the install, so it is not part
# of the runtime image.
# To change dependencies intentionally see docs/deployment.md.
ARG UV_VERSION=0.11.8
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/locked-requirements.txt \
    && uv pip install --system --no-cache --require-hashes --no-deps -r /tmp/locked-requirements.txt \
    && rm /tmp/locked-requirements.txt \
    && pip uninstall -y uv

# Application code & dependencies
COPY app.py ./app.py
COPY start-script.sh ./start-script.sh
COPY streamlit_app/ ./streamlit_app/
COPY data/examples/ ./data/examples/
COPY benchmarks/benchmark_engines.py ./benchmarks/benchmark_engines.py
COPY scripts/docker_smoke.sh ./scripts/docker_smoke.sh
COPY scripts/docker_smoke_api.sh ./scripts/docker_smoke_api.sh
COPY scripts/offline_smoke.py ./scripts/offline_smoke.py
RUN chmod +x ./scripts/docker_smoke.sh ./scripts/docker_smoke_api.sh ./start-script.sh

# Copy built frontend assets from builder stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Non-root user setup for container security
# SciLifeLab Serve standard specifies UID 1000
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /tmp/annotator && \
    chown -R appuser:appgroup /app /tmp/annotator && \
    chmod 777 /tmp/annotator

# Default port for the AnnotateR FastAPI/React web service (start-script.sh).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

ENV PYTHONUNBUFFERED=1

# Run as non-root user
USER appuser

# Entry point: runs the start-script.sh (SciLifeLab Serve requirement for Custom Apps)
ENTRYPOINT ["./start-script.sh"]

