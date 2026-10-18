#!/usr/bin/env bash
# Create .venv and install AFID with the hash-pinned lockfile (Linux/Ubuntu, Python >= 3.11).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python >= 3.11 required")'
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install --require-hashes --no-deps -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/afid doctor || true
echo "Activate with: source .venv/bin/activate"
