# Resource budgets

All limits live in `config/settings.yml` under `resources`: `defaults`, `hard_caps` and
`minimums`. Each can be overridden per run with an environment variable `AFID_<NAME>`
(workflows map repository variables onto them); overrides are clamped to the caps and
minimums (`test_limits_env_override_is_clamped`), and a malformed or negative value is an
error, never silently ignored.

| Name | Default | Hard cap | Used by |
|---|---|---|---|
| `MAX_DISCOVERY_PARALLEL` | 2 | 4 | `discover-dumps.yml` `max-parallel` (variable `AFID_MAX_DISCOVERY_PARALLEL`) |
| `MAX_DOWNLOAD_PARALLEL` | 1 | 2 | concurrency profile from `afid resources`; each firmware job downloads one file |
| `MAX_EXTRACT_PARALLEL` | 1 | 2 | concurrency profile; forced to 1 below 8 GiB available memory; each DumprX job unpacks one file |
| `MAX_ANALYSIS_PARALLEL` | 2 | 4 | `analyze-components.yml` `max-parallel` |
| `MAX_ITEMS_PER_RUN` | 20 | 256 | matrix batch size (GitHub allows 256 jobs per matrix) |
| `MAX_DOWNLOAD_BYTES` | 4 GiB | 32 GiB | `afid firmware download`: Content-Length check and streaming cut-off |
| `MAX_EXTRACTED_BYTES` | 20 GiB | 64 GiB | extraction / DumprX output size |
| `MAX_FETCH_FILES` | 400 | 2000 | files fetched per dump item |
| `MAX_FETCH_BYTES` | 512 MiB | 4 GiB | bytes fetched per dump item (64 MiB per file) |
| `DISK_RESERVE_BYTES` | 5 GiB | 100 GiB (minimum 1 GiB) | free space every heavy step must leave |
| `JOB_TIMEOUT_MINUTES` | 60 | 360 | per-item job timeout |
| `RETRY_LIMIT` | 3 | 6 | HTTP retries; analysis attempts per item revision |
| `HTTP_TIMEOUT` | 60 s | 300 s | every HTTP request |
| `RATE_LIMIT_DELAY` | 0.5 s | 30 s (minimum 0.2 s) | delay between requests to one host (the stricter of this and `network.min_interval_seconds` wins) |

## Checks before heavy work

- Workflows print `nproc`, `free -h`, `df -h` and `df -i`, then `afid resources`, which
  reports the machine, the effective limits and the derived concurrency profile, and exits 1
  when free disk is below `DISK_RESERVE_BYTES`.
- `afid firmware download` refuses a response whose Content-Length plus the reserve exceeds
  free disk, stops streaming at `MAX_DOWNLOAD_BYTES`, rejects HTML error pages, detects
  truncation and verifies the SHA-256 (`test_download_rejects_html_oversize_and_truncation`,
  `test_download_checks_disk_budget`, `test_download_retries_then_verifies_checksum`).
- Remote analysis checks disk for the full fetch budget first. It spends at most 75% of the
  budget on the selected files, then follows libraries the fetched binaries need, then
  spends the rest (`test_fetch_budget_keeps_build_prop_first`).
- DumprX refuses to start without about three times the input size free, and its output is
  measured against `MAX_EXTRACTED_BYTES`.

Container limits restrict a job; they never add resources a runner does not have. A
GitHub-hosted `ubuntu-24.04` runner is enough for dump analysis (megabytes per item); large
firmware through DumprX may need a larger or self-hosted runner.
