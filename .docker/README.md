# AFID container images

| File | Image | Role |
|---|---|---|
| `afid-validation.Dockerfile` | `afid-validation` | pytest, ruff, mypy, actionlint, shellcheck against a mounted checkout |
| `afid-discovery.Dockerfile` | `afid-discovery` | provider discovery (network: provider hosts only) |
| `afid-catalog.Dockerfile` | `afid-catalog` | reconcile, validate and index the catalog (no network) |
| `afid-firmware-worker.Dockerfile` | `afid-firmware-worker` | pinned DumprX + ingestion, offline only; **not published** |
| `afid-security.Dockerfile` | `afid-security` | Trivy, Syft, Hadolint, shellcheck, actionlint, pip-audit |
| `scripts/with-build-ca.sh` | build helper | trusts an optional proxy CA (BuildKit secret) for one step only |
| `scripts/install-afid.sh` | build helper | installs the runtime lockfile, the `afid` launcher and user `afid`, removes pip |

Design and isolation rules: [docs/DOCKER_ARCHITECTURE.md](../docs/DOCKER_ARCHITECTURE.md).
Naming, publishing and digests: [docs/CONTAINER_IMAGES.md](../docs/CONTAINER_IMAGES.md).

## Build

From the repository root (the build context is filtered by `.dockerignore`):

```bash
docker build -f .docker/afid-catalog.Dockerfile --build-arg VCS_REF="$(git rev-parse HEAD)" -t afid-catalog:local .
```

Behind a TLS-intercepting proxy, pass its CA as a secret and the proxy as a build arg; use a
mirror of the **same digest** if Docker Hub rate-limits you:

```bash
docker build --network host --secret id=proxy_ca,src=/path/to/proxy-ca.crt \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg PYTHON_BASE=mirror.gcr.io/library/python@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f \
  -f .docker/afid-firmware-worker.Dockerfile -t afid-firmware-worker:local .
```

## Run

```bash
docker run --rm --network none -v "$PWD:/workspace:ro" afid-catalog:local --root /workspace database validate
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp -v "$PWD:/workspace:ro" afid-firmware-worker:local --root /workspace providers health --provider dumprx
```
