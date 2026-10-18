#!/usr/bin/env bash
# Everything CI checks about the data: schemas, references, codenames, generated files, policy.
set -euo pipefail
cd "$(dirname "$0")/.."
afid database validate --check-index "$@"
afid providers test
afid policy check
afid security scan
