# Security design

## Threat model

Firmware archives and their contents are attacker-controlled input. Threats: path traversal
and symlink escape, decompression bombs, malformed binaries crashing parsers, XML entity
expansion, code execution via firmware scripts, shell injection via file names, secret
leakage, and accidental publication of restricted payloads. Community dump repositories and
DumprX add: files fetched from third-party hosts, a tool that can publish what it unpacks,
and per-item CI jobs handling untrusted data.

## Controls

| Threat | Control | Test |
|---|---|---|
| Traversal / absolute paths | `utils/paths.safe_join`, normalization before extraction | `test_zip_path_traversal_rejected`, `test_unsafe_member_names` |
| Escaping symlinks/hardlinks | rejected in ZIP/TAR; scanner records links, never follows | `test_tar_symlink_escape_and_traversal_rejected`, `test_symlinks_recorded_not_followed` |
| Device files | skipped | `test_tar_device_files_skipped` |
| Bombs | member count and written-bytes limits | `test_zip_bomb_limits` |
| Malformed ELF/XML/JSON | bounded parsers, errors recorded per component | `test_elf_malformed_rejected`, `test_vintf_parse_and_dtd_rejected` |
| Code execution | nothing from firmware is executed; tools get argument lists, no shell | code review: `extraction/tools.py` |
| Network misuse | HTTPS only, per-provider host allowlist, retries bounded | `test_http_only_https_and_allowed_hosts` |
| Token leakage | tokens only from env, redacted from errors | `test_http_gives_up_and_redacts_token` |
| Payload publication | default `unknown`; allowlist by SHA-256; JSON-only `database/` | `test_policy_unknown_blocks_publishing`, `test_validator_catches_broken_references` |
| Secrets/payloads in Git | `afid security scan` | `tests/security/test_audit.py` |
| CI supply chain | actions pinned to SHAs, read-only default token, no `pull_request_target`, hash-pinned dependencies, `pip-audit`, Trivy filesystem scan, SBOM | `test_workflows_are_valid_and_least_privilege`, `security-audit.yml` |
| Redirect to another host | every redirect hop re-checked against the provider's allowed hosts; `Authorization` dropped on cross-host redirects | `afid.download._RedirectGuard` |
| Remote dump content | fetched files written through `safe_join` into a private work dir, pinned to a commit, size-limited per file and per item, parsed only; LFS pointers never resolved | `test_remote_analysis_catalogs_verified_device`, `test_fetch_budget_keeps_build_prop_first` |
| Truncated or empty source listing | below `min_projects` = failed check; snapshot untouched, nothing marked removed | `test_truncated_listing_is_a_failure_and_keeps_snapshot` |
| DumprX publishing dumps | AFID never creates credential files and refuses to run when one exists; no `git`/`curl`/`wget`/`sudo` in the worker; `--network none` | `test_dumprx_refuses_credential_files`, `test_worker_image_cannot_download_or_publish` |
| DumprX downloading or self-updating | local file input only; pinned commit and `dumper.sh` hash; offline check | `test_dumprx_refuses_wrong_revision_url_network_and_missing` |
| Token leakage into DumprX | environment emptied before DumprX starts | `test_dumprx_runs_with_clean_environment` |
| Container escape / privilege | non-root uid 10001, `--cap-drop ALL`, `no-new-privileges`, read-only root, no Docker socket, digest-pinned bases | `test_dockerfile_hardening`, `container-images.yml` smoke test |
| Untrusted job output | matrix jobs write delta artifacts only; reconcile re-validates every record and places it by content | `test_reconcile_rejects_tampered_or_foreign_deltas` |
| Secrets in firmware jobs | analysis and dump jobs have read-only tokens and reference no secrets | `test_firmware_jobs_never_see_secrets_or_write_tokens` |

## Personal data

AFID does not store serial numbers, IMEIs, account data or user files. `build.prop` parsing
keeps an allowlist of build properties only.

## AWS CodeBuild metadata pipeline

Scope: `registry/`, `src/afid/pipeline/`, `tools/`, `buildspec.yml` and
`infra/cloudformation/codebuild.yml` ([AWS_PIPELINE.md](AWS_PIPELINE.md)).

### Trust boundaries

- **Repository:** the registry, schemas and code are trusted, but only after review. A
  source becomes reachable only through a reviewed registry change that records an approved
  review.
- **Source responses:** JSON from GitLab APIs is untrusted.
  - It is parsed with size limits (`max_response_bytes`).
  - Every field is shape-checked; malformed entries are rejected and counted, never
    crashing the run or guessed.
  - URLs found in responses are only *recorded*, after the URL policy. They are never
    followed.
