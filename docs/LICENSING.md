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

## Third-party metadata

Community metadata (LineageOS wiki) is recorded as facts with source URL and revision. Its
content license was not found in the source repository; review before committing it in bulk.
