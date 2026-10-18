#!/usr/bin/env bash
# Write the catalog report: scripts/generate_report.sh [json|markdown] [output-file]
set -euo pipefail
cd "$(dirname "$0")/.."
fmt="${1:-markdown}"
out="${2:-reports/catalog-report.${fmt/markdown/md}}"
mkdir -p "$(dirname "$out")"
afid report --format "$fmt" --output "$out"
echo "wrote $out"
