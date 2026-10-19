# Docker architecture

Five images, each with one job, defined in [`.docker/`](../.docker/README.md). They all
start from `python:3.13-slim-trixie` pinned by digest
(`sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`, Debian 13.7),
install AFID's runtime dependencies from the hash-pinned `requirements-runtime.lock`, drop
pip, and run as the non-root user `afid` (uid/gid 10001).

| Image | Purpose | Network at run time | Extra contents |
|---|---|---|---|
| `afid-validation` | repository checks: pytest, ruff, mypy, check-jsonschema, actionlint, shellcheck | none | full `requirements.lock` (dev), `shellcheck`, `git`, `binutils`, `e2fsprogs`; **no AFID source**: it imports the checkout mounted at `/workspace` |
| `afid-discovery` | provider discovery (`afid discover`, `afid updates check`) | HTTPS to the provider's `allowed_hosts` only | `git` (LineageOS wiki sparse clone) |
| `afid-catalog` | `afid catalog reconcile`, `catalog validate`, `database index` | none | nothing |
| `afid-firmware-worker` | `afid firmware dump` (pinned DumprX) and local ingestion | **none** (`--network none`) | Debian main extraction tools, pinned DumprX + android_tools + extract-ikconfig; no `git`, `curl`, `wget`, `sudo`, `uv`, `rar` |
| `afid-security` | Trivy, Syft, Hadolint, shellcheck, actionlint, pip-audit | DB updates only | binaries copied from digest-pinned upstream images |

## Rules every image follows

- Base and tool images are referenced **by digest**; a mirror may be used for the same
  digest (`--build-arg PYTHON_BASE=mirror.gcr.io/library/python@sha256:...`), never a
  different one (`test_dockerfile_hardening`).
- Python packages come only from hash-pinned lockfiles (`pip --require-hashes --no-deps`).
- No secret, token or credential is baked in or passed as a build argument. A
  TLS-intercepting proxy's CA (only some build environments have one) is a BuildKit
  **secret** used by [`with-build-ca.sh`](../.docker/scripts/with-build-ca.sh) for one
  `RUN` step and removed before that layer is committed.
- No image mounts or needs the Docker socket; the firmware worker never gets credentials
  (`test_worker_image_cannot_download_or_publish`).
- Images (except `afid-validation`) contain AFID's code but not its configuration or catalog: the checkout is mounted
  at `/workspace` and passed with `--root /workspace`, so the code in the image and the data
  it works on are reviewed separately.

## Firmware worker isolation

```
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --read-only --tmpfs /tmp --user 10001:10001 \
  -v "$PWD:/workspace" -v /path/to/work:/work \
  afid-firmware-worker:<tag> --root /workspace firmware dump --input /work/in/<file> \
  --workdir /work/job --ingest
```

- `--network none`: DumprX cannot download or publish, and the runner refuses to start if
  it can reach the network.
- Read-only root filesystem; writable paths are `/tmp` (tmpfs), `/work` (firmware and
  extraction, deleted after the job) and `/workspace/database` (metadata only).
- The firmware file and extracted files never leave the job: workflows upload only the
  `database/` diff (`dump-and-analyze.yml`).

## Dump analysis does not use the worker

Community dump items (Android-Dumps, tadiphone) are analyzed by fetching individual files,
not by unpacking firmware, so `analyze-components.yml` runs on the standard runner with
`setup-afid` and needs no container. The worker is only for firmware files run through
DumprX.
