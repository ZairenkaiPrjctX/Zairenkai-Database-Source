#!/bin/sh
# Install AFID's runtime dependencies from the hash-pinned lockfile and make the AFID source
# importable without a build backend. Used by every AFID image.
#   AFID_SRC  where the source is imported from: /opt/afid/src (copied into the image,
#             default) or /workspace/src (afid-validation tests the mounted checkout).
set -eu
AFID_SRC="${AFID_SRC:-/opt/afid/src}"
python3 -m pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps \
    -r /opt/afid/requirements-runtime.lock
python3 -m pip check
site=$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
echo "$AFID_SRC" > "$site/afid.pth"
cat > /usr/local/bin/afid <<'SH'
#!/bin/sh
exec python3 -I -m afid.cli "$@"
SH
chmod 0755 /usr/local/bin/afid
groupadd --system --gid 10001 afid
useradd --system --uid 10001 --gid afid --home-dir /home/afid --create-home --shell /usr/sbin/nologin afid
if [ -d "$AFID_SRC" ]; then afid version; fi
# pip (and its vendored urllib3/msgpack/pkg_resources) is only needed to install; images
# carry no package installer at run time.
python3 -m pip uninstall -y -q pip
rm -rf "$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')/ensurepip"
