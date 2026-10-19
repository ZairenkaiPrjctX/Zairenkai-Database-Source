# syntax=docker/dockerfile:1
# afid-firmware-worker: unpacks ONE local firmware file with a pinned DumprX checkout and
# catalogs the extracted tree. Run it only like this (see .docker/README.md):
#   docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
#     --read-only --tmpfs /tmp -v "$PWD:/workspace" -v /path/to/work:/work afid-firmware-worker ...
# No credentials, tokens or Docker socket are ever given to this container.
#
# NOT auto-published: DumprX (GPL-3.0-only) ships prebuilt third-party binaries in utils/
# whose licences have not been reviewed; see docs/DUMPRX_INTEGRATION.md.
ARG PYTHON_BASE=docker.io/library/python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

# ---- fetch pinned third-party code (network only in this stage) ---------------------------
FROM ${PYTHON_BASE} AS fetch
SHELL ["/bin/sh", "-eu", "-c"]
ARG DUMPRX_COMMIT=303f5bba1f583c2c857a5e11d46812361a1d4625
ARG DUMPER_SHA256=297f37d63415dc4273f4d168455451e4a08dac57016dd547a2c0516ad971f0b3
# ShivamKumarJha/android_tools (GPL-3.0): the only DumprX runtime helper with a licence.
ARG ANDROID_TOOLS_COMMIT=ca04143bb9233ea8696f74cfe73949a123e5bb66
# scripts/extract-ikconfig (GPL-2.0) from torvalds/linux tag v6.12.
ARG LINUX_COMMIT=adc218676eef25575469234709c2d87185ca223a
ARG IKCONFIG_SHA256=070020a9c5a0b9e6f7e24f5728073e8e62155be49133a9f3f37e8fc19230a9b1
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh -eu -c ' \
      apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates; \
      git init -q /opt/dumprx && cd /opt/dumprx; \
      git fetch -q --depth 1 https://github.com/DumprX/DumprX "$DUMPRX_COMMIT"; \
      git checkout -q FETCH_HEAD; test "$(git rev-parse HEAD)" = "$DUMPRX_COMMIT"; \
      echo "$DUMPER_SHA256  dumper.sh" | sha256sum -c -; \
      git init -q utils/android_tools && cd utils/android_tools; \
      git fetch -q --depth 1 https://github.com/ShivamKumarJha/android_tools "$ANDROID_TOOLS_COMMIT"; \
      git checkout -q FETCH_HEAD; test "$(git rev-parse HEAD)" = "$ANDROID_TOOLS_COMMIT"; \
      cd /opt/dumprx; \
      curl -sSfL -o utils/extract-ikconfig \
        "https://raw.githubusercontent.com/torvalds/linux/$LINUX_COMMIT/scripts/extract-ikconfig"; \
      echo "$IKCONFIG_SHA256  utils/extract-ikconfig" | sha256sum -c -; chmod 0755 utils/extract-ikconfig; \
      rm -rf .git utils/android_tools/.git; \
      rm -rf utils/downloaders utils/bin/transfer; \
      echo "$DUMPRX_COMMIT" > .afid-dumprx-commit'

# ---- runtime ------------------------------------------------------------------------------
FROM ${PYTHON_BASE}
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0 AND GPL-3.0-only" \
      org.opencontainers.image.title="afid-firmware-worker" \
      org.opencontainers.image.description="AFID firmware worker: pinned DumprX, offline unpacking, metadata-only output"
SHELL ["/bin/sh", "-eu", "-c"]
# Debian trixie main only (no contrib/non-free: no rar/unrar). Deliberately absent: git,
# curl, wget, sudo and uv - DumprX uses them only to download, self-update or publish.
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh -c 'apt-get update -qq \
      && apt-get install -y --no-install-recommends \
         file binutils e2fsprogs erofs-utils 7zip unzip xz-utils zstd lz4 cpio brotli \
         android-sdk-libsparse-utils device-tree-compiler jq gawk detox unace f2fs-tools \
      && rm -rf /var/lib/apt/lists/* \
      && ln -s /usr/bin/7z /usr/local/bin/7zz'
# (Debian's 7zip ships upstream 7-Zip as `7z`; the `7zz` name makes DumprX use it instead
# of the prebuilt utils/bin/7zz.)
COPY --from=fetch /opt/dumprx /opt/dumprx
COPY requirements-runtime.lock /opt/afid/requirements-runtime.lock
COPY src /opt/afid/src
RUN --mount=type=secret,id=proxy_ca,required=false \
    --mount=type=bind,source=.docker/scripts,target=/afid-build \
    sh /afid-build/with-build-ca.sh sh /afid-build/install-afid.sh \
    && chmod -R a-w /opt/dumprx \
    && mkdir -p /work && chown afid:afid /work
ENV AFID_DUMPRX_DIR=/opt/dumprx \
    TMPDIR=/work/tmp
USER afid
WORKDIR /workspace
ENTRYPOINT ["afid"]
CMD ["providers", "health", "--provider", "dumprx"]
