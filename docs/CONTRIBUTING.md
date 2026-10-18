# Contributing

## Setup (Linux / Ubuntu)

```bash
scripts/setup_environment.sh          # .venv with hash-pinned dependencies
source .venv/bin/activate
sudo scripts/install_dependencies.sh  # optional: tools for image formats
afid doctor
```

## Checks (same as CI)

```bash
ruff check src tests scripts && ruff format --check src tests scripts
mypy
python -m pytest -q
afid database validate --check-index
afid providers test && afid policy check && afid security scan
actionlint   # workflow lint (installed via requirements.lock)
```

Updating dependencies: edit `pyproject.toml`, then
`uv pip compile pyproject.toml --extra dev --universal --python-version 3.11 --generate-hashes -o requirements.lock`.

## Adding a device

Ingest firmware that contains its identity (`afid ingest --local ...`). A device directory is
created only from firmware or official evidence. Community information can be proposed with
`.github/ISSUE_TEMPLATE/add_device.yml`; it lands in staging until verified. Never rename or
merge device directories by hand: open a pull request that explains the evidence, and let
`afid database validate` confirm references stay intact.

## Adding a provider or classifier

See `docs/PROVIDERS.md` and `docs/COMPONENT_CLASSIFICATION.md`.

## Commits and pull requests

- Work on a topic branch; open a pull request against `dev`. Do not push to the default branch.
- Commits must be cryptographically signed (SSH or GPG) and end with the project's trailer:
  `Signed-off-by: FebriCahyaa <febricahya12345@gmail.com>` (see the organization standard
  `agent-foundation/standards/git-and-commit-signing.md` in `ZairenkaiPrjctX/.github`).
- Never commit firmware, vendor binaries, tokens, serial numbers or IMEIs.
