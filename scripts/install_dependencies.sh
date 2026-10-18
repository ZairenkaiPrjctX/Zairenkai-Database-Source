#!/usr/bin/env bash
# Optional system tools for image extraction. AFID works without them for archives and
# extracted directories; `afid doctor` reports which formats each missing tool blocks.
# Ubuntu/Debian. Run with sudo. Nothing here is required for the test suite except git.
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends git e2fsprogs erofs-utils lz4 binutils
cat <<'MSG'
Installed: git, e2fsprogs (debugfs: ext4), erofs-utils (fsck.erofs: EROFS), lz4, binutils.
Not available from apt on all releases, install manually if you need them:
  lpunpack           super.img (dynamic partitions): AOSP system/extras/partition_tools
  payload-dumper-go  payload.bin (full OTAs): https://github.com/ssut/payload-dumper-go
MSG
