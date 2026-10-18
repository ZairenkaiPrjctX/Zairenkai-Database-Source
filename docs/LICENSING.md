# Licensing and redistribution

## Layers

| Layer | Location | May contain |
|---|---|---|
| Catalog metadata | `database/` (Git) | JSON only: identities, versions, paths, checksums, classifications, dependencies, provenance |
| Redistributable data | `redistributable/` (Git) | files whose SHA-256 is in `config/redistributable_allowlist.yml` with license evidence |
| Restricted payload | never in Git | proprietary firmware and vendor files; indexed by metadata only |
| Local extraction/cache | `.afid-cache/` (gitignored) | downloads, unpacked archives, extracted trees |
| Workflow artifacts | Actions | JSON reports, patches of `database/`, test reports; never payloads |

## Statuses

`allowed`, `restricted`, `unknown` (default), `user_supplied`, `metadata_only`. Only `allowed`
is publishable. XML, JSON, `.conf`, `.rc` files are not assumed to be free: they start as
`unknown` like binaries. A private repository does not change this.

## Making a file publishable

1. Find the license or written permission that covers the exact file.
2. Add an allowlist entry: `sha256`, `path_glob`, `license`, `evidence_url`, `reviewed_by`,
   `reviewed_at` (all required; the policy refuses entries without evidence).
3. Place the file under `redistributable/` with attribution and provenance.
4. `afid policy check` must pass; a second maintainer reviews the pull request.

## Storage choice

Git stores metadata. Large binaries do not belong in Git history; Git LFS would still place
restricted payloads in the repository's storage, and GitHub Releases are public distribution.
Both are appropriate only for allowlisted files. The catalog is designed to be useful without
storing payloads: checksums plus provenance let any user verify their own copy.

## Licenses in this repository

| Content | License | Notes |
|---|---|---|
| AFID code, config, schemas, docs, `tests/fixtures/` | Apache-2.0 (`LICENSE`, `NOTICE`) | original project work; contributors certify rights via `Signed-off-by` (DCO) |
| `database/staging/unresolved/lineageos_wiki/` | CC BY-SA 3.0 | adapted third-party data; attribution + share-alike; see the README there |
| Other catalog metadata in `database/` | facts derived by AFID from user-supplied firmware | carries `distribution_status`; firmware itself is never included |
| Firmware, vendor binaries and vendor configuration | owners' proprietary terms | **not** covered by Apache-2.0 or any license here; never published by default |

Apache-2.0 grants rights only to the project's own work. It does not grant permission to
redistribute third-party firmware, proprietary libraries, or content under another license.

## Per-source license metadata

Each provider has a `data_license` block in `config/provider_registry.yml` (`spdx`, `status`,
`basis`, `evidence_urls`, `attribution`, `share_alike`); `afid providers test` rejects a
declared license without evidence or attribution. The block is copied into every staging
record, so each record states its own license.

| Source | License status | Basis |
|---|---|---|
| `lineageos_wiki` | `CC-BY-SA-3.0`, `declared_by_source` | no license file for `_data/devices/`; the repository's own footer template declares CC BY-SA 3.0 for every generated page (commit `2c365be2`, live page checked 2026-10-18) |
| all firmware providers | `unknown` | user-supplied proprietary firmware |

`declared_by_source` means the source states the license for its published content but not in a
file-level grant. AFID complies with the declared terms (attribution, share-alike) and keeps the
basis visible so a maintainer can re-check it.

## Attribution requirements

- CC BY-SA data: keep the attribution text from the record's `license.attribution`, a link to
  the license, a note that the data was adapted, and distribute adaptations under CC BY-SA 3.0.
- `afid policy check` fails if a licensed third-party record lacks attribution, if a staging
  record claims a firmware payload or verification, or if unknown-license data is publishable.
