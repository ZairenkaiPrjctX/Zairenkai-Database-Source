# Troubleshooting

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | a provider check failed, or `doctor`/`providers test` found problems |
| 2 | configuration error (missing/invalid `config/*.yml`, repository root not found) |
| 3 | validation failed (`database validate`, stale index, invalid generated records) |
| 4 | required external tool missing (message names the tool and install command) |
| 5 | unsafe archive (traversal, escaping link, size/member limit) |
| 6 | unsupported format |
| 7 | provider error (network, HTTP status after retries) |
| 8 | provider does not support the operation (message gives the documented limitation) |
| 9 | policy or security scan findings |
| 10 | record or path not found |
| 11 | corrupt archive or checksum mismatch |
| 12 | ingestion staged: identity could not be verified |
| 13 | resource budget: not enough free disk for the planned work (message gives the numbers) |

## Common problems

- **"no config/settings.yml found"**: run inside the repository, pass `--root`, or set
  `AFID_ROOT`.
- **Partition not extracted, note mentions a tool**: install it (`afid doctor` lists all
  tools and what each is for) and re-run; work directories are keyed by archive SHA-256.
- **Status `staged`**: the firmware had no usable `ro.product.*.device` / OTA `pre-device`,
  or brand/build id could not be determined. Pass `--brand` if the brand was the problem; a
  codename cannot be forced.
- **`--codename ... contradicts firmware evidence`**: the package is for a different device
  than you expected. Check the package.
- **`database validate --check-index` reports stale files**: run `afid database index` and
  `afid dependencies build`, commit the result.
- **LineageOS discovery fails offline**: point `AFID_LINEAGE_WIKI_DIR` at an existing checkout.
- **Workflow could not open a PR**: enable "Allow GitHub Actions to create and approve pull
  requests" in repository settings (see `docs/UPDATE_SYSTEM.md`).
- **`afid discover` asks for `--provider`, `--brand` or `--all`**: discovery is explicit
  because dump listings are long; `afid discover --all --skip-dumps` checks the fast sources.
- **Dump discovery `failed: listing returned N projects, expected at least M`**: the host
  returned a truncated listing (outage, rate limit). Nothing was changed; retry later. Lower
  `min_projects` in `config/provider_registry.yml` only if the source really shrank.
- **gitlab.com 429 / slow discovery**: the unauthenticated API allows 500 requests per window;
  AFID waits for `ratelimit-reset` and honours `Retry-After`. Raise `AFID_RATE_LIMIT_DELAY`.
- **Dump item `unresolved` with "does not map to one AFID brand"**: the build.prop brand is
  not in `config/brands.yml` (e.g. `alps`). Add the brand (with evidence) if it is a real
  product brand; reference-design brands should stay in staging.
- **`skipped_budget` in an analysis report**: the item has more candidate files than
  `MAX_FETCH_FILES`/`MAX_FETCH_BYTES`; raise them for that run.
- **`DumprX run refused`**: run `afid providers health --provider dumprx` inside the worker
  image; it lists each failed guard (revision, hash, credential file, network).
- **`firmware download`: "no download hosts are allowed"**: by design; see
  `docs/FIRMWARE_INGESTION.md`.
- **Files written by a container are unreadable on the host**: catalog JSON is written 0644;
  older files written 0600 by earlier versions can be fixed with `chmod 644`.
