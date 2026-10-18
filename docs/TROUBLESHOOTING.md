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
