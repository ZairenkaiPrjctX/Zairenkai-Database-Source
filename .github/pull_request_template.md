## Summary
<!-- What changes and why. -->

## Data changes
<!-- New/changed devices, firmware, components, providers. Link evidence for identity changes. -->

## Verification
| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest -q` | |
| Database | `afid database validate --check-index` | |
| Policy | `afid policy check` | |
| Audit | `afid security scan` | |

## Checklist
- [ ] Commits are cryptographically signed
- [ ] No firmware payload, vendor binary, token, serial number or IMEI in the diff
- [ ] New codenames are backed by firmware or official evidence (otherwise they stay in staging)
- [ ] Docs updated where behaviour changed
