---
paths:
  - ".github/workflows/**"
  - ".github/actions/**"
---
# Rule: GitHub Actions in AFID

- Top-level `permissions: contents: read`; grant write only to the job that opens a pull
  request, and only `contents`, `pull-requests`, `actions`.
- Pin every third-party action to a full commit SHA with the version in a comment. Resolve
  SHAs with `git ls-remote https://github.com/<owner>/<action> refs/tags/<tag>`.
- Never use `pull_request_target`, never echo secrets, never push to the default branch or
  force-push; data changes go through `scripts/open_data_pr.py`.
- Pass `inputs.*` to scripts through `env:`, not by interpolating them into `run:`.
- Every job has `timeout-minutes`; every workflow has `concurrency`.
- After editing run `actionlint`, `check-jsonschema --builtin-schema vendor.github-workflows
  .github/workflows/*.yml`, and `python -m pytest -q tests/schemas`.
