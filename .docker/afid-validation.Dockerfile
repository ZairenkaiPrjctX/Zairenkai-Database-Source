# syntax=docker/dockerfile:1
# afid-validation: the repository's own checks (pytest, ruff, mypy, actionlint, shellcheck).
# Build: see .docker/README.md. The base image is pinned by digest; override PYTHON_BASE only
# with the same digest from a mirror (e.g. mirror.gcr.io/library/python@sha256:...).
ARG PYTHON_BASE=docker.io/library/python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
FROM ${PYTHON_BASE}
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0"
SHELL ["/bin/sh", "-eu", "-c"]
LABEL org.opencontainers.image.title="afid-validation" \
      org.opencontainers.image.description="AFID validation toolchain; run against a mounted checkout"
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh -c 'apt-get update -qq \
      && apt-get install -y --no-install-recommends shellcheck git binutils e2fsprogs \
      && rm -rf /var/lib/apt/lists/*'
COPY requirements.lock /opt/afid/requirements.lock
# Full development lock (hash-pinned): pytest, ruff, mypy, check-jsonschema, actionlint-py.
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh python3 -m pip install --no-cache-dir \
      --disable-pip-version-check --require-hashes --no-deps -r /opt/afid/requirements.lock
# No AFID source in this image: it imports the checkout mounted at /workspace, so it always
# tests the code under review, never a copy baked in at build time.
COPY requirements-runtime.lock /opt/afid/requirements-runtime.lock
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    AFID_SRC=/workspace/src sh /afid-build/with-build-ca.sh sh /afid-build/install-afid.sh
USER afid
WORKDIR /workspace
CMD ["sh", "-c", "python3 -m pytest -q && ruff check src tests scripts && mypy"]
