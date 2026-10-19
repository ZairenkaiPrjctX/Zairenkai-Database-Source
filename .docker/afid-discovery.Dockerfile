# syntax=docker/dockerfile:1
# afid-discovery: provider discovery jobs (network: HTTPS to the provider hosts only).
# Build: see .docker/README.md. The base image is pinned by digest; override PYTHON_BASE only
# with the same digest from a mirror (e.g. mirror.gcr.io/library/python@sha256:...).
ARG PYTHON_BASE=docker.io/library/python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
FROM ${PYTHON_BASE}
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0"
SHELL ["/bin/sh", "-eu", "-c"]
LABEL org.opencontainers.image.title="afid-discovery" \
      org.opencontainers.image.description="AFID discovery: lists provider sources, writes snapshots; no firmware payloads"
# git: the lineageos_wiki provider reads a shallow sparse clone of a public repository.
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh -c 'apt-get update -qq \
      && apt-get install -y --no-install-recommends git \
      && rm -rf /var/lib/apt/lists/*'
COPY requirements-runtime.lock /opt/afid/requirements-runtime.lock
COPY src /opt/afid/src
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh /afid-build/install-afid.sh
USER afid
WORKDIR /workspace
ENTRYPOINT ["afid"]
CMD ["--help"]
