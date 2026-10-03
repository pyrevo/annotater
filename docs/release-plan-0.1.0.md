# v0.1.0 release plan (to run AFTER manual GUI acceptance)

## Current release state

- **RC1 was published:** the immutable image `0.1.0-rc1` exists in GHCR
  (see [Release-candidate publications](#release-candidate-publications)
  for the source commit and digest). That record is historical and is
  not rewritten.
- **RC2 is the latest published pre-release:** `0.1.0-rc2` was published
  to GHCR from source commit `4edb362e9143286754a41dabeb81f58034f2debc`
  with digest
  `sha256:a0b1b7e8941f0660208d90876a6e0aa3cd73ca9ec5e9704fdb2746c659d1f3f9`
  and verified independently (see
  [Release-candidate publications](#release-candidate-publications)).
  RC1 is unchanged and remains a historical release candidate.
- **SciLifeLab Serve is running RC2:** the existing AnnotateR app at
  <https://annotater.serve.scilifelab.se> was updated from RC1 to RC2 by
  changing only the container image reference; the deployment is healthy.
- **`main` may be ahead of RC2:** RC2 contains only the source at
  `4edb362`. Assembly-aware chromosome normalization (bundled assembly
  registries, custom chromosome mappings, VCF `##contig` normalization)
  is not part of RC2; it is expected to ship in a later release
  candidate, and no such image has been published or deployed.
- **Final `v0.1.0` has not been released:** there is no `v0.1.0` git
  tag, no GitHub Release, no `0.1.0` image tag, no `latest` tag and no
  Zenodo record or DOI. Version metadata is
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
| 0.1.0-rc2 (latest published pre-release) | `4edb362e9143286754a41dabeb81f58034f2debc` (main) | `ghcr.io/pyrevo/annotater:0.1.0-rc2`, `ghcr.io/pyrevo/annotater:sha-4edb362` | `sha256:a0b1b7e8941f0660208d90876a6e0aa3cd73ca9ec5e9704fdb2746c659d1f3f9` (both tags verified to resolve to it) | 2026-10-01 (release-ghcr workflow run: [actions/runs/36862770914](https://github.com/pyrevo/annotater/actions/runs/36862770914), platform `linux/amd64`) |

Serve deployment history: the project-restricted beta app at
<https://annotater.serve.scilifelab.se> ran RC1 first and now runs RC2
(image reference updated by the maintainer; referenced by tag, not
digest). RC1 is still published and its digest is unchanged.

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