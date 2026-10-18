---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "scripts/*.py"
---
# Rule: AFID Python code

- Python >= 3.11, standard library plus PyYAML and jsonschema only. A new dependency needs a
  reason, an entry in `pyproject.toml`, and a regenerated `requirements.lock`
  (`uv pip compile pyproject.toml --extra dev --universal --python-version 3.11 --generate-hashes -o requirements.lock`).
- `mypy` runs in strict mode and `ruff` must stay clean; match the existing style.
- Firmware content is untrusted: parse with bounds checks, never execute it, pass external
  tools argument lists (never `shell=True`), and route archive paths through
  `afid.utils.paths.safe_join`.
- Records are built with `afid.models` helpers and validated against `schemas/` before writing;
  write JSON only through `afid.utils.jsonio.write_if_changed` (deterministic, no empty diffs).
- Tests must run offline. Use generated fixtures (`tests/conftest.py`) or the self-built ELF
  fixtures; never commit real firmware or vendor files.
