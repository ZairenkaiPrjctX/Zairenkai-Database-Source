# Component classification

## Categories

`thermal_hal`, `thermal_service`, `thermal_config`, `thermal_engine`, `power_hal`,
`power_config`, `power_json`, `power_profile`, `performance_config`, `vendor_library`,
`init_service`, `init_script`, `vintf_manifest`, `supporting_metadata`, `unknown`.
New categories may be added; existing ones are never renamed.

## Rules

`config/component_rules.yml` holds the rules: path globs (`*` within a segment, `**` across
segments), optional `require_elf`, `confidence`, `reason`, optional `soc_vendors` tags.
Every matching rule is recorded on the component (`classification.rule_ids`, `reasons`); the
highest-confidence rule decides the category. Name-only rules (e.g. "file name contains
thermal") carry confidence below 0.5 and say that the name proves nothing.

SoC-specific knowledge (Qualcomm `thermal-engine`, `/etc/perf/`, `libqti-perf*`) is tagged
with `soc_vendors` and never applied as fact to other platforms. MediaTek, Exynos and
Tensor rules should be added the same way once verified on real firmware.

## What enters the catalog

- Files matched by a rule.
- `init*.rc` files only when they define a service whose name or binary matches
  `relevance_keywords`; the relevant services are listed. Other init files stay in the local
  inventory (`afid scan --inventory`).
- Unmatched files under `catalog_unknown_globs` (HAL directories, thermal/perf/power config
  directories) as category `unknown`, so new rules can be written for them later.
- Libraries reached through DT_NEEDED from cataloged components on vendor-side partitions
  (`vendor_library` / `resolved_dependency`), transitively.

Everything else is inventoried (path, size, SHA-256) but not committed.

## Content analysis (safe)

- ELF: class, endianness, machine, type, interpreter, SONAME, DT_NEEDED, RUNPATH (bounded
  pure-Python parser; cross-checked against `readelf` in tests).
- init `.rc`: services (binary, class, user, groups, capabilities, interfaces, flags),
  actions with property triggers and start/stop references, imports.
- VINTF: HAL names, formats, versions, instances. DTD/ENTITY declarations are rejected.
- Thermal/power configs: sensor and cooling-device names, powerhint nodes and hints,
  thermal-engine sections, referenced partition paths and kernel nodes.
- build.prop: an allowlist of build properties; serial numbers and other personal data are
  never stored.

## Dependency edges

| Type | From -> to | `resolved` when | `inferred` when |
|---|---|---|---|
| `dt_needed` | ELF -> library | found in the same partition's lib dir for the ELF class | found in another partition's lib dir |
| `init_service_binary` | init file -> service binary | binary exists at that path | - |
| `vintf_declares_hal` | manifest -> HAL service | name matches and an init `interface` declares it | name match only |
| `config_reference` | config -> referenced file | path exists | - |
| `hal_config` | HAL/engine binary -> config | - | config file name appears as a string in the binary |

Anything not found is `unresolved`. Android linker namespaces can resolve differently at
runtime; edges describe the image, not a running device.

## Adding a classifier

1. Add a rule to `config/component_rules.yml` with an honest confidence and reason.
2. Add a test with a fixture path to `tests/unit/test_core.py` or `tests/unit/test_scanner.py`.
3. Re-run ingestion (or `afid classify --input <tree>`) to see the effect.