- **CodeBuild:** builds run in an AWS-managed container with the service role's temporary
  credentials. The dry-run makes no source requests. Only PyPI, for the hash-locked install,
  and S3, when publishing, are contacted.
- **S3 staging bucket:** owned by the operator and pre-existing. The role can only create
  objects under `<prefix>runs/`, in a bucket owned by this account.

### Controls

| Threat | Control | Test |
|---|---|---|
| SSRF, or requests to unexpected hosts | `check_url` rejects non-HTTPS URLs, credentials in URLs, non-default ports, IP literals and hosts not on the source's allowlist. When resolving, any non-public address (private, loopback, link-local, carrier-grade NAT, multicast, reserved) is refused | `test_rejects_unsafe_schemes_and_hosts`, `test_rejects_hosts_resolving_to_private_addresses` |
| Redirect to another host or to metadata endpoints | the same policy runs on every redirect hop | `test_redirects_outside_allowlist_are_refused` |
| Accidental firmware download | `GuardedHttpClient.download` always refuses; only GET; listing endpoints only; `binary_downloads` is `0` by schema | `test_no_binary_downloads_in_initial_mode`, `test_client_never_downloads_and_only_sends_get` |
| Unreviewed or disabled sources | `discover` needs an explicit `--source` that is enabled; enabling needs an approved review; tools can never be enabled | `test_discover_refuses_disabled_sources`, `test_enabling_requires_an_approved_review`, `test_tool_cannot_be_enabled` |
| Abusive load on a source | per-source pacing, `max_requests`, `max_pages`, `max_records`, `max_run_seconds`; retries only on 429, 5xx and network errors, bounded with exponential backoff and `Retry-After` | `test_request_budget_truncates_without_failing`, `test_rate_limit_is_retried_with_retry_after`, `test_persistent_server_errors_are_bounded`, `test_client_errors_are_not_retried`, `test_timeout_budget_stops_the_run` |
| Overwriting repository files | the output must be a `.json` file inside `build/`, after symlinks are resolved | `test_safe_output_paths` |
| Unverified data presented as verified | provenance is required for every field; `checksum_verified` only after a local SHA-256 match; deterministic ids | `test_unverified_records_cannot_claim_checksum_verification`, `test_provenance_must_match_values` |
| Uploading somewhere unexpected | publishing needs `ENABLE_S3_PUBLISH` to be exactly `true`, a valid bucket and prefix, `--expected-bucket-owner`, and one `put-object` call; IAM `s3:PutObject` is limited to `<bucket>/<prefix>runs/*` with `s3:ResourceAccount` | `test_publish_is_disabled_by_default`, `test_publish_requires_bucket_owner_and_valid_prefix`, `test_cloudformation_least_privilege` |
| Over-privileged role | no wildcard actions or resources, no managed policies, no `s3:ListBucket`, no GitHub write access (`ReportBuildStatus: false`); trust limited by `aws:SourceAccount` and `aws:SourceArn` (confused deputy) | `test_cloudformation_least_privilege`, `test_project_has_no_webhook_and_no_privileged_mode` |
| Recursive or automatic builds | no webhook, schedule or trigger; nothing is pushed back to GitHub | `test_project_has_no_webhook_and_no_privileged_mode` |
| Secrets in logs | no credentials are read, configured or printed; logs carry counts and source ids, not records | `test_logs_do_not_contain_records_or_credentials`, `test_summary_has_no_record_contents` |
| Dependency tampering | `pip install --require-hashes --no-deps -r requirements-runtime.lock` | `test_buildspec_is_metadata_only_and_publish_is_off` |

### Residual risks

- **DNS rebinding:** the resolver check and urllib's connection resolve separately. A
  hostile DNS answer could differ between the two. The allowlist limits this to the
  allowlisted names.
- **robots.txt:** both dump hosts serve GitLab's stock robots.txt, which disallows
  `/api/v*` for all user agents. The sources stay disabled until a human decides whether
  bounded API listing is acceptable (see the registry's `robots.finding`).

### Incident handling

- **Credentials:** if credentials or tokens ever appear in a log, an artifact or the
  repository, revoke them first: rotate or delete the IAM session or key, or delete the
  CodeConnections connection. Then delete the log streams and the S3 object, and only then
  investigate.
- **Unexpected S3 objects or charges:**
  1. Stop running builds (`aws codebuild stop-build`).
  2. Delete the stack if needed ([AWS_SETUP.md](AWS_SETUP.md), step 11).
  3. Review the CloudTrail events for the role `<project>-codebuild`.
- **A source complaint, or abuse:** set the provider to `enabled: false` in a pull request
  and contact the host's operator.
