# v0.1.0 release plan (to run AFTER manual GUI acceptance)

## Current release state

- **RC1 was published:** the immutable image `0.1.0-rc1` exists in GHCR
  (see [Release-candidate publications](#release-candidate-publications)
  for the source commit and digest). That record is historical and is
  not rewritten.
- **RC2 was published:** `0.1.0-rc2` was published to GHCR from source
  commit `4edb362e9143286754a41dabeb81f58034f2debc` with digest
  `sha256:a0b1b7e8941f0660208d90876a6e0aa3cd73ca9ec5e9704fdb2746c659d1f3f9`
  and verified independently (see
  [Release-candidate publications](#release-candidate-publications)).
  RC1 and RC2 remain published as historical release candidates.
- **RC3 is the latest published pre-release:** `0.1.0-rc3` was published
  to GHCR (the same digest is also tagged `sha-7592b9d`) from source
  commit `7592b9de803ea19cc10042c2a10515c350d4fbfc` with digest
  `sha256:d4ea46ae879c60c34f98fcabd3545e04281dea40ab56f432c0aa2a10a021f661`
  (see
  [Release-candidate publications](#release-candidate-publications)).
  RC3 is the first release candidate that ships assembly-aware chromosome
  normalization (bundled assembly registries, custom chromosome mappings,
  VCF `##contig` normalization). It is a pre-release, not the final
  `v0.1.0`.
- **SciLifeLab Serve is running RC2:** the existing AnnotateR app at
  <https://annotater.serve.scilifelab.se> was updated from RC1 to RC2 by
  changing only the container image reference; the deployment is healthy.
  RC3 has **not** been deployed to Serve.
- **`main` may be ahead of RC3:** RC2 contains only the source at
  `4edb362`, which predates the assembly-aware chromosome normalization
  that first shipped in RC3 (`7592b9d`).
- **A pre-release is tagged, released and archived on Zenodo; final
  `v0.1.0` has not been released:** the `v0.1.0-rc3` git tag, its GitHub
  Release and the Zenodo archive exist (Zenodo version DOI
  `10.5281/zenodo.23415802`, Concept DOI `10.5281/zenodo.23415801`; see
  [GitHub Release and Zenodo archive](#github-release-and-zenodo-archive)).
  There is still no final `v0.1.0` git tag, no final-release GitHub
  Release, no `0.1.0` image tag and no `latest` tag. Version metadata is
  aligned to `0.1.0` (`release-prep-0.1.0`), but the formal release
  happens only after the GUI is accepted.

**License: RESOLVED (2026-09-28).** The maintainers selected
BSD-3-Clause as the canonical license for the current AnnotateR
project/release after reviewing the provenance audit (see
`docs/implementation-notes.md`); LICENSE, README badge/text, app footer,
`pyproject.toml`, and `CITATION.cff` now all agree on BSD-3-Clause.
This former release gate is closed.

Remaining release gate (in order):

1. Manual GUI acceptance.
2. Apply any final approved GUI polish from the acceptance review
   (separate, small change; re-verify tests).
3. Run the full test suite: `.venv/bin/python -m pytest` (expected: all
   tests pass, 0 failed, 0 skipped; the test count grows with the suite,
   so record the exact count at release time. At the time of this
   cleanup `main` measured 1462 passed.)
4. Docker smoke: `docker build --platform linux/amd64 -t annotater . &&
   docker run --rm -p 8501:8501 annotater` and confirm `/_stcore/health`
   plus the manual GUI checks.
5. Align final release metadata:
   - confirm `pyproject.toml` version == `Settings.VERSION` == footer ==
     `0.1.0`; confirm all license declarations remain BSD-3-Clause;
   - add `version: 0.1.0` and the release date to `CITATION.cff`
     (still no invented DOI or publication).
5a. **Release-candidate image (this step is separate from the final
    release above):** publish `ghcr.io/pyrevo/annotater:0.1.0-rc1` (plus
    the per-commit `sha-<sha>` tag, same digest) from the verified `main`
    commit via the `release-ghcr` workflow (explicit `workflow_dispatch`,
    `image_tag: 0.1.0-rc1`; see
    [deployment.md — Published images (GHCR)](deployment.md#published-images-ghcr)).
    Set the GHCR *package* to public so Serve can pull it, then let the
    maintainer test the RC on SciLifeLab Serve (private Project
    visibility) before the final release gate below. RC1 publication
    record: see [Release-candidate publications](#release-candidate-publications).
5b. **RC2 (completed):** `0.1.0-rc2` was published with the same
    `release-ghcr` workflow from source commit `4edb362`, verified
    independently by digest (Docker smoke, scientific smoke, Polars-Bio
    concurrency regression, issue #37 regression), and deployed by the
    maintainer to the existing SciLifeLab Serve app. RC1 was verified
    unchanged before and after. The final-release steps above (6-9) remain
    pending.
5c. **RC3 (completed):** `0.1.0-rc3` was published with the same
    `release-ghcr` workflow from source commit `7592b9d`, then tagged
    `v0.1.0-rc3`, published as the first GitHub Release, and archived on
    Zenodo (version DOI `10.5281/zenodo.23415802`; Concept DOI
    `10.5281/zenodo.23415801`). RC3 has not been deployed to Serve. The
    final-release steps below (6-9) remain pending.
6. Tag `v0.1.0` on the release commit.
7. Create the GitHub Release from the tag, including the first-release
   summary (canonical coordinate contract; Bedtools and Polars-Bio
   parity; overlap / left / min_overlap / strand / contains / within /
   closest; Streamlit integration; reproducible Docker deployment;
   benchmark infrastructure).
8. Deploy the approved image (SciLifeLab Serve or other target) with the
   `v0.1.0` tag.
9. Post-deployment smoke test: health endpoint, one real run per engine
   (Bedtools and Polars-Bio), result export.

## Release-candidate publications

Immutable GHCR images published before the final `v0.1.0` release
(process: [deployment.md — Published images (GHCR)](deployment.md#published-images-ghcr)).

| RC | Source commit | Image tags (same digest) | Digest | Published |
|---|---|---|---|---|
| 0.1.0-rc1 (historical) | `7269b47cdade3511cd317634c304ebadf3d10345` (main) | `ghcr.io/pyrevo/annotater:0.1.0-rc1`, `ghcr.io/pyrevo/annotater:sha-7269b47` | `sha256:76b5574bb506abfa2d9a0fdeea51f0d5bca941e155d8e26e62cb1fcd73f10d91` (both tags, verified from the GHCR push receipts) | 2026-09-29 (release-ghcr workflow run #1: [actions/runs/36564727227](https://github.com/pyrevo/annotater/actions/runs/36564727227), platform `linux/amd64`) |
| 0.1.0-rc2 (historical) | `4edb362e9143286754a41dabeb81f58034f2debc` (main) | `ghcr.io/pyrevo/annotater:0.1.0-rc2`, `ghcr.io/pyrevo/annotater:sha-4edb362` | `sha256:a0b1b7e8941f0660208d90876a6e0aa3cd73ca9ec5e9704fdb2746c659d1f3f9` (both tags verified to resolve to it) | 2026-10-01 (release-ghcr workflow run: [actions/runs/36862770914](https://github.com/pyrevo/annotater/actions/runs/36862770914), platform `linux/amd64`) |
| 0.1.0-rc3 (latest published pre-release) | `7592b9de803ea19cc10042c2a10515c350d4fbfc` (main) | `ghcr.io/pyrevo/annotater:0.1.0-rc3`, `ghcr.io/pyrevo/annotater:sha-7592b9d` | `sha256:d4ea46ae879c60c34f98fcabd3545e04281dea40ab56f432c0aa2a10a021f661` (both tags verified to resolve to it) | 2026-10-03 (release-ghcr workflow run: [actions/runs/37112430397](https://github.com/pyrevo/annotater/actions/runs/37112430397), platform `linux/amd64`) |

Serve deployment history: the project-restricted beta app at
<https://annotater.serve.scilifelab.se> ran RC1 first and now runs RC2
(image reference updated by the maintainer; referenced by tag, not
digest). RC3 has **not** been deployed to Serve. RC1 and RC2 are still
published and their digests are unchanged.

### GitHub Release and Zenodo archive

The first GitHub Release is the pre-release `v0.1.0-rc3`
(<https://github.com/pyrevo/annotater/releases/tag/v0.1.0-rc3>), created
from the `v0.1.0-rc3` git tag, which points at commit
`cb7c9c5374992a89e207be6799449895d035f7d9`. That commit differs from the
RC3 image source (`7592b9d`) only in `CITATION.cff`. The release is
archived on Zenodo:

- **Version DOI** (the RC3 release): `10.5281/zenodo.23415802` —
  <https://zenodo.org/records/23415802>
- **Concept DOI** (all versions; used for a general project citation):
  `10.5281/zenodo.23415801` — <https://doi.org/10.5281/zenodo.23415801>

This is a pre-release archive: the final `v0.1.0` release has not been
published.

Package visibility note (2026-09-29): the `annotater` container package was
created by the workflow as **private** (default for a private repository)
and the automated token could not change it (no `packages` scope). The
maintainer must set it to **public** under the repository's Package
settings (or make the repository public) before Serve can pull it
anonymously — the agent token of this session only has
`gist, read:org, repo, workflow`.

Final-release images (`0.1.0`) are published only after step 5/6/7 above
have been approved.

Follow-up cleanup (not part of the release gate): final disposition of
the legacy R files per `docs/legacy.md` (delete vs. move to `legacy/`).
**Resolved:** the legacy files were deleted from the repository in
preparation for publication; see `docs/legacy.md`.