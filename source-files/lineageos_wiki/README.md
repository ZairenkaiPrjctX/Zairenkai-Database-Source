# LineageOS Wiki source files

This directory contains the original device metadata YAML files from
[`LineageOS/lineage_wiki`](https://github.com/LineageOS/lineage_wiki/tree/main/_data/devices).
The files are copied unchanged so AFID contributors can inspect and compare the source data
directly in this repository. They are reference inputs; AFID's canonical, unverified device
candidates remain under `database/staging/unresolved/lineageos_wiki/`.

The upstream repository's [footer](https://github.com/LineageOS/lineage_wiki/blob/main/_includes/layout/footer.html)
states that the wiki is licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
Attribution: **The LineageOS Project**. These source files and adaptations are distributed under
the same share-alike license. They are not firmware images or vendor payloads.

`manifest.json` pins the upstream Git commit and records each file's SHA-256, Git blob id and
immutable source URL. The `Mirror LineageOS Wiki source files` Actions workflow refreshes this
directory and proposes a pull request. Each refresh is committed in batches of at most 50 files;
review and merge the pull request to add the new snapshot to the repository.
