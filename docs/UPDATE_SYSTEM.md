# Update system

## Detection

`afid updates check` runs discovery for every provider that supports it and compares the
result with `database/sources/<provider>.json`:

| Situation | Reported as |
|---|---|
| new item | `added` |
| revision marker changed (git blob SHA, content hash, ETag) | `changed` |
| item absent from a complete, unfiltered listing | `removed_from_source` (staging data kept) |
| provider failed, or listing partial/filtered | `unavailable` (nothing deleted) |
| codename already cataloged under another brand | `unverified` identity item for review |
| source lists model numbers absent from the verified record | `unverified` identity item |

For dump providers the items are dump branches and the marker is the branch commit SHA;
a branch whose commit changed is `changed`, and the matrix planner treats it as new work.
`check-updates.yml` passes `--skip-dumps` (dump listings are long; `discover-dumps.yml`
handles them). A dump listing that returns fewer than `min_projects` projects is a failure,
so it can never mark items removed (`test_truncated_listing_is_a_failure_and_keeps_snapshot`).

Check timestamps never count as change. `--write` stores the snapshot and staging candidates;
files are rewritten only when content changes, so an unchanged source produces no Git diff.

`afid updates report` compares consecutive firmware builds of each device: components
added/removed, `checksum_changed`, `license_changed`, dependency edges added/removed.

## Workflows

| Workflow | Trigger | Writes |
|---|---|---|
| `check-updates.yml` | daily 03:17 UTC, manual, registry change on `dev` | PR when metadata changed |
| `source-discovery.yml` | manual (provider, brand, open_pr) | PR when requested and changed |
| `refresh-catalog.yml` | weekly, manual | PR when generated files are stale |
| `ingest-firmware.yml` | manual | report artifact only |
| `discover-dumps.yml` | weekly (Mon 04:41 UTC), manual | PR when a dump snapshot changed |
| `download-dumps.yml` | weekly (Tue 06:13 UTC), manual (mode, provider, item, batch) | PR with analysis results |
| `plan-firmware-matrix.yml` | called by `download-dumps`, manual | plan artifact only |
| `analyze-components.yml` | called by `download-dumps`, manual (one item) | delta artifacts only |
| `reconcile-catalog.yml` | called by `download-dumps`, manual (run id) | PR when `database/` changed |
| `dump-and-analyze.yml` | manual (URL from an allowlisted host + SHA-256) | PR with DumprX metadata |
| `container-images.yml` | PRs/pushes touching images, manual (publish) | GHCR images on explicit publish only |
| `validate.yml` | PRs, pushes to `dev`/`main`, manual | nothing |
| `security-audit.yml` | weekly, PRs, manual | nothing |

The checking job always runs with `contents: read`. A separate `propose` job (contents,
pull-requests and actions write) applies the checked patch and runs
`scripts/open_data_pr.py`, which:
- refuses any change outside `database/`;
- re-runs `afid database validate --check-index` and `afid policy check`;
- creates a new branch and a commit through the GraphQL `createCommitOnBranch` API, so the
  commit is created and signed by GitHub instead of being an unsigned bot commit (confirm the
  "Verified" badge on the first run);
- opens a pull request against the default branch (never pushes to it, never force-pushes);
- dispatches `validate.yml` on the new branch, because pull requests opened with
  `GITHUB_TOKEN` do not trigger workflows by themselves.

No pull request is created when there is no diff.

## Enabling scheduled updates

1. Merge the workflows into the default branch (schedules run only from the default branch).
2. Settings -> Actions -> General -> Workflow permissions: keep "Read repository contents";
   enable **"Allow GitHub Actions to create and approve pull requests"** (needed by `propose`).
3. Optional: repository variable `AFID_COMMIT_TRAILER` (Settings -> Secrets and variables ->
   Actions -> Variables), e.g. `Signed-off-by: Name <email>`, appended to bot commit messages.
4. Optional: branch protection on the default branch requiring `validate` to pass.
5. Run `check-updates` once manually (Actions -> check-updates -> Run workflow) and review the
   resulting pull request.
