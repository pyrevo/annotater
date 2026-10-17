# Deployment

How to build, test, and deploy AnnotateR — locally, in a container, and on
[SciLifeLab Serve](https://serve.scilifelab.se/).

This document is for maintainers. End users who just want to run the app
locally should read [QUICKSTART.md](https://github.com/pyrevo/annotater/blob/main/QUICKSTART.md).

## Contents

- [Prerequisites](#prerequisites)
- [Architecture status](#architecture-status)
- [Architecture / platform](#architecture-platform)
- [Building the container image](#building-the-container-image)
- [Published images (GHCR)](#published-images-ghcr)
- [Local container test](#local-container-test)
- [Port and health check](#port-and-health-check)
- [SciLifeLab Serve setup](#scilifelab-serve-setup)
- [Environment / configuration](#environment-configuration)
  (including [upload size](#upload-size) and [data handling](#data-handling))
- [Single-worker requirement](#single-worker-requirement)
- [Expected startup and resources](#expected-startup-and-resources)
- [Deployment verification](#deployment-verification)
- [Common failure modes](#common-failure-modes)
- [References](#references)

## Prerequisites

- **Docker** (Docker Desktop on macOS/Windows, or the Docker Engine on
  Linux) with build support. On Apple Silicon hosts the image is built for
  `linux/amd64` (below) and runs under x86 emulation: Docker Desktop uses
  Rosetta when that option is enabled (the default in recent releases) and
  QEMU otherwise. The build is slower but functional.
- For Serve deployment: a Docker Hub account or a GitHub account (for
  GHCR), and a SciLifeLab Serve account.
- No other system dependencies are needed to *build or run* the image:
  bedtools is installed inside the image from the base distribution.

## Architecture status

AnnotateR's container has two generations, and this document covers both:

| | **Streamlit image** — published | **React/FastAPI image** — this branch |
|---|---|---|
| Web layer | Streamlit, script `app.py` | React SPA (`frontend/dist`) + FastAPI (`streamlit_app/api_server.py`) |
| Entry point | Streamlit server, port **8501** | `start-script.sh` → Uvicorn, port **8000** |
| Health path | `GET /_stcore/health` | `GET /health` |
| State | Streamlit session state | in-memory API session store (single worker; see [Single-worker requirement](#single-worker-requirement)) |
| Published tags | `0.1.0-rc3` (and `0.1.0-rc2`, running on the public beta) | **none yet** |

The **Streamlit** generation is what the published GHCR images and the current
public beta deployment run, and the sections below that describe it remain the
reference for those images. The **React/FastAPI** generation is what the
`Dockerfile` on this branch builds. It is **not yet published to GHCR and not
yet deployed to SciLifeLab Serve**: its deployment steps below are the
documented plan, not a completed publication. Do not read this document as a
claim that the React/FastAPI image is live anywhere.

## Architecture / platform

**The image is built for `linux/amd64` only.**

- The pinned Polars-Bio release (`polars-bio==0.35.1`) publishes
  manylinux `x86_64` wheels only — there is no `linux/aarch64` wheel, so
  an arm64-native build cannot resolve the pinned dependencies. This was
  re-verified against PyPI during Task 8 (see
  [references.md](references.md)).
- The `Dockerfile` pins the platform at the `FROM` level
  (`ARG PLATFORM=linux/amd64` + `FROM --platform=${PLATFORM}
  python:3.12-slim`), so `docker build` produces an amd64 image regardless
  of the host architecture. The build is multi-stage: a Node 20 stage
  builds the React frontend, and only the built assets (`frontend/dist`)
  are copied into the runtime image.
- SciLifeLab Serve's own build guidance likewise uses
  `docker build --platform linux/amd64 ...`.
- If a future Polars-Bio release ships `linux/aarch64` wheels, the
  platform pin can be relaxed — but only after the full contract suite is
  revalidated on the new platform.

## Building the container image

From the repository root:

```bash
docker build --platform linux/amd64 -t annotater:dev .
```

Python dependencies are installed from the committed `uv.lock` (see
[Dependency management](#dependency-management)), so the full resolved
graph — including transitive dependencies — is the one recorded in the
lock, not whatever is newest on PyPI at build time. The build is
multi-stage: a `node:22-slim` stage runs `npm ci` and `npm run build`
(so the build host needs access to the npm registry), and the runtime
image then installs only the pinned Python dependencies. The remaining
inputs are the base image `python:3.12-slim` (a moving tag; not
digest-pinned) and the distribution bedtools package (Debian bookworm
ships bedtools 2.31.1, matching the validated environment). Image layers
are not claimed to be bit-reproducible.

The image contains only what the app needs:

```
/app
├── app.py                        # legacy Serve entry-point shim (Streamlit generation)
├── start-script.sh               # ENTRYPOINT: single-worker Uvicorn on port 8000
├── pyproject.toml                # dependency declarations (install input only)
├── uv.lock                       # exact locked graph (install input only)
├── streamlit_app/                # application package (api_server.py is the FastAPI app)
├── frontend/dist/                # built React assets, served by FastAPI at /
├── data/examples/                # bundled example inputs (no user data)
├── benchmarks/benchmark_engines.py
└── scripts/
    ├── docker_smoke.sh           # scientific-core smoke
    ├── docker_smoke_api.sh       # served FastAPI/React smoke
    └── offline_smoke.py          # network-disabled scientific smoke
```

The runtime image is non-root: the container runs as `appuser` (UID 1000,
the SciLifeLab Serve standard).

## Dependency management

- `pyproject.toml` declares the direct dependencies (runtime
  `dependencies`, test/lint tools in the `dev` extra).
- `uv.lock` is the exact resolved graph and the single source of truth.
- The `Dockerfile` runs `uv export --frozen --no-dev` on the lock and
  installs the result with `uv pip install --require-hashes --no-deps`:
  no re-resolution, hash-verified, runtime dependencies only. `uv` is
  pinned (`UV_VERSION` build arg) and removed after the install.
- CI runs `uv sync --frozen --extra dev` (same lock, plus dev tools) and a
  `lock-consistency` job running `scripts/export_requirements.sh --check`,
  which fails if `uv.lock` is out of sync with `pyproject.toml` or the
  committed requirements files are stale.
- `requirements.txt` / `requirements-dev.txt` are **generated** from
  `uv.lock` (fully pinned, no hashes) for plain-`pip` users. Do not edit
  them by hand.

To change dependencies intentionally: edit `pyproject.toml`, run
`uv lock` (or `uv lock --upgrade-package <name>` for a single package),
review the `uv.lock` diff, run `scripts/export_requirements.sh`, and
commit all of them together.

`docs/requirements-docs.txt` (MkDocs site build) is a separate,
non-runtime dependency set and is not covered by `uv.lock`.

## Published images (GHCR)

Release images are published to GitHub Container Registry by the
`release-ghcr` GitHub Actions workflow
(`.github/workflows/release-ghcr.yml`). It runs **only on explicit
`workflow_dispatch`** (maintainer action, from `main`) with an explicit
`image_tag` input — it never publishes on every push, and it rejects
`latest`. Each publication is gated before the push by the same in-container
smokes CI runs: the scientific core (`scripts/docker_smoke.sh`), the served
FastAPI/React application (`scripts/docker_smoke_api.sh`), and the
network-disabled scientific runtime (`scripts/offline_smoke.py`).

The published tags so far (`0.1.0-rc1`…`0.1.0-rc3`) are **Streamlit**
images. The React/FastAPI image this branch builds has not been published.

Every published image is immutable and is tagged twice with the **same
digest**:

```text
ghcr.io/pyrevo/annotater:0.1.0-rc3     # release-candidate tag (pre-publication testing; latest published RC)
ghcr.io/pyrevo/annotater:sha-<sha>     # per-commit tag of the exact published commit
```

Conventions:

- **RC tags** (`X.Y.Z-rcN`) are for pre-publication testing, e.g. on
  SciLifeLab Serve before the final release.
- **Final semantic-version tags** (e.g. `0.1.0`) are published later, in
  the same workflow, from the approved final release commit.
- **`latest` is never used** as a deployment reference; Serve image
  fields and any pull commands must use an explicit tag (or a digest).
- **Digest pinning** is available where useful: `docker pull
  ghcr.io/pyrevo/annotater@sha256:<digest>` always resolves the exact
  published image (the published digest is recorded in
  [release-plan-0.1.0.md](https://github.com/pyrevo/annotater/blob/main/docs/release-plan-0.1.0.md)).
- **Package visibility:** Serve pulls the image anonymously, so the GHCR
  *package* must be set to **public** under the repository's Package
  settings. Package visibility is independent of the future Serve
  application visibility (which is configured separately in Serve as
  *Project* during the private testing phase).
- All images are `linux/amd64` (platform pin, see
  [Architecture / platform](#architecture-platform)).

The workflow has no default `image_tag`, and it fails before building if
`image_tag` (or the `sha-<sha>` tag) already exists in GHCR, so a published
tag can never be overwritten. A registry error while checking also fails
the run.

Example publication (GitHub → Actions → `release-ghcr` → Run workflow):

```text
branch: main
image_tag: 0.1.0-rc3
```

### Why `app.py` is still present

The **published Streamlit generation** must name its main file `app.py` in the
image working directory (a SciLifeLab Serve requirement for its Streamlit app
type). The repository's application entry point is
`streamlit_app/streamlit_app.py`; `app.py` is a thin shim that imports the real
module and calls its `main()`. It is retained so the published images stay
runnable and reproducible.

The **React/FastAPI generation** does not go through Streamlit. Its image
`ENTRYPOINT` is `start-script.sh`, which launches Uvicorn serving
`streamlit_app.api_server:app`; the React app is served as static assets by
that same FastAPI process at `/`.

## Local container test

```bash
# 1. Build
docker build --platform linux/amd64 -t annotater:dev .

# 2. Scientific-core smoke (bedtools, both engines, canonical parity)
#    --entrypoint bash overrides the image ENTRYPOINT (start-script.sh),
#    otherwise the args are appended to it and the web server starts.
docker run --rm --entrypoint bash annotater:dev /app/scripts/docker_smoke.sh

# 3. Served-application smoke (startup, /health, routes, sessions, export)
docker run --rm --entrypoint bash annotater:dev /app/scripts/docker_smoke_api.sh

# 4. Offline scientific-runtime smoke (network hard-blocked)
docker run --rm --network none --entrypoint python \
  annotater:dev /app/scripts/offline_smoke.py

# 5. Interactive run
docker run --rm -p 8000:8000 annotater:dev
# -> http://localhost:8000   (health: http://localhost:8000/health)
```

The three smoke scripts are also executed by CI (`.github/workflows/
python-tests.yml`, job `docker-smoke`). What each covers:

- **`scripts/docker_smoke.sh`** — scientific core, server-agnostic:
  1. `bedtools` is on `PATH` at version 2.31.x;
  2. core imports succeed (app package, both engines, canonical adapter);
  3. a canonical smoke annotation on the bundled example inputs completes
     with **both** engines (overlap and closest), and the two canonical
     results pass the same strict comparator used by the parity suite;
  4. hand-computed scientific assertions on tiny inline fixtures pass on
     both engines.
- **`scripts/docker_smoke_api.sh`** — the served application, exactly as the
  container runs it (starts `start-script.sh`): non-root UID 1000, healthy
  startup, `GET /health` (and that it fails while the process is down), the
  React assets served at `/`, `/api/meta`, two independent sessions with
  isolated results, upload cleanup, Bedtools and Polars-Bio execution,
  bundled chromosome normalization, custom mapping, VCF export, and that a
  restart resets session state (no leak).
- **`scripts/offline_smoke.py`** — the scientific runtime with the network
  off (`--network none`, plus a socket-level block): the bundled chromosome
  catalog and a custom mapping load, both engines annotate with strict
  canonical parity, and VCF export works — with no external chromosome data.

The served-application and offline smokes can also be run from pytest,
gated on a built image:

```bash
docker build --platform linux/amd64 -t annotater:ci .
ANNOTATER_TEST_IMAGE=annotater:ci pytest tests/test_container_image.py
```

A passing `docker build` alone is **not** sufficient verification.

## Port and health check

- The **React/FastAPI** image listens on **8000**. `start-script.sh` runs
  `uvicorn streamlit_app.api_server:app --host 0.0.0.0 --port "${PORT}"`
  (`PORT` defaults to 8000). SciLifeLab Serve asks for the port in the app
  settings; 8000 is the expected value for this image.
- The image defines a health check against the FastAPI health route:

  ```
  curl --fail http://localhost:8000/health
  ```

  (`GET /health` returns `{"status": "ok", "version": "0.1.0"}`.) The
  Dockerfile `HEALTHCHECK` uses interval 30 s, timeout 10 s, start period
  30 s, 3 retries; `docker-compose.yml` matches. Serve additionally monitors
  the container itself; the in-image health check is used by Docker and by
  the smoke tests.
- For reference, the **published Streamlit** images listen on **8501** and
  are healthy at `curl --fail http://localhost:8501/_stcore/health`.

## SciLifeLab Serve setup

Verified against the current Serve documentation (see
[References](#references) and [references.md](references.md)). Summary of
the platform requirements this deployment satisfies:

| Requirement | AnnotateR |
|---|---|
| App packaged as a Docker image | yes (above) |
| Main file named `app.py` in the working directory | Streamlit generation only (shim). The React/FastAPI generation needs no `app.py`: its `ENTRYPOINT` is `start-script.sh` |
| Web app listening on the configured port | Streamlit generation: 8501. React/FastAPI generation: **8000**, health at `/health` |
| `linux/amd64` image | yes (pinned in `Dockerfile`) |
| Code publicly available, no sensitive data | code is public; uploaded files are processed by the running app, which deletes its temporary parsing copy immediately after parsing and keeps parsed data and results only in memory for the active session (see [Data handling](#data-handling)) |
| Upload size limit | the Serve platform documents **100 MB per file** for its Streamlit app type ([references.md](references.md)); this applies to the published Streamlit generation. The React/FastAPI generation's platform limit depends on its Serve app type and must be confirmed against the current Serve documentation at deployment time |

### Step-by-step

1. **Publish the image to a registry.** Serve fetches the image from a
   registry (it never uses your local image). Either:

   - **Docker Hub (manual):**

     ```bash
     docker build --platform linux/amd64 \
       -t <your-dockerhub-username>/annotater:<tag> .
     docker push <your-dockerhub-username>/annotater:<tag>
     ```

   - **GHCR (automated):** the `release-ghcr` workflow publishes from
     GitHub Actions on explicit request (see
     [Published images (GHCR)](#published-images-ghcr)). The package must
     be set to *public* under Package settings, since Serve must be able
     to pull it.

   Rules to keep in mind:
   - **Each version needs a unique tag** (e.g. `annotater:v2`,
     `annotater:20260925`). Once an app has been deployed with a tag, that
     tag is frozen — redeploying requires a new tag.
   - The image **must remain available** after deployment; Serve fetches
     it at regular intervals and the app stops working if it disappears.

2. **Create (or sign in to) a Serve account**, then create a **project**
   (Default project template) on the *My projects* page.

3. **Create the app**: click **Create** on the *Streamlit App* card and
   fill in:

   | Field | Value |
   |---|---|
   | Subdomain | e.g. `annotater` → `annotater.serve.scilifelab.se` |
   | Mount path | `None` (AnnotateR does not use persistent storage) |
   | Hardware | default (2 vCPU / 4 GB RAM); request more via serve@scilifelab.se if motivated by a concrete workload |
   | Port | `8501` |
   | Image | `<registry>/<image>:<tag>`, e.g. `<username>/annotater:v1` |
   | Title / Description / Keywords | per your project |
   | Permissions | `Private` or `Link` while developing; `Public` at release (Serve requires apps to become public eventually) |
   | Creators | per your project records |
   | Source code URL | `https://github.com/pyrevo/annotater` |

4. **Update**: publish a new image tag, then in the app *Settings* change
   the Image tag and press *Update*.

#### Deploying the React/FastAPI image (planned)

The steps above use Serve's *Streamlit App* type, which is what the published
`0.1.0-rc*` images use. The React/FastAPI image is a plain web service
(`start-script.sh` → Uvicorn), so when it is published it should be deployed
as a Docker-image web app rather than the Streamlit type. Differences to
apply at that point:

- **Port:** `8000` (the Streamlit type's `8501` does not apply).
- **Health:** `GET /health` (not `/_stcore/health`).
- **No `app.py` requirement:** the image `ENTRYPOINT` starts the server.
- **Single worker:** the image already runs exactly one Uvicorn worker; do
  not add a worker flag (see [Single-worker requirement](#single-worker-requirement)).

This deployment has **not been performed**: the image is not yet published
and the exact Serve app type and platform limits must be confirmed against
the current Serve documentation (see [References](#references)) at that time.
Until then, the only live Serve deployment remains the Streamlit-generation
public beta described below.

No secrets or credentials are used by AnnotateR at runtime; there is
nothing to configure in Serve's environment-variable settings beyond the
defaults in [Environment / configuration](#environment-configuration).

## Environment / configuration

All environment variables are optional. The React/FastAPI image's
entrypoint (`start-script.sh`) reads `PORT` and `FORWARDED_ALLOW_IPS`; the
API reads `MAX_FILE_SIZE_MB` and `ANNOTATER_CORS_ORIGINS`. The published
Streamlit generation instead sets four `STREAMLIT_*` variables, reads
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` if it is set, and uses `TEMP_DIR`
through its file helpers.

**React/FastAPI image (this branch):**

| Variable | Default | Effect |
|---|---|---|
| `PORT` | `8000` | Port Uvicorn binds in `start-script.sh`. |
| `FORWARDED_ALLOW_IPS` | `*` | Trusted proxy address(es) for `--forwarded-allow-ips`, so the TLS-terminating proxy's `X-Forwarded-Proto` is honoured and the session cookie is issued `Secure` over HTTPS. Override if the deployment topology differs. |
| `MAX_FILE_SIZE_MB` | `500` | Per-file upload limit enforced by the API (`/api/upload`); see [Upload size](#upload-size). |
| `ANNOTATER_CORS_ORIGINS` | unset (no cross-origin access) | Comma-separated origin allowlist for credentialed cross-origin API calls, e.g. `https://app.example.org,https://tools.example.org`. The default deployment (React app served from the same host) is same-origin and needs no configuration. A bare `*` entry is rejected at startup: with `allow_credentials=True` it would reflect every request origin. |

The React/FastAPI upload path writes its temporary parsing copy under the
**system** temporary directory (`tempfile.mkdtemp`) and deletes it
immediately after parsing, on success or failure; it does not read
`TEMP_DIR`. `TEMP_DIR` (default `/tmp/annotator`; the image creates it with
world-writable permissions) and `CLEANUP_AFTER_HOURS` (age after which
`cleanup_temp_files` would remove stale files) apply only to the
Streamlit-generation helpers (`save_uploaded_file`, `cleanup_temp_files`),
which the React/FastAPI image does not call.

**Published Streamlit generation (reference):**

| Variable | Default | Effect |
|---|---|---|
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | unset (Streamlit default **200**) | Maximum size of one uploaded file, in MB (see [Upload size](#upload-size)). |
| `STREAMLIT_SERVER_HEADLESS` | `true` (image) | No browser auto-open in the container. |
| `STREAMLIT_SERVER_FILE_WATCHER_TYPE` | `poll` (image) | Avoids inotify limits on volumes. |
| `STREAMLIT_SERVER_ENABLE_CORS` | `false` (image) | Disables CORS. |
| `STREAMLIT_BROWSER_GATHER_USAGE_STATS` | `false` (image) | No usage stats. |

Other settings-style names that appear in
`streamlit_app/config/settings.py` or in `docker-compose.yml` (for example
chunking, worker-count, caching and logging settings) are not read by any
application code path, so setting them has no effect and they are not
supported configuration.

### Upload size

**React/FastAPI image:** the API enforces its own per-file limit,
`MAX_FILE_SIZE_MB` (default **500 MB**): an upload over the limit is rejected
by `/api/upload` with an explicit error rather than being silently truncated.
Change it by setting `MAX_FILE_SIZE_MB`.

**Streamlit generation:** the effective per-file upload limit is Streamlit's
`server.maxUploadSize`, which defaults to **200 MB** in the pinned Streamlit
release (1.64.0); an operator can change it with
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (in MB). On SciLifeLab Serve, the platform
documents a limit of **100 MB** for its Streamlit app type, which applies to
that generation there.

### Data handling

- Uploaded files are processed by the running AnnotateR server.
- In the React/FastAPI image a temporary copy of each upload is written
  under the system temporary directory (`tempfile.mkdtemp`) for parsing and
  deleted immediately afterwards, whether parsing succeeds or fails. In the
  Streamlit generation the copy is written under `TEMP_DIR`.
- Parsed data and results remain only in application memory for the
  active session; AnnotateR does not intentionally persist uploaded files
  or results after that lifecycle.
- Session state is held in the API process's memory and addressed by a
  per-browser cookie, so the API must run a single Uvicorn worker. With more
  than one worker a follow-up request could be routed to a process that does
  not hold the session's state. The bundled `start-script.sh` starts a single
  worker accordingly.
- Local Docker execution processes uploads in the AnnotateR container
  running on the user's own machine; SciLifeLab Serve is not involved.
- Infrastructure-level behavior of a hosting platform (logs, caches,
  proxies, node storage) is outside what AnnotateR controls and is not
  described here.

The repository's `docker-compose.yml` is a development convenience
(it bind-mounts the source tree and `/tmp/annotator`); the bind mount is
not required for, or part of, the supported container behavior.

### Developer toolbar controls

The Streamlit toolbar in the top-right corner (Rerun, Deploy, Clear
cache, developer menu) is controlled with the officially supported
`client.toolbarMode` configuration. The app pins it explicitly in
`streamlit_app/streamlit_app.py` via
`st.set_option("client.toolbarMode", "auto")`. With `auto` (the default
in Streamlit 1.64.0) the developer options are shown only when the app is
accessed through localhost, i.e. by a developer running it locally; a
deployed (Serve) audience connecting from outside localhost gets the clean
viewer toolbar. No CSS/DOM-based hiding is used, and local development
ergonomics (including the local Rerun control) are unchanged.

## Single-worker requirement

The React/FastAPI image keeps each user's parsed data, options, and results in
an **in-memory** session store, addressed by the session cookie: the
unprefixed `annotater_session` over plain HTTP, and — when the request
arrives over HTTPS via the trusted proxy — the `__Host-` prefixed
`__Host-annotater_session`. Both carry a server-generated token and are
`HttpOnly` and `SameSite=Lax`; over TLS the cookie is additionally `Secure`
with `Path=/` and no `Domain` (the `__Host-` prefix enforces exactly that),
and the unprefixed cookie is never read, so a token planted by a sibling
subdomain cannot fixate the session. Because the state lives in one
process's memory, the app **must run exactly one Uvicorn worker**:

- `start-script.sh` starts a single worker and deliberately passes no
  `--workers` flag;
- with more than one worker, a follow-up request (execute, export, paginated
  results) could be routed to a process that does not hold that session's
  state, and the session would appear empty or inconsistent;
- the deployment is therefore vertically scaled (more CPU/RAM), not
  horizontally scaled. Do not add workers, and do not put multiple replicas
  behind a non-sticky load balancer;
- `--proxy-headers` with a trusted `--forwarded-allow-ips` is what lets the
  TLS-terminating Serve proxy influence the `Secure` cookie decision; if the
  proxy is bypassed or untrusted, adjust `FORWARDED_ALLOW_IPS`.

## Expected startup and resources

- Cold start (interpreter + imports + Uvicorn, plus the static React
  assets) takes roughly 10–20 s locally; Serve may need a couple of minutes
  after *Running* before the app answers (stated by Serve). The Streamlit
  generation's cold start is comparable.
- Default allocation (2 vCPU / 4 GB RAM) is sufficient for interactive
  use with files below the 100 MB platform upload cap; the in-container
  smoke test passes within these limits. Very large inputs (hundreds of
  MB) need headroom for canonical frames held in memory — see
  [Limitations](limitations.md).
- The filesystem is ephemeral except for the project *Mount path* (not
  used). Each upload is written to a temporary file under the system
  temporary directory (`tempfile.mkdtemp`) for parsing and deleted
  immediately afterwards; parsed data is held in memory. Intermediate
  bedtools files are likewise written by pybedtools to the system temp
  directory (`TMPDIR` if set).

## Deployment verification

After (re)deploying:

1. Open the app URL (or `http://localhost:8000` for a local React/FastAPI
   container, `http://localhost:8501` for a local Streamlit-generation
   container).
2. Confirm the service is healthy: `GET /health` must return
   `{"status": "ok", ...}` (React/FastAPI image) — the same check Docker and
   Serve use. For the Streamlit generation, `GET /_stcore/health`.
3. Run the built-in check: upload `data/examples/example_coordinates.bed`
   as coordinates and `data/examples/example_annotations.gff3` as
   annotations, run **overlap**, then rerun with the other engine — both
   must return identical canonical results (the UI states the backends
   are interchangeable).
4. Confirm the deployed image version separately from the application
   version: the running app reports the application version (`0.1.0`, which is
   unchanged across the release candidates and the final release), so it cannot
   identify an RC tag (`/api/meta` for the React/FastAPI image; the footer for
   the Streamlit generation). Check the image's OCI label instead, e.g.
   `docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' ghcr.io/pyrevo/annotater:<tag>`,
   which the `release-ghcr` workflow sets to the published tag.
5. For Serve: confirm the container status is *Running* and the health
   check in the app overview is green.

### Current public beta deployment

The public beta deployment at <https://annotater.serve.scilifelab.se> is
**running the `0.1.0-rc2` image** — the **Streamlit** generation, not the
React/FastAPI image described above. The maintainer updated the existing
Serve app from `0.1.0-rc1` by changing only the container image
reference; the deployment is healthy and the application loads. The
deployment is referenced by tag, not pinned by digest; the verified GHCR
digest of that tag is recorded separately in
[Release-candidate publications](https://github.com/pyrevo/annotater/blob/main/docs/release-plan-0.1.0.md#release-candidate-publications).
This is a pre-release deployment: final `v0.1.0` has not been released, and
the React/FastAPI image has not been deployed.

## Common failure modes

| Symptom | Likely cause / fix |
|---|---|
| `docker build` fails in `pip install` on an Apple Silicon host | Building arm64-native. Build with `--platform linux/amd64` (the `Dockerfile` already pins amd64; on Apple Silicon enable amd64 emulation in Docker Desktop — Rosetta when available — for the faster path). |
| Serve keeps serving an old version | Reused an image tag. Publish a **new unique tag** and update the Image field. |
| Serve app never becomes available | Image tag not pulled (private GHCR package, image deleted, or typo in the Image field). The image must stay publicly available at all times. |
| Uploads above ~100 MB are rejected on Serve | Platform upload limit (Streamlit apps). When running the image yourself, the limit is Streamlit's 200 MB default; change it with `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (see [Upload size](#upload-size)). |
| bedtools engine errors only in the container | `bedtools` not on `PATH` inside the image — run `scripts/docker_smoke.sh`; it asserts version 2.31.x. |
| App is slow on Serve | Default 2 vCPU/4 GB allocation. Request more resources via serve@scilifelab.se with a concrete workload example. |
| Positions ≥ 2³¹ error from the Bedtools engine | pybedtools packs coordinates into a 32-bit field (see [benchmark docs](benchmark.md) / Limitations). Not reachable with natural chromosomes. |

## References

Current official documentation (retrieved 2026-09-25; exact links are
kept in [references.md](references.md)):

- SciLifeLab Serve — Streamlit app hosting guide (step-by-step, resource
  defaults, upload limit, image/tag rules)
- SciLifeLab Serve — application hosting overview (port range, public
  code/data, no databases)
- Docker build reference (`--platform`)
- PyPI — `polars-bio` (wheel availability per platform)