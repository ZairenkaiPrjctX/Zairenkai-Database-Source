#!/usr/bin/env bash
# Regenerate index.json, statistics.json and the library map from the committed records.
set -euo pipefail
cd "$(dirname "$0")/.."
afid database validate
afid database index
afid dependencies build
afid database stats
