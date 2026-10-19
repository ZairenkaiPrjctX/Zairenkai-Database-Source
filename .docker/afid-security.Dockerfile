# syntax=docker/dockerfile:1
# afid-security: Trivy, Syft and Hadolint (copied from their digest-pinned upstream images),
# shellcheck, actionlint and pip-audit. Scans the mounted checkout and built images.
ARG PYTHON_BASE=docker.io/library/python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ARG TRIVY_IMAGE=ghcr.io/aquasecurity/trivy:0.67.0@sha256:94711c60051c6cab848a292e3a67f62623fcee361b2bb661f43b17184f4afdac
ARG SYFT_IMAGE=ghcr.io/anchore/syft:v1.33.0@sha256:f94e5d9fce1f2278491a8e3a63bd5f6ddb81fdfdbb8bf7a1637565c1d5344357
ARG HADOLINT_IMAGE=docker.io/hadolint/hadolint:v2.14.0@sha256:27086352fd5e1907ea2b934eb1023f217c5ae087992eb59fde121dce9c9ff21e
FROM ${TRIVY_IMAGE} AS trivy
FROM ${SYFT_IMAGE} AS syft
FROM ${HADOLINT_IMAGE} AS hadolint
FROM ${PYTHON_BASE}
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.title="afid-security" \
      org.opencontainers.image.description="AFID security tooling: trivy, syft, hadolint, shellcheck, actionlint, pip-audit"
SHELL ["/bin/sh", "-eu", "-c"]
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=syft /syft /usr/local/bin/syft
COPY --from=hadolint /bin/hadolint /usr/local/bin/hadolint
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh -c 'apt-get update -qq \
      && apt-get install -y --no-install-recommends shellcheck \
      && rm -rf /var/lib/apt/lists/*'
COPY requirements.lock /opt/afid/requirements.lock
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh python3 -m pip install --no-cache-dir \
      --disable-pip-version-check --require-hashes --no-deps -r /opt/afid/requirements.lock
COPY requirements-runtime.lock /opt/afid/requirements-runtime.lock
COPY src /opt/afid/src
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh /afid-build/install-afid.sh
USER afid
WORKDIR /workspace
CMD ["sh", "-c", "trivy --version && syft version && hadolint --version && shellcheck --version"]
