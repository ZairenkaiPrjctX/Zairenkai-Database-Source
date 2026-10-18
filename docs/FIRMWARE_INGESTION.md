# Firmware ingestion

## Formats

| Format | Detection | Handling | How it was tested |
|---|---|---|---|
| ZIP (incl. OTA, factory) | `PK\x03\x04` | native, safe extraction | fixtures: valid, corrupt, truncated, traversal, bomb |
| TAR (plain, gz, bz2, xz), `.tgz`, `.tar.md5` | `ustar`, gzip/bz2/xz magic | native, safe extraction | fixtures: valid, escaping symlink, traversal, device file |
| Nested archives (e.g. Pixel `image-*.zip`) | magic | recursed up to 2 levels | fixtures |
| Android sparse image | `0xED26FF3A` | native (AOSP sparse format) | synthetic RAW/FILL/DONT_CARE round trip, corrupt chunk |
| ext4 | superblock magic at 1080 | `debugfs -R "rdump / <dir>"` | real ext4 image made with `mke2fs -d` |
| EROFS | magic at 1024 | `fsck.erofs --extract` (erofs-utils >= 1.6) | missing-tool path only |
| `super.img` (dynamic partitions) | LP geometry magic at 4096 | `lpunpack` | missing-tool path only |
| `payload.bin` (A/B full OTA) | `CrAU` | `payload-dumper-go` | missing-tool path only |
| LZ4 (Samsung images) | LZ4 frame magic | `lz4 -d` | missing-tool path only |
| Boot image | `ANDROID!` | detected, not parsed (kernel version not extracted) | - |

"Missing-tool path only" means AFID reports a precise `ToolMissingError` with an install hint
and records the partition as not extracted. Extraction with the real tool has not been run
against real firmware yet.

## Stages and safety

1. **Integrity**: archive size limit (`max_archive_bytes`), SHA-256 computed; with `--sha256`
   a mismatch aborts. The official checksum and whether it matched are recorded.
2. **Detection** by magic bytes.
3. **Unpack** into `.afid-cache/work/<sha256[:16]>/unpacked` (reused on re-runs; a completion
   marker makes interrupted runs restart cleanly). Members are normalized; absolute paths,
   `..`, escaping symlinks and hardlinks are rejected; special files skipped; member count and
   *written* bytes limited.
4. **Partition images** found by magic; only partitions in `scan.partitions` are extracted;
   the others are recorded in the layout as not extracted.
5. **Scan, classify, dependencies, policy, schema validation** (see
   `COMPONENT_CLASSIFICATION.md`).
6. **Write** device/firmware/components/dependencies only after validation succeeds.
7. **Cleanup**: the work directory is deleted unless `--keep-work`.

A failing partition does not stop the others; failures are recorded in `partitions[].note`
and `warnings`. Nothing from the firmware is executed.

## Device identity

Codename sources, in order: `ro.product.vendor.device`, `ro.product.odm.device`,
`ro.product.device`, `ro.product.product.device`, `ro.product.system.device`,
`ro.build.product` (values `generic`/`mainline` ignored), then OTA metadata `pre-device`.
`--codename` is only an expectation: if it contradicts the firmware, ingestion stops.
Brand: `--brand`, else build.prop brand mapped through `config/brands.yml` (model prefixes
separate POCO/Redmi from Xiaomi and Pixel from other Google devices).

If codename, brand or build id cannot be established, a staging candidate is written to
`database/staging/unresolved/` and the command exits with code 12.

When a device is verified, matching community candidates (same brand + codename) are merged
in as corroborating evidence and removed from staging.

## Examples

```bash
# Pixel factory image downloaded manually after accepting Google's terms
afid ingest --local ~/Downloads/<codename>-<build>-factory-<hash>.zip \
    --provider google_pixel --sha256 <sha256 from the download page>

# A directory you extracted yourself (vendor/, odm/, system/ ... inside)
afid ingest --local ./extracted --provider local_firmware --brand xiaomi --region global

# Everything except writing
afid ingest --local ./fw.zip --brand oneplus --dry-run --json
```
