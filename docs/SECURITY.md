# Security design

## Threat model

Firmware archives and their contents are attacker-controlled input. Threats: path traversal
and symlink escape, decompression bombs, malformed binaries crashing parsers, XML entity
expansion, code execution via firmware scripts, shell injection via file names, secret
leakage, and accidental publication of restricted payloads.

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
| CI supply chain | actions pinned to SHAs, read-only default token, no `pull_request_target`, hash-pinned dependencies, `pip-audit` | `test_workflows_are_valid_and_least_privilege`, `security-audit.yml` |

## Personal data

AFID does not store serial numbers, IMEIs, account data or user files. `build.prop` parsing
keeps an allowlist of build properties only.
