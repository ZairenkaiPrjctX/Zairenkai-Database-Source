# Security policy

## Reporting a vulnerability
Report privately to the repository maintainers (GitHub: Security -> Report a vulnerability,
or contact the ZairenkaiPrjctX organization owners). Do not open public issues for security
problems and do not attach firmware or credentials.

## Scope
AFID processes untrusted firmware. In scope: path traversal or symlink escape during
extraction, decompression bombs, XML entity attacks, code execution from firmware content,
secret leakage in logs or artifacts, and publication of payloads the policy should block.

## Design guarantees (tested in tests/extraction and tests/security)
- Firmware content is never executed; external tools receive argument lists, never shells.
- ZIP/TAR members cannot escape the extraction root; device files are skipped.
- Size and member-count limits are enforced on bytes actually written.
- XML with DOCTYPE/ENTITY declarations is rejected before parsing.
- Only allowlisted (by SHA-256) payloads are publishable; `unknown` is the default.
- Workflows use read-only tokens except PR-proposing jobs, pin actions to commit SHAs and
  never use `pull_request_target`.

See docs/SECURITY.md for details.
