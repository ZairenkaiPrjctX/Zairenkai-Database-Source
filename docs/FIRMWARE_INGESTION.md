# Firmware ingestion

AFID has three ingestion paths. All of them end in the same identity rules, scanner,
classifier, policy and schema validation.

| Path | Input | Command | Evidence type / source type | Distribution |
|---|---|---|---|---|
| Local import | a firmware archive, image or extracted tree you obtained | `afid ingest --local <path>` (`afid firmware ingest --local <path>`) | `firmware_build_prop` / `user_supplied_local_firmware` | `user_supplied` |
| DumprX | one local firmware file, unpacked by pinned DumprX offline | `afid firmware dump --input <file> --ingest` ([DUMPRX_INTEGRATION.md](DUMPRX_INTEGRATION.md)) | `firmware_build_prop` / `user_supplied_local_firmware` | `user_supplied` |
| Community dump | one dump branch on Android-Dumps or tadiphone | `afid firmware analyze --provider <id> --item <item>` ([SOURCE_INTEGRATION.md](SOURCE_INTEGRATION.md)) | `dump_build_prop` / `community_firmware_dump` | `unknown` |

`afid firmware download --url <https url> --sha256 <hex> --out <file>` fetches a firmware
file only from hosts listed in `config/settings.yml` `downloads.allowed_hosts`, which is
empty: no host has been verified to permit automated download, so the command refuses until
an owner adds one. It enforces `MAX_DOWNLOAD_BYTES`, the disk reserve, HTML-page rejection,
truncation detection and the checksum ([RESOURCE_BUDGETS.md](RESOURCE_BUDGETS.md)).

## Remote dump analysis

No firmware file is involved. The dump's file list is read, paths are mapped onto
partitions (`system/system/X` becomes `system/X`), build.prop files and every path a rule
could match are fetched one by one at the branch's commit SHA, and DT_NEEDED libraries of
fetched vendor binaries are followed within the fetch budget. Files that were listed but not
fetched still count for dependency resolution (edges say "listed by the source, content not
fetched"); Git LFS pointers are recorded in the report and never resolved. Firmware identity
includes `ro.build.version.incremental`, so firmware keys look like `<build id>-<incremental>`
when the two differ (e.g. `BP2A.250605.031.A3-2512182326`).

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
   `COMPONENT_ANALYSIS.md`).
6. **Write** device/firmware/components/dependencies only after validation succeeds.
7. **Cleanup**: the work directory is deleted unless `--keep-work`.

A failing partition does not stop the others; failures are recorded in `partitions[].note`
and `warnings`. Nothing from the firmware is executed.

## Device identity

Codename sources, in order: `ro.product.vendor.device`, `ro.product.odm.device`,
`ro.product.device`, `ro.product.product.device`, `ro.product.system.device`,
`ro.build.product` (values `generic`/`mainline` ignored), then OTA metadata `pre-device`.
`--codename` is only an expectation: if it contradicts the firmware, ingestion stops.
Brand: `--brand`, else build.prop brand mapped case-insensitively through `config/brands.yml`
aliases (model prefixes separate POCO/Redmi from Xiaomi and Pixel from other Google
devices). Android uses the last definition of a property in a file; so does AFID.

If codename, brand or build id cannot be established, a staging candidate is written to
`database/staging/unresolved/` and the command exits with code 12. A build.prop brand that
is neither a core nor an extended brand in `config/brands.yml` (e.g. `alps`, the MediaTek
reference brand) is staged the same way (`test_unknown_brand_stays_in_staging`).

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
