# LineageOS Wiki device candidates (unverified)

**License of the JSON files in this directory: CC BY-SA 3.0**
(https://creativecommons.org/licenses/by-sa/3.0/), not the Apache-2.0 license of AFID's code.

Attribution: device metadata from the LineageOS Wiki (https://wiki.lineageos.org),
(c) The LineageOS Project, licensed under CC BY-SA 3.0. Source data:
https://github.com/LineageOS/lineage_wiki (`_data/devices/*.yml`); each record names the exact
file, git blob and commit it came from (`source.url`, `source.revision`, `source.snapshot`).

Changes made by AFID: only factual fields were selected (codename, product name, model
numbers, SoC, architecture, release date) and reshaped into AFID's candidate schema; brand
assignment was inferred by AFID from vendor and product-name prefix. No wiki prose,
instructions or images are copied. Redistribution of these files must keep this notice and
the same license (share-alike).

Basis for the license: the repository has no license file for `_data/devices/`; its footer
template (`_includes/layout/footer.html`) declares "Licensed under CC BY-SA 3.0" for every page
generated from this data (checked at commit 2c365be2b66336e4da1f3ca3bdd71c17eb819005 and on
https://wiki.lineageos.org/devices/oriole/, 2026-10-18). Recorded as `declared_by_source`.

Status: every record is `unverified` and is **not** counted as a verified device. No firmware
payload is associated with any record (`firmware_payload_ingested: false`). A candidate
becomes a verified device only through firmware evidence (`afid ingest --local`) or an
official source.
