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
