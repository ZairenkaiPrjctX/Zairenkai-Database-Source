# Test fixtures

All fixtures are synthetic and written for AFID tests (same license as the repository).
No real firmware, vendor blob or third-party file is committed here.

- `elf/src/*.c`: C sources of the ELF fixtures. `elf/build.sh` rebuilds `elf/arm64/` and
  `elf/arm/` with clang + lld for Android targets. The binaries are a few KB, are never
  executed by AFID or its tests, and exist so the ELF parser is tested on real AArch64/ARM
  output rather than on hand-made bytes.
- `lineage_wiki/_data/devices/*.yml`: synthetic device files in the LineageOS wiki layout
  (fictional codenames), used to test the `lineageos_wiki` provider offline.

Firmware trees and archives are generated at test time in temporary directories
(see `tests/conftest.py`), never committed.
