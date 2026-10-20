# AWS CodeBuild metadata pipeline

A small, manually started pipeline that discovers firmware **metadata** within strict
limits, validates it, and writes one JSON run manifest. Its first phase only runs an
offline, synthetic dry-run in AWS CodeBuild. It can also upload that manifest to the
existing S3 staging prefix, but only when explicitly enabled.

It never downloads firmware. Metadata discovery and binary acquisition are separate stages,
and only discovery exists here. Binary acquisition stays with the existing, operator-driven
`afid` commands (docs/FIRMWARE_INGESTION.md).

Related: [AWS setup](AWS_SETUP.md), [cost control](COST_CONTROL.md),
[security](SECURITY.md#aws-codebuild-metadata-pipeline).

## Layout

| Path | Role |
|---|---|
| `registry/sources.json` | Versioned source registry; every source is disabled until reviewed |
| `registry/fixtures/synthetic-dry-run.json` | Offline synthetic items for the dry-run (`.invalid` hosts) |
| `schemas/source-registry.schema.json` | Registry schema |
| `schemas/firmware-record.schema.json` | Canonical firmware record |
| `schemas/run-manifest.schema.json` | Run manifest (records, rejected items, counts) |
| `src/afid/pipeline/` | Implementation: `urlpolicy`, `registry`, `records`, `discovery`, `run`, `validation`, `publish` |
| `tools/ingest.py`, `tools/validate.py`, `tools/publish_manifest.py` | Command-line entry points |
| `tests/pipeline/` | Offline tests (`unittest`; pytest collects them too) |
| `buildspec.yml` | CodeBuild build specification (version 0.2) |
| `infra/cloudformation/codebuild.yml` | CodeBuild project, service role and log group |

### What is reused from AFID

The pipeline does not duplicate AFID's existing code:
- **HTTP client:** `afid.download.HttpClient`, which handles timeouts, bounded retries of
  transient errors with exponential backoff, `Retry-After`, per-host pacing, response size
  limits and an allowlist check on every redirect hop.
  - `GuardedHttpClient` (in `afid.pipeline.urlpolicy`) adds the URL policy, a request
    budget and a run deadline, and refuses `download()`.
- **GitLab and dumps:** `afid.providers.gitlab.GitLabClient` and the dump-branch conventions
  of `afid.providers.dumps`.
- **Utilities:** `afid.utils.jsonio` for deterministic JSON, `afid.utils.log` for structured
  logs, and `afid.hashing` for stable ids and SHA-256.
- **Cross-check:** `config/provider_registry.yml`. Each registry entry names its
  `afid_provider`, and validation fails if their hosts, API base or group differ.

## Running it locally

```bash
python3 tools/validate.py all                       # schemas, registry, fixture
python3 tools/ingest.py --mode dry-run              # offline; writes build/pipeline/manifest.json
python3 tools/validate.py manifest build/pipeline/manifest.json
python3 tools/publish_manifest.py build/pipeline/manifest.json   # prints "disabled"
PYTHONPATH=src python3 -m unittest discover -s tests/pipeline -t .
```

Requirements: Python 3.11 or later, plus `jsonschema` and `PyYAML` (already AFID
dependencies). Install them with
`pip install --require-hashes --no-deps -r requirements-runtime.lock`, or use the dev venv
from `scripts/setup_environment.sh`.

### Modes

| Mode | Network | Sources | Output |
|---|---|---|---|
| `--mode dry-run` | none | the synthetic fixture. Sources named with `--source` are reported as `planned`, with their effective limits, and nothing is requested | records from the fixture |
| `--mode discover` | HTTPS GET to the source's allowlisted hosts only | only the sources named with `--source`, each **enabled** in the registry | records from the source |

Run-level rules:
- **Limits:** command-line limits (`--max-pages`, `--max-records`, `--max-requests`,
  `--timeout`, `--max-run-seconds`) can only lower the registry's limits, never raise them.
  - Test: `test_cli_limits_only_lower_registry_limits`.
- **Output path:** the manifest must be a `.json` file inside `build/`, even after symlinks
  are resolved. It can never overwrite `registry/`, `schemas/` or `database/`.
  - Test: `test_safe_output_paths`.
- **Timestamp:** `--generated-at`, otherwise `SOURCE_DATE_EPOCH`, otherwise the current time.
  - Records and keys are sorted, so the same input gives a byte-identical file.
  - Test: `test_dry_run_is_offline_and_deterministic`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success; the manifest was written |
| 2 | configuration problem: invalid registry, schema or arguments |
| 3 | validation failure: rejected records, or an invalid manifest |
| 7 | every selected source failed. The manifest is still written |
| 9 | policy refusal, raised before any request: a disabled source, a URL outside the policy, or an unsafe output path |
| 13 | the run-time budget ran out. The manifest is written with status `partial` |
| 14 | partial: some requests failed, and the records that were found are kept |

## Source registry

Each provider in `registry/sources.json` records:
- **Identity and access:** a stable `id`, `display_name`, `provider_type`, `base_url`,
  `allowed_hosts`, and the discovery strategy with its endpoints.
- **Fields:** `supported_fields`, each labelled `source` or `inferred`.
- **Limits:** request timeout, minimum interval between requests, retries, backoff, pages,
  records, requests, response bytes and run seconds.
- **Evidence:** rate-limit and robots findings, each with its date and URL.
- **Review:** access mechanism, legal terms, endpoint stability, resource consumption, and
  reviewer and date.
- **Licensing:** attribution and licence notes.
- **Capabilities:** confirmed, kept separate from assumed.
- **Other:** `last_successful_discovery` and the provider's limitations.

`tools/validate.py all` enforces rules that the schema alone cannot express:
- `test_enabling_requires_an_approved_review`: `enabled: true` needs a review with status
  `approved`, a reviewer, a review date, a recorded rate-limit check and a recorded robots
  check.
- `test_tool_cannot_be_enabled`: tools such as DumprX have the strategy `none` and can never
  be enabled.
- `test_registry_must_agree_with_provider_registry`: hosts, API base and group must match
  `config/provider_registry.yml`.
- `test_registry_rejects_unsafe_urls_and_hosts`: every URL must pass the URL policy, and
  every host must be a plain DNS name.

`last_successful_discovery` changes only through a reviewed pull request; each run reports
its own time in the manifest. All providers start disabled
(`test_every_registry_provider_is_disabled_by_default`).

### Provider status (checked 2026-10-20)

| Provider | Confirmed | Assumed or unknown |
|---|---|---|
| `android_dumps_gitlab` | Unauthenticated GitLab REST v4 group listing and branch listing. Branch names are Android build descriptions. GitLab.com documents per-IP limits of 500 unauthenticated requests per minute and 600 per minute for group projects | Namespace = manufacturer and project = codename are hints. A proposed limit of 60 unauthenticated requests per hour is not yet in effect. Terms of use not reviewed. robots.txt disallows `/api/v*` for `User-Agent: *`: needs a decision |
| `tadiphone_dumps` | Same API and layout. Some repositories answer HTTP 404 | No published rate limit and no rate-limit headers. Capacity unknown. No terms found. robots.txt is the same stock GitLab template, including `Disallow: /api/v*` |
| `dumprx` | A GPL-3.0 extraction tool, run offline at pinned commit `303f5bba` in `afid-firmware-worker` | Real vendor firmware has not been tested. Not a metadata source: never contacted, never run by this pipeline |

Neither dump source offers downloadable packages or checksums. Their records keep
`file_name`, `file_size_bytes`, `sha256` and `download_url` null.

## Firmware record

Defined by `schemas/firmware-record.schema.json`:
- **Identity:** `record_id = stable_id("fwr", "firmware-record/1", source_id,
  source_item_id)`. It never depends on time
  (`test_record_ids_are_deterministic_and_time_independent`).
- **Provenance:** every data field has an entry with an origin and a method:
  - `source`: the source states the value;
  - `inferred`: derived by a documented rule, such as a namespace or a parsed branch name
    (`test_inferred_values_are_labelled_inferred`);
  - `computed`: measured by AFID; allowed only for checksums and sizes;
  - `unknown`: the value is null (`test_missing_fields_are_null_with_unknown_provenance`).
- **`validation_status`:**
  - `unverified`: the schema, URL policy and provenance checks passed, and nothing was
    compared with the firmware itself;
  - `checksum_verified`: only after a local file's SHA-256 matched
    (`tools/validate.py checksum ...`, `test_checksum_verification_matches_and_mismatches`).
  - A record can never claim verification it did not get
    (`test_unverified_records_cannot_claim_checksum_verification`).
- **Rejected records:** any record that fails a check appears under `rejected`, with the
  reason, and is counted as `failed`.
- **Duplicates:** a repeated `record_id` is counted as `duplicate` and appears only once.

Branch-name parsing (`<product>-<type>-<release>-<build id>-<incremental>-<tags>`) is
verified against real dump branch names (`test_build_description_parsing`). A name that does
not parse leaves the version fields null rather than guessed.

## In CodeBuild

`buildspec.yml` runs these steps, in order:
1. Install the hash-locked runtime dependencies (`--require-hashes`).
2. Run `compileall`.
3. Run `tools/validate.py all`.
4. Run the offline `tests/pipeline` suite.
5. Run the synthetic dry-run and validate its manifest.
6. Run `tools/publish_manifest.py`, the last command of the build phase. It uploads only if
   `ENABLE_S3_PUBLISH` is exactly `true`.

When publishing is enabled:
- One `aws s3api put-object` call uploads
  `s3://<bucket>/<prefix>runs/<build id>/manifest.json`, with `--expected-bucket-owner` and
  a SHA-256 checksum, using the service role's temporary credentials
  (`test_publish_command_is_a_single_put_object`).
- `post_build` prints a short summary with counts only, no records
  (`test_summary_has_no_record_contents`).
- `discover` mode is not run in CodeBuild in this phase
  (`test_buildspec_is_metadata_only_and_publish_is_off`).

## Future: publishing metadata back to GitHub (not implemented)

Writing validated metadata back to the repository is out of scope for this phase. When it
is requested, the design should:
- **Write location:** write to a dedicated branch, for example `afid/pipeline-metadata`,
  and a dedicated path, for example `database/pipeline/<source>/<shard>.json`. Then open a
  pull request; never push to `dev`.
- **Authentication:** use a GitHub App installation token scoped to this one repository
  with `contents:write` and `pull_requests:write`.
  - Mint the token at run time from a private key kept in AWS Secrets Manager.
  - The key is never placed in the repository, the buildspec or the logs.
- **No-op runs:** write files through `jsonio.write_if_changed`, so unchanged metadata
  produces no diff, and skip the commit entirely when nothing changed.
- **Loop prevention:** a CodeBuild webhook, if one is ever added, filters on `dev` pushes
  and excludes the metadata branch and path (`FILE_PATH` and `HEAD_REF` filters). Commits
  made by the App are also excluded with an `ACTOR_ACCOUNT_ID` filter.
- **Payloads:** never commit firmware or any binary. `afid security scan` and
  `.gitignore` already block payload types.
