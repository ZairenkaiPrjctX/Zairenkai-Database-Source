# Changelog

All notable changes to this project are documented here. Format: Keep a Changelog;
versioning: SemVer.

## [Unreleased]

### Added
- Initial AFID implementation (0.1.0): codename-centric catalog, JSON Schemas (device,
  firmware, component, dependency, source, candidate, report), rule-based classifier,
  ELF/init/VINTF/build.prop/config parsers, dependency graph, distribution policy, safe
  extraction pipeline (ZIP, TAR, Android sparse, ext4 via debugfs; EROFS, super.img,
  payload.bin and LZ4 via external tools), provider registry with 11 providers,
  LineageOS wiki metadata discovery, update detection and history reports, `afid` CLI,
  six GitHub Actions workflows, documentation.
