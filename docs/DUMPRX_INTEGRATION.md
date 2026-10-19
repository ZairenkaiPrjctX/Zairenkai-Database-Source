# DumprX integration

[DumprX](https://github.com/DumprX/DumprX) unpacks many firmware formats (OTA ZIPs,
`payload.bin`, sparse/`super` images, EROFS, F2FS, vendor containers) into partition
directories. AFID uses it as an **external program** for one job: turn one local firmware
file into an extracted tree, which AFID then catalogs like any other extracted directory.

## Pin

| Item | Value | Where enforced |
|---|---|---|
| DumprX commit | `303f5bba1f583c2c857a5e11d46812361a1d4625` (2026-07-30) | `config/settings.yml` `dumprx.commit`; worker image build checks `git rev-parse HEAD`; runner checks the `.afid-dumprx-commit` marker |
| `dumper.sh` SHA-256 | `297f37d63415dc4273f4d168455451e4a08dac57016dd547a2c0516ad971f0b3` | settings `dumprx.dumper_sha256`; checked at image build and before every run |
| Licence | GPL-3.0-only (repository `LICENSE`) | AFID does not link or modify it; it runs as a separate program |
| `ShivamKumarJha/android_tools` | `ca04143bb9233ea8696f74cfe73949a123e5bb66`, GPL-3.0 | baked into the image (DumprX would otherwise `git clone` it at run time) |
| `extract-ikconfig` | `torvalds/linux` `adc218676eef25575469234709c2d87185ca223a` (v6.12), SHA-256 `070020a9...30a9b1`, GPL-2.0 | baked into the image (DumprX would otherwise `curl` it from `master`) |

`test_settings_pin_matches_worker_dockerfile` keeps settings and the Dockerfile in step.

## What upstream DumprX does that AFID blocks

Read from `dumper.sh` at the pinned commit:

| DumprX behaviour | Risk | AFID control |
|---|---|---|
| Pushes the dump to GitHub/GitLab and posts to Telegram when `.github_token`, `.github_orgname`, `.gitlab_token`, `.gitlab_group`, `.gitlab_instance`, `.tg_token` or `.tg_chat` exist next to `dumper.sh` | publishing proprietary firmware | AFID never creates these files and refuses to run if any exists in the checkout or the job copy (`test_dumprx_refuses_credential_files`); `git` and `curl` are not installed in the worker |
| Accepts URLs and downloads with `wget --no-check-certificate`, mega/mediafire/gdrive/afh helpers | unverified downloads | AFID passes only a local regular file (`test_dumprx_refuses_wrong_revision_url_network_and_missing`); `utils/downloaders` and the `transfer` upload tool are removed from the image; the container has no network |
| `git clone`/`git pull` of four helper repositories at every run | unpinned code | `android_tools` is pinned in the image; the other three (`bkerler/oppo_ozip_decrypt`, `bkerler/oppo_decrypt`, `HemanthJabalpuri/pacextractor`) have **no licence** and are not included, so OPPO `.ozip`/`.ofp`/`.ops` and Spreadtrum `.pac` inputs are unsupported |
| `uvx ... git+...@master` for device-tree generation, kallsyms, dtb extraction | unpinned code at run time | `uv` is not installed and there is no network; those optional outputs are simply missing |
| `sudo mount -o loop` fallback | privilege | no `sudo`, container runs as uid 10001 with `--cap-drop ALL` and `no-new-privileges`; the fallback fails and the next extractor is tried |
| `setup.sh` installs `rar`/`unrar`/`p7zip-rar` (non-free) and runs `curl \| bash` for `uv` | non-free code, unpinned installer | `setup.sh` is never run; the worker installs Debian trixie **main** packages only |
| Writes `input/`, `out/` next to `dumper.sh` | shared state between jobs | every run works in a private, writable copy of the read-only checkout |

## Runner (`afid.dumprx`)

Before starting, `DumprX.problems()` must be empty: checkout present, marker equals the
pinned commit, `dumper.sh` hash matches, no credential file, `bash` available, and (with
`require_offline: true`, the default) no network reachable. Then it copies the checkout to a
private work directory, runs `bash dumper.sh <absolute local file>` with an **emptied
environment** (`PATH`, `HOME`, `LANG`, `TERM` only; no tokens can leak,
`test_dumprx_runs_with_clean_environment`), stdin closed, a timeout
(`dumprx.timeout_minutes`) and an output size limit (`limits.max_extracted_bytes`), and
returns the partition directories found in `out/`.

```bash
# inside the worker container (see CONTAINER_IMAGES.md for the full docker run line)
afid --root /workspace firmware dump --input /work/in/firmware.zip --workdir /work/job --ingest
afid --root /workspace providers health --provider dumprx    # are all guards satisfied?
```

`--ingest` catalogs the extracted tree through the `dumprx` provider (source type
`user_supplied_local_firmware`, distribution `user_supplied`). The extracted files stay in
the work directory; only metadata reaches `database/`, and DumprX output is never committed.

## Verified behaviour

On 2026-10-19 the worker image ran the pinned DumprX with `--network none` on a synthetic
ZIP holding ext4 `system.img` and `vendor.img`: exit code 0, `out/system` and `out/vendor`
extracted by 7-Zip, `all_files.txt` and `proprietary-files.txt` generated, and AFID cataloged
the tree. DumprX logged that `fsck.erofs`, `f2fs-extractor` and `mount` could not extract
`vendor` (expected for ext4, which 7-Zip had already handled) and that `git`/`sudo` are
missing, which is what blocks its publishing paths. Real vendor firmware has not been run
through DumprX in this repository yet.

## Licence review before publishing the worker image

The worker image combines AFID (Apache-2.0), DumprX (GPL-3.0-only) and DumprX's prebuilt
`utils/bin/*` binaries (7zz, payload-dumper-go, magiskboot, simg2img, fsck.erofs, e2fsck,
f2fs-extractor, ...) and helpers such as `utils/lpunpack`, whose licences and corresponding-source obligations have
not been reviewed. Until a human completes that review, `container-images.yml` builds and
tests the worker but never publishes it. A published image would also have to ship or
offer the GPL corresponding source.
