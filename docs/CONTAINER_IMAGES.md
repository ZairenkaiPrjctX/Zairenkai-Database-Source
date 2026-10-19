# Container images

## Naming

```
ghcr.io/zairenkaiprjctx/<image>:sha-<full git commit>      e.g. ghcr.io/zairenkaiprjctx/afid-catalog:sha-<40 hex>
ghcr.io/zairenkaiprjctx/<image>@sha256:<digest>            how anything consumes it
```

GHCR names are lowercase (`${GITHUB_REPOSITORY_OWNER,,}`); tags are immutable per commit and
there are no floating tags (`latest`). **No AFID image has been published yet**, so
`config/container_images.yml` records every digest as `null` and no workflow pulls an AFID
image (`test_image_lock_lists_every_image_and_nothing_unpublished_is_referenced`); workflows
that need one build it from the checked-out commit.

## Bootstrap order

1. **Build** every image from the commit (`container-images.yml`, on PRs and pushes to `dev`
   that touch images or code).
2. **Test**: non-root user, offline smoke test (`database validate`, tool versions, DumprX
   guards; the worker must not contain `git`, `curl`, `wget`, `sudo`, `uvx`).
3. **Scan** with Trivy (pinned by digest) for fixable HIGH/CRITICAL findings; publishable
   images fail the job on any finding.
4. **SBOM** with Syft (SPDX JSON, uploaded as an artifact).
5. **Publish** only when someone dispatches the workflow with `publish: true` on `dev`, and
   only the exact tarball that passed steps 2-4.
6. **Record the digest**: the run summary and an `image-digest-*` artifact list it.
7. **Reviewed lock update**: a human copies the digest into `config/container_images.yml` in
   a PR; only then may a workflow reference the image, by digest.

## Which images are publishable

| Image | Publishable | Why |
|---|---|---|
| `afid-discovery` | yes | Debian + Python layers only; scan clean |
| `afid-catalog` | yes | Debian + Python layers only; scan clean |
| `afid-validation` | no | the `actionlint` binary (from `actionlint-py`) carries Go standard-library findings AFID cannot patch |
| `afid-security` | no | bundled `trivy`, `syft` and `actionlint` binaries carry Go standard-library findings |
| `afid-firmware-worker` | no | licence review of DumprX's prebuilt `utils/bin/*` pending; `payload-dumper-go` and `f2fs-extractor` also carry Go findings |

## Local build and scan results (2026-10-19)

Built from the working tree on top of `dev` `f18bb2f` with BuildKit, base
`python:3.13-slim-trixie@sha256:70729b46...` (pulled through the `mirror.gcr.io` mirror,
same digest), scanned with Trivy 0.67.0 (`--severity HIGH,CRITICAL --ignore-unfixed`) and
inventoried with Syft 1.33.0. Image IDs are local build outputs, not published digests.

| Image | Local image ID | Size | SBOM packages | HIGH/CRITICAL (fixable) | Where |
|---|---|---|---|---|---|
| `afid-validation` | `sha256:a4d334747af4...` | 612 MB | 218 | 23 | `usr/local/bin/actionlint` |
| `afid-discovery` | `sha256:e9938cfe630f...` | 335 MB | 127 | 0 | - |
| `afid-catalog` | `sha256:f2f44a166aec...` | 194 MB | 96 | 0 | - |
| `afid-firmware-worker` | `sha256:c4b71fad5645...` | 563 MB | 196 | 88 | `payload-dumper-go` 61, `f2fs-extractor` 25, Java 2 (DumprX `utils/`) |
| `afid-security` | `sha256:499391eb2eb3...` | 813 MB | 833 | 162 | `trivy` 79, `syft` 60, `actionlint` 23 |

An earlier build showed four findings in pip's vendored `urllib3`, `msgpack` and
`pkg_resources`; images now remove pip after installing, which cleared them. Smoke tests
passed for all five images (non-root `afid`, offline); the worker's DumprX guard reported
`pinned checkout 303f5bba1f58 ready, offline`. The full test suite run inside
`afid-validation` against a mounted checkout: 242 passed, 0 skipped.

## Settings needed before publishing

- Repository/organization **Packages** must allow this repository to write to GHCR (the
  publish job uses `GITHUB_TOKEN` with `packages: write`, granted only to that job).
- Decide package visibility in GHCR (private by default for a private repository).
