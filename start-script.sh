#!/bin/bash
set -e

# SciLifeLab Serve startup script for AnnotateR
# This script is executed by SciLifeLab Serve when deployed as a Custom App.

PORT="${PORT:-8000}"

# The FastAPI session store lives in this process's memory, so the app MUST
# run a single Uvicorn worker (see streamlit_app/api_sessions.py). Do NOT add
# --workers here: multiple workers would route a follow-up request to a
# process that does not hold the user's session state.
#
# --proxy-headers with a trusted forwarded-allow-ips lets the
# TLS-terminating reverse proxy (SciLifeLab Serve) pass X-Forwarded-Proto
# through, so the session cookie is issued with Secure over HTTPS. The
# container is intended to be reachable only through that proxy; override
# FORWARDED_ALLOW_IPS if the deployment topology differs.
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

echo "Starting AnnotateR on port ${PORT} (single worker)..."
exec uvicorn streamlit_app.api_server:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}"
