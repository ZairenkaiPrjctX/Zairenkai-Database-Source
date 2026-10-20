# Matrix pipeline

How thousands of dump items are processed on GitHub Actions without one job doing
everything, without exceeding GitHub limits, and without one failure spoiling the rest.

```
discover-dumps.yml      lists sources            -> PR: database/sources/<provider>.json
download-dumps.yml      orchestrates one batch:
  plan-firmware-matrix.yml   afid matrix plan     -> matrix JSON (<= 256 entries)
  analyze-components.yml     one job per entry    -> artifact delta-<id> (delta store + report)
  reconcile-catalog.yml      afid catalog reconcile -> PR: database/ changes
```

## Item statuses

| Status | Meaning | Planned again? |
|---|---|---|
| `discovered` | listed by the source, never processed at this revision | yes |
| `analyzed` | cataloged from this source at this revision | no (`unchanged` afterwards) |
| `unchanged` | a catalog `source_ref` already records this provider, item and revision | no |
| `unresolved` | processed, identity could not be verified (staged) | no, until the revision changes |
| `failed` | processing failed; `attempts` counted per revision | yes, until `RETRY_LIMIT` attempts |
| `metadata_verified`, `download_pending`, `downloaded`, `extracted`, `validated`, `license_review_required`, `restricted` | reserved for the DumprX/firmware path and later stages; accepted by the state schema | per status |

Statuses come from three committed sources, so the plan is reproducible: the discovery
snapshot (`database/sources/<provider>/*.json`), the catalog's `source_refs`, and the ingestion state
(`database/state/<provider>.json`, schema `schemas/state.schema.json`).

## Planning

```bash
afid matrix plan --mode eligible-batch                          # first batch of eligible items
afid matrix plan --mode full-eligible-catalog --batch-index 3   # batch 3 of all eligible items
afid matrix plan --mode selected-item --item 'nothing/Galaga@<branch>' --provider android_dumps_gitlab
afid matrix plan --mode metadata-only                           # statuses only, no work
```

- Eligible items are ordered by (provider, item id): the same inputs always give the same
  plan (`test_plan_is_deterministic_and_ids_are_stable`).
- Batch size is `--batch-size`, capped by `MAX_ITEMS_PER_RUN` (default 20, hard cap 256) and
  by GitHub's 256-job matrix limit (`test_batches_never_exceed_github_limit`).
- Each entry has a stable 16-hex-digit `id` derived from provider, item and revision, used
  for artifact names.
- `full-eligible-catalog` is processed one batch per workflow run. Because finished items
  drop out of the eligible set after each reconcile, batch 0 of the next run is new work.

## Per-item jobs

`analyze-components.yml` runs `afid firmware analyze --out <delta>` per entry with
`fail-fast: false` and `max-parallel` from the `AFID_MAX_ANALYSIS_PARALLEL` variable. A job
never writes the repository: it uploads `delta-<id>`, a directory with the `database/`
layout plus `item-report.json`. A failed analysis still writes its report, so the attempt
is recorded. Jobs have read-only tokens and no secrets.

## Reconcile

`afid catalog reconcile --deltas <dir>` merges every delta:

- each record is schema-validated and placed by its **content** (brand, codename, build),
  never by the delta's paths; invalid or foreign records are rejected and reported
  (`test_reconcile_rejects_tampered_or_foreign_deltas`);
- a firmware build already cataloged from another source keeps its components and gains a
  `source_ref` when fingerprint and common file hashes agree
  (`test_same_build_on_two_hosts_is_one_firmware`); otherwise it is a conflict, staged as
  `codename_status: conflict` and nothing is overwritten (`test_conflicting_dump_is_quarantined`);
- community candidates for a codename that is now verified are absorbed;
- the ingestion state is updated from each `item-report.json`
  (`test_failed_items_retry_until_exhausted_and_new_revision_resets`);
- nothing is deleted; reconciling the same deltas again writes nothing.

The reconcile job regenerates `index.json`/`statistics.json`, runs `afid catalog validate`
and `afid policy check`, and opens a PR through `scripts/open_data_pr.py` only when
`database/` changed.

## Running it

| Goal | How |
|---|---|
| See what would run | dispatch `plan-firmware-matrix.yml`, or `afid matrix plan --mode metadata-only` |
| One firmware | dispatch `download-dumps.yml` with mode `selected-item`, provider and item id (or `analyze-components.yml` for a single job without reconcile) |
| A bounded batch | dispatch `download-dumps.yml` with mode `eligible-batch` (also runs weekly) |
| The whole eligible catalog | dispatch `download-dumps.yml` with mode `full-eligible-catalog`, `batch_index` 0, merge the PR, repeat |
